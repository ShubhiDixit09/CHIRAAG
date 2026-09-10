"""
pipeline/ingest_imagery.py

Imagery coverage as evidence.

The lighting pipeline can only ever say two things about a street: a lamp was
detected near it, or no lamp was. That second case currently collapses into
observation_state='unobserved', which conflates two completely different
situations:

    1. No camera has ever travelled this street. We know nothing. Abstain.
    2. A camera travelled it and no street light was detected anywhere along
       it. That is evidence the street is dark, not an absence of evidence.

Only the first deserves 'unobserved'. This module measures which streets have
imagery coverage so the second can be scored as what it is.

Two modes:

    # measure first -- writes nothing, prints the projected impact
    python -m pipeline.ingest_imagery --probe --mapillary-token YOUR_TOKEN

    # then, if the numbers justify it, persist image counts
    python -m pipeline.ingest_imagery --mapillary-token YOUR_TOKEN

run_ingestion.py reads the persisted counts on its next scoring pass. Until
this has been run at least once the column is empty and scoring behaves
exactly as it did before, so this is safe to land ahead of the decision.
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import geopandas as gpd
import requests
from shapely.geometry import Point
from sqlalchemy import create_engine, text

from app.config import settings
from pipeline.snap_to_road import snap_lights_to_roads


MAPILLARY_URL = "https://graph.mapillary.com/images"

# The 3 km surveyed area around the ingestion centre, as minLon,minLat,maxLon,maxLat.
DEFAULT_BBOX = "77.1893,28.5949,77.2507,28.6491"

# Images are captured from the roadway itself, so they need a tighter radius
# than lamps -- but not tight enough to lose them to GPS drift.
IMAGE_ATTACH_RADIUS_M = 20.0

# Below this, imagery coverage is too thin to argue a street is dark: one
# passing photo says nothing about the far end of a 200 m road.
MIN_IMAGES_FOR_DARK = 3

# Deliberately not 1.0. A detector that missed a lamp is a real possibility,
# so an imagery-derived dark score should sit below anything measured from a
# lamp that was actually seen.
IMAGED_DARK_FRACTION = 0.7

# Mapillary caps a single response; at the cap we cannot tell a full page from
# a truncated one, so the tile is subdivided instead.
RESULT_CAP = 2000


def _split_bbox(bbox):
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
    mid_lon = (min_lon + max_lon) / 2
    mid_lat = (min_lat + max_lat) / 2
    return [
        f"{min_lon},{min_lat},{mid_lon},{mid_lat}",
        f"{mid_lon},{min_lat},{max_lon},{mid_lat}",
        f"{min_lon},{mid_lat},{mid_lon},{max_lat}",
        f"{mid_lon},{mid_lat},{max_lon},{max_lat}",
    ]


def _fetch_tile(bbox, access_token, depth=0, max_depth=4, quiet=False):
    """
    Fetch image positions for one bounding box, subdividing when a response
    comes back at the result cap.

    Same shape as ingest_mapillary._fetch_tile, deliberately: a truncated tile
    silently understates coverage, which would show up as streets we wrongly
    believe were never photographed.
    """
    params = {
        "fields": "id,computed_geometry,geometry",
        "bbox": bbox,
        "limit": RESULT_CAP,
    }
    headers = {"Authorization": f"OAuth {access_token}"}

    try:
        response = requests.get(
            MAPILLARY_URL, params=params, headers=headers, timeout=60
        )
        status = response.status_code
    except requests.RequestException as exc:
        if not quiet:
            print(f"  request error on {bbox}: {exc}")
        response, status = None, "network error"

    if response is not None and status == 200:
        data = response.json().get("data", [])
        if not quiet:
            print(f"  {bbox} -> {len(data)} images")
        if len(data) < RESULT_CAP:
            return data
        if not quiet:
            print("    (at result cap -- subdividing so coverage is not truncated)")
    elif depth >= max_depth:
        if not quiet:
            print(f"  giving up on {bbox} (HTTP {status})")
        return []
    else:
        if not quiet:
            print(f"  HTTP {status} on {bbox} -- subdividing")

    if depth >= max_depth:
        return data if response is not None and status == 200 else []

    features = []
    for sub in _split_bbox(bbox):
        time.sleep(0.25)
        features.extend(
            _fetch_tile(sub, access_token, depth + 1, max_depth, quiet)
        )
    return features


def fetch_image_points(bbox, access_token, quiet=False):
    """Return a GeoDataFrame of de-duplicated image positions."""
    if not quiet:
        print(f"Fetching imagery coverage for bbox {bbox} (auto-tiling as needed)...")

    raw = _fetch_tile(bbox, access_token, quiet=quiet)

    points, seen = [], set()
    for item in raw:
        iid = str(item.get("id"))
        if iid in seen:
            continue

        # computed_geometry is the structure-from-motion refined position and
        # is markedly better than the raw GPS fix; fall back when absent.
        geom = item.get("computed_geometry") or item.get("geometry")
        if not geom or "coordinates" not in geom:
            continue

        seen.add(iid)
        lon, lat = geom["coordinates"][0], geom["coordinates"][1]
        points.append({"id": iid, "geometry": Point(lon, lat)})

    if not quiet:
        print(f"{len(raw)} returned, {len(points)} distinct image positions")

    if not points:
        return gpd.GeoDataFrame(
            {"id": [], "geometry": []}, geometry="geometry", crs="EPSG:4326"
        )

    return gpd.GeoDataFrame(points, geometry="geometry", crs="EPSG:4326")


def load_roads(engine):
    return gpd.read_postgis(
        "SELECT id, length_m, observation_state, geom AS geometry FROM road_segments",
        engine,
        geom_col="geometry",
    )


def count_images_per_road(roads_gdf, images_gdf):
    """
    {road_id: image_count} using the same multi-attachment join as lamps, so an
    image near a junction counts for every street it could have photographed.
    """
    if images_gdf.empty or roads_gdf.empty:
        return {}

    attached = snap_lights_to_roads(
        roads_gdf, images_gdf, radius=IMAGE_ATTACH_RADIUS_M
    )
    return {road_id: len(positions) for road_id, positions in attached.items()}


def report(roads_gdf, image_counts):
    """Print what these counts would change, without changing anything."""
    unobserved = roads_gdf[roads_gdf["observation_state"] == "unobserved"]

    would_flip = [
        r for r in unobserved["id"]
        if image_counts.get(r, 0) >= MIN_IMAGES_FOR_DARK
    ]

    covered_any = sum(1 for r in unobserved["id"] if image_counts.get(r, 0) > 0)
    total = len(roads_gdf)
    already = total - len(unobserved)

    print()
    print("---- projected impact -------------------------------------------")
    print(f"  streets in the network            : {total:>6,}")
    print(f"  already carrying lighting evidence: {already:>6,}  ({100*already/total:.1f}%)")
    print(f"  unobserved today                  : {len(unobserved):>6,}")
    print(f"    of those, some imagery          : {covered_any:>6,}")
    print(f"    of those, >= {MIN_IMAGES_FOR_DARK} images          : {len(would_flip):>6,}  <- would become imaged-dark")
    after = already + len(would_flip)
    print(f"  evidence coverage after           : {after:>6,}  ({100*after/total:.1f}%)")
    print("-----------------------------------------------------------------")

    if len(would_flip) < 100:
        print("  Thin result. Imagery is sparse here; the gain may not justify")
        print("  the time. Consider stopping and spending it elsewhere.")
    else:
        print("  Worth persisting. Re-run without --probe, then re-run")
        print("  pipeline.run_ingestion to apply the new scores.")


def persist(engine, roads_gdf, image_counts):
    """Write image counts, adding the column on first use."""
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS image_count INTEGER"
        ))

    updates = [
        {"id": int(r), "image_count": int(image_counts.get(r, 0))}
        for r in roads_gdf["id"]
    ]

    print(f"Writing image counts for {len(updates)} road segments...")

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE road_segments SET image_count = :image_count WHERE id = :id"),
            updates,
        )

    print("Done. Re-run pipeline.run_ingestion to turn these counts into scores.")


def main():
    parser = argparse.ArgumentParser(
        description="Measure imagery coverage per road segment."
    )
    parser.add_argument("--mapillary-token", required=True,
                        help="Mapillary API access token.")
    parser.add_argument("--bbox", default=DEFAULT_BBOX,
                        help="minLon,minLat,maxLon,maxLat. Defaults to the "
                             "surveyed area around the ingestion centre.")
    parser.add_argument("--probe", action="store_true",
                        help="Measure and report only -- write nothing.")
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    print(f"Database: {settings.database_summary}")

    roads_gdf = load_roads(engine)
    print(f"{len(roads_gdf)} road segments loaded.")

    if roads_gdf.empty:
        print("No road segments -- run the OSM ingestion first.")
        return

    images_gdf = fetch_image_points(args.bbox, args.mapillary_token)

    if images_gdf.empty:
        print("No imagery returned. Nothing to do.")
        return

    print("Attaching images to streets...")
    image_counts = count_images_per_road(roads_gdf, images_gdf)
    print(f"{len(image_counts)} streets have at least one image nearby.")

    report(roads_gdf, image_counts)

    if args.probe:
        print("\n(probe mode -- nothing written)")
        return

    persist(engine, roads_gdf, image_counts)


if __name__ == "__main__":
    main()
