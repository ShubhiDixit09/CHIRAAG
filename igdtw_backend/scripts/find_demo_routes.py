"""
scripts/find_demo_routes.py

Find the journeys that actually demonstrate the product.

Picking demo routes by eye does not work. Of the three presets this project
originally shipped, two returned a route identical to the shortest path -- not
because the router was broken, but because on those particular corridors the
shortest way really was already the least-exposed one. A correct result and a
dead demo at the same time.

So measure instead. This evaluates every pair of named places against the live
database, through the same graph builder and router the API uses, and ranks
them by how much unlit street the safer route actually avoids.

    python -m scripts.find_demo_routes
    python -m scripts.find_demo_routes --area hauz-khas
    python -m scripts.find_demo_routes --places my_places.json --top 15

A places file is JSON: {"Name": [lon, lat], ...}

Read the output as a whole, not just the top line. A big "avoided" figure on a
route with 30% coverage is a weaker demo than a smaller one at 75%, because
the first invites "so how much of that route do you actually know about?" and
the second answers it.
"""

import argparse
import itertools
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.db import SessionLocal
from app.services.graph_builder import build_graph_from_db, _distance_m
from app.services.routing import find_optimal_route


# Coordinates are approximate -- good to a hundred metres or so. That is fine:
# the router snaps to the nearest street within 250 m, and anything it cannot
# snap is reported as skipped rather than silently dropped.
AREAS = {
    "central": {
        "India Gate": (77.2295, 28.6129),
        "Connaught Place": (77.2167, 28.6315),
        "Jantar Mantar": (77.2166, 28.6271),
        "Patel Chowk": (77.2144, 28.6236),
        "Central Secretariat": (77.2122, 28.6152),
        "National Museum": (77.2194, 28.6118),
        "Mandi House": (77.2344, 28.6258),
        "Barakhamba Road": (77.2249, 28.6294),
        "Janpath": (77.2185, 28.6242),
        "Shivaji Stadium": (77.2118, 28.6280),
        "Bengali Market": (77.2318, 28.6296),
        "Bangla Sahib": (77.2090, 28.6262),
        "Agrasen ki Baoli": (77.2249, 28.6253),
        "RML Hospital": (77.2016, 28.6262),
        "Gole Market": (77.2065, 28.6335),
        "Palika Bazaar": (77.2177, 28.6304),
    },
    "hauz-khas": {
        "Hauz Khas Village": (77.1937, 28.5535),
        "Hauz Khas Fort": (77.1929, 28.5538),
        "Deer Park": (77.1965, 28.5555),
        "Hauz Khas Metro": (77.2065, 28.5433),
        "Green Park Market": (77.2060, 28.5580),
        "IIT Delhi Main Gate": (77.1926, 28.5450),
        "SDA Market": (77.1975, 28.5478),
        "Yusuf Sarai": (77.2010, 28.5540),
        "Kalu Sarai": (77.1990, 28.5430),
        "Hauz Khas Enclave": (77.1980, 28.5490),
        "Shahpur Jat": (77.2100, 28.5525),
        "Gulmohar Park": (77.2050, 28.5545),
        "Aurobindo Market": (77.2035, 28.5497),
        "Asiad Village": (77.2120, 28.5570),
    },
}


def evaluate(session, name_a, origin, name_b, dest, alpha, hour, policy):
    graph = build_graph_from_db(session, origin_coords=origin, dest_coords=dest)

    if graph.number_of_nodes() == 0:
        return None, "no streets in range"

    try:
        result = find_optimal_route(
            G=graph,
            origin_coords=origin,
            dest_coords=dest,
            alpha=alpha,
            unknown_policy=policy,
            hour=hour,
        )
    except ValueError as exc:
        # Out of area, or no walking path between them. Both are useful to see.
        return None, str(exc).split(".")[0]

    baseline = result["baseline_route"]["metrics"]
    safer = result["chiraag_route"]["metrics"]
    summary = result["evidence_summary"]

    return {
        "journey": f"{name_a} -> {name_b}",
        "avoided": summary["unlit_meters_avoided"],
        "gain": summary["safety_gain_percent"],
        "extra": summary["extra_distance_m"],
        "baseline_m": baseline["total_length_m"],
        "safer_m": safer["total_length_m"],
        "coverage": min(baseline["coverage_ratio"], safer["coverage_ratio"]),
    }, None


def main():
    parser = argparse.ArgumentParser(
        description="Rank journeys by how well they demonstrate safer routing."
    )
    parser.add_argument("--area", choices=sorted(AREAS), default="central",
                        help="Built-in set of named places to evaluate.")
    parser.add_argument("--places", default=None,
                        help='JSON file of {"Name": [lon, lat]}, overrides --area.')
    parser.add_argument("--hour", type=int, default=23,
                        help="Hour of day for the routing weight (default 23).")
    parser.add_argument("--alpha", type=float, default=1.20,
                        help="Detour cap multiplier (default 1.20 = 20%%).")
    parser.add_argument("--policy", default="neutral",
                        help="neutral | assume_typical | avoid")
    parser.add_argument("--min-m", type=float, default=500.0,
                        help="Ignore pairs closer than this (default 500 m).")
    parser.add_argument("--max-m", type=float, default=2600.0,
                        help="Ignore pairs further than this (default 2600 m).")
    parser.add_argument("--top", type=int, default=12,
                        help="How many journeys to print (default 12).")
    args = parser.parse_args()

    if args.places:
        with open(args.places, encoding="utf-8") as handle:
            places = {k: tuple(v) for k, v in json.load(handle).items()}
    else:
        places = AREAS[args.area]

    print(f"Database: {settings.database_summary}")
    print(f"{len(places)} places, {args.hour}:00, detour cap "
          f"{round((args.alpha - 1) * 100)}%, unknown policy '{args.policy}'\n")

    session = SessionLocal()
    rows, skipped = [], []

    try:
        for (name_a, a), (name_b, b) in itertools.combinations(places.items(), 2):
            separation = _distance_m(a, b)

            if not (args.min_m <= separation <= args.max_m):
                continue

            row, problem = evaluate(session, name_a, a, name_b, b,
                                    args.alpha, args.hour, args.policy)

            if row is None:
                skipped.append(f"{name_a} -> {name_b}: {problem}")
            else:
                rows.append(row)
    finally:
        session.close()

    rows.sort(key=lambda r: r["avoided"], reverse=True)
    dead = sum(1 for r in rows if r["avoided"] <= 0)

    print(f"{'journey':<44} {'avoided':>8} {'gain':>7} {'extra':>6} "
          f"{'safer':>7} {'observed':>9}")
    for row in rows[:args.top]:
        print(f"{row['journey']:<44} {row['avoided']:>7.0f}m {row['gain']:>6.1f}% "
              f"{row['extra']:>5.0f}m {row['safer_m']:>6.0f}m "
              f"{100 * row['coverage']:>8.0f}%")

    print(f"\n{len(rows)} routable pairs; {dead} of them show no improvement "
          f"(the shortest route was already the least exposed).")

    if skipped:
        print(f"\n{len(skipped)} pairs could not be routed:")
        for line in skipped[:10]:
            print(f"   {line}")
        if len(skipped) > 10:
            print(f"   ... and {len(skipped) - 10} more")

    good = [r for r in rows if r["avoided"] > 0 and r["coverage"] >= 0.5]
    if good:
        best = good[0]
        print(f"\nBest all-round demo: {best['journey']} -- "
              f"{best['avoided']:.0f} m of unlit street avoided for "
              f"{best['extra']:.0f} m extra, {100 * best['coverage']:.0f}% observed.")
    else:
        print("\nNothing here clears both bars (some improvement, at least 50% "
              "observed). Widen the search or pick a better-covered area.")


if __name__ == "__main__":
    main()
