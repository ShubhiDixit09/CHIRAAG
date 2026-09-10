import math
import networkx as nx


# How dark to assume an unobserved street is under the "assume_typical"
# policy. This is not a guess: it is the length-weighted mean dark fraction
# of the streets we HAVE observed in the survey area (30.5 km unlit out of
# 123.8 km observed, ~0.25). Treating an unknown street as typical of its
# neighbours is a defensible prior; treating it as fully lit is not.
UNKNOWN_PRIOR_DARK_FRACTION = 0.25

# Multiplier on lambda for the "avoid" policy. At the night weighting of
# 0.65 this makes an unobserved street cost ~2.95x its length, enough to
# route around it whenever any observed alternative exists, without making
# it impassable when none does.
AVOID_UNKNOWN_WEIGHT = 3.0


def _dist(a, b) -> float:

    return math.hypot(a[0] - b[0], a[1] - b[1])


def _find_nearest_node(
    G: nx.MultiDiGraph,
    target_coords: tuple[float, float],
) -> tuple[tuple[float, float] | None, float]:
    """
    Find the nearest graph node to a (lon, lat) pair.

    Returns:
        (nearest_node, distance_in_metres)
    """
    target_lon, target_lat = target_coords

    lon_scale = 111320.0 * math.cos(math.radians(target_lat))
    lat_scale = 110574.0

    best_node = None
    min_dist = float("inf")

    for node in G.nodes():
        node_lon, node_lat = node

        dist = math.hypot(
            (node_lon - target_lon) * lon_scale,
            (node_lat - target_lat) * lat_scale,
        )

        if dist < min_dist:
            min_dist = dist
            best_node = node

    return best_node, min_dist


def _pick_edge(
    G: nx.MultiDiGraph,
    u,
    v,
) -> dict | None:
    """
    Choose one edge among parallel u->v edges.
    """
    edge_data = G.get_edge_data(u, v)

    if not edge_data:
        return None

    return min(
        edge_data.values(),
        key=lambda attrs: attrs.get(
            "length_m",
            float("inf"),
        ),
    )


def _time_of_day_weight(hour: int) -> float:
    """
    Bounded contextual multiplier for the safety-search weight.

    06:00–18:59 -> 1.00x
    19:00–21:59 -> 1.15x
    22:00–05:59 -> 1.30x

    This does NOT modify the stored lighting evidence.
    It only makes the routing decision more conservative at darker hours.
    """
    hour = int(hour) % 24

    if 6 <= hour < 19:
        return 1.0

    if 19 <= hour < 22:
        return 1.15

    return 1.30


def _calculate_edge_weight(
    d: dict,
    lam: float,
    unknown_policy: str = "neutral",
) -> float:
    """
    Calculate routing cost for parallel edges.

    Known segment:
        cost = distance + lambda * unlit exposure

    Unknown segment -- three stances toward the missing evidence:
        neutral        -> distance only; no assumption either way
        assume_typical -> scored at the observed network's average darkness
        avoid          -> heavily penalised, used only when unavoidable

    "show_gaps" is accepted as a deprecated alias for neutral so that an
    older deployed front end keeps working during a rollout.
    """
    best = float("inf")

    for attrs in d.values():
        length = float(
            attrs.get(
                "length_m",
                1.0,
            )
        )

        dark_frac = attrs.get("dark_fraction")

        observation_state = attrs.get(
            "observation_state",
            "unobserved",
        )

        is_unknown = (
            observation_state in {
                "unobserved",
                "unknown",
                "UNKNOWN",
            }
            or dark_frac is None
        )

        if is_unknown:
            if unknown_policy == "avoid":
                # Proportional to length, so a long unobserved road costs more
                # than a short one. The previous formula added a flat 500 m,
                # which punished a 20 m link ~18x and a 500 m road only ~2x --
                # backwards, since the long road carries far more unknown
                # exposure. Street networks split at every junction, so most
                # segments are short and that made 'avoid' behave as 'forbid'.
                cost = length * (
                    1.0 + lam * AVOID_UNKNOWN_WEIGHT
                )

            elif unknown_policy == "assume_typical":
                # Neither optimism nor prohibition: score the street as if it
                # were as dark as the average observed street. A prior, stated
                # openly, rather than a silent assumption that it is fine.
                cost = length + (
                    lam
                    * UNKNOWN_PRIOR_DARK_FRACTION
                    * length
                )

            else:
                cost = length

        else:
            dark_frac = float(
                dark_frac or 0.0
            )

            unlit_length = (
                dark_frac * length
            )

            cost = length + (
                lam * unlit_length
            )

        best = min(
            best,
            cost,
        )

    return best


def _path_segments(
    G: nx.MultiDiGraph,
    path_nodes: list,
) -> list[dict]:
    """
    Return one entry per physical street in the route.
    """
    segments = []

    for u, v in zip(
        path_nodes,
        path_nodes[1:],
    ):
        data = _pick_edge(
            G,
            u,
            v,
        )

        if data is None:
            continue

        geom = data.get("geometry")

        if geom is None:
            coords = [
                tuple(u),
                tuple(v),
            ]

        else:
            coords = [
                (x, y)
                for x, y in geom.coords
            ]

            if _dist(
                coords[0],
                u,
            ) > _dist(
                coords[-1],
                u,
            ):
                coords.reverse()

        segments.append(
            {
                "road_id": data.get("id"),
                "length_m": round(
                    float(
                        data.get(
                            "length_m",
                            0.0,
                        )
                    ),
                    2,
                ),
                "dark_fraction": data.get(
                    "dark_fraction"
                ),
                "observation_state": data.get(
                    "observation_state",
                    "unobserved",
                ),
                "coordinates": coords,
            }
        )

    return segments


def _path_geometry(
    G: nx.MultiDiGraph,
    path_nodes: list,
    tol: float = 1e-9,
) -> list:
    """
    Flatten per-segment geometry into one continuous polyline.
    """
    coords = []

    for segment in _path_segments(
        G,
        path_nodes,
    ):
        piece = segment["coordinates"]

        if (
            coords
            and _dist(
                coords[-1],
                piece[0],
            ) < tol
        ):
            piece = piece[1:]

        coords.extend(piece)

    return (
        coords
        or [
            tuple(node)
            for node in path_nodes
        ]
    )


def _get_path_metrics(
    G: nx.MultiDiGraph,
    path_nodes: list,
    lam: float = 0.0,
    unknown_policy: str = "neutral",
) -> dict:
    """
    Aggregate physical length, known-unlit exposure and unknown evidence.

    Unknown segments are NOT treated as dark.
    """
    total_length = 0.0
    total_unlit = 0.0
    unknown_length = 0.0

    for u, v in zip(
        path_nodes,
        path_nodes[1:],
    ):
        data = _pick_edge(
            G,
            u,
            v,
        )

        if data is None:
            continue

        length = float(
            data.get(
                "length_m",
                0.0,
            )
        )

        dark_frac = data.get(
            "dark_fraction"
        )

        observation_state = data.get(
            "observation_state",
            "unobserved",
        )

        total_length += length

        is_unknown = (
            observation_state in {
                "unobserved",
                "unknown",
                "UNKNOWN",
            }
            or dark_frac is None
        )

        if is_unknown:
            unknown_length += length

        else:
            total_unlit += (
                float(
                    dark_frac or 0.0
                )
                * length
            )

    coverage_ratio = (
        (total_length - unknown_length)
        / total_length
        if total_length > 0
        else 0.0
    )

    dark_fraction = (
        total_unlit / total_length
        if total_length > 0
        else 0.0
    )

    return {
        "total_length_m": round(
            total_length,
            2,
        ),
        "unlit_length_m": round(
            total_unlit,
            2,
        ),
        "unknown_length_m": round(
            unknown_length,
            2,
        ),
        "dark_fraction": round(
            dark_fraction,
            4,
        ),
        "coverage_ratio": round(
            coverage_ratio,
            4,
        ),
    }


def find_optimal_route(
    G: nx.MultiDiGraph,
    origin_coords: tuple[float, float],
    dest_coords: tuple[float, float],
    alpha: float = 1.20,
    unknown_policy: str = "neutral",
    hour: int = 23,
    max_snap_m: float = 250.0,
) -> dict:
    """
    Find the shortest route first, then select a safety-aware route
    within the allowed detour cap.

    `hour` applies a bounded contextual multiplier to the safety-search
    lambda. Stored lighting evidence and baseline metrics remain unchanged.
    """

    if not 0 <= int(hour) <= 23:
        raise ValueError(
            "hour must be between 0 and 23"
        )

    time_weighting_factor = (
        _time_of_day_weight(hour)
    )

    start_node, start_dist = (
        _find_nearest_node(
            G,
            origin_coords,
        )
    )

    end_node, end_dist = (
        _find_nearest_node(
            G,
            dest_coords,
        )
    )

    if (
        start_node is None
        or end_node is None
    ):
        raise ValueError(
            "Road network graph is empty."
        )

    if start_dist > max_snap_m:
        raise ValueError(
            f"Start point is {start_dist:.0f} m "
            "from the nearest mapped street. "
            "CHIRAAG only covers a small area "
            "of Delhi right now."
        )

    if end_dist > max_snap_m:
        raise ValueError(
            f"Destination is {end_dist:.0f} m "
            "from the nearest mapped street. "
            "CHIRAAG only covers a small area "
            "of Delhi right now."
        )

    # ------------------------------------------------------------------
    # 1. Baseline shortest-distance route
    # ------------------------------------------------------------------

    try:
        baseline_path = nx.dijkstra_path(
            G,
            start_node,
            end_node,
            weight=lambda u, v, d: _calculate_edge_weight(
                d,
                lam=0.0,
                unknown_policy=unknown_policy,
            ),
        )

    except nx.NetworkXNoPath:
        raise ValueError(
            "No walking route exists between "
            "these points in the mapped network."
        )

    baseline_metrics = _get_path_metrics(
        G,
        baseline_path,
        lam=0.0,
        unknown_policy=unknown_policy,
    )

    shortest_length = (
        baseline_metrics[
            "total_length_m"
        ]
    )

    max_allowed_length = (
        alpha * shortest_length
    )

    # ------------------------------------------------------------------
    # 2. Contextual safety-aware route
    # ------------------------------------------------------------------

    # Normal safety weighting = 0.5
    # Day    = 0.50
    # Dusk   = 0.575
    # Night  = 0.65
    lam = (
        0.5
        * time_weighting_factor
    )

    try:
        candidate_path = nx.dijkstra_path(
            G,
            start_node,
            end_node,
            weight=lambda u, v, d: _calculate_edge_weight(
                d,
                lam=lam,
                unknown_policy=unknown_policy,
            ),
        )

    except nx.NetworkXNoPath:
        candidate_path = baseline_path

    candidate_metrics = _get_path_metrics(
        G,
        candidate_path,
        lam=lam,
        unknown_policy=unknown_policy,
    )

    # Enforce detour constraint.
    if (
        candidate_metrics[
            "total_length_m"
        ]
        <= max_allowed_length
    ):
        best_path = candidate_path
        best_metrics = candidate_metrics

    else:
        best_path = baseline_path
        best_metrics = baseline_metrics

    # ------------------------------------------------------------------
    # 3. Evidence summary
    # ------------------------------------------------------------------

    unlit_avoided_m = (
        baseline_metrics[
            "unlit_length_m"
        ]
        - best_metrics[
            "unlit_length_m"
        ]
    )

    safety_gain_percent = (
        (
            unlit_avoided_m
            / baseline_metrics[
                "unlit_length_m"
            ]
        )
        * 100
        if baseline_metrics[
            "unlit_length_m"
        ] > 0
        else 0.0
    )

    # ------------------------------------------------------------------
    # 4. Response
    # ------------------------------------------------------------------

    return {
        "status": "success",

        "detour_multiplier_cap": alpha,

        "hour": int(hour),

        "time_weighting_factor": (
            time_weighting_factor
        ),

        "baseline_route": {
            "nodes": _path_geometry(
                G,
                baseline_path,
            ),
            "segments": _path_segments(
                G,
                baseline_path,
            ),
            "metrics": baseline_metrics,
        },

        "chiraag_route": {
            "nodes": _path_geometry(
                G,
                best_path,
            ),
            "segments": _path_segments(
                G,
                best_path,
            ),
            "metrics": best_metrics,
        },

        "evidence_summary": {
            "unlit_meters_avoided": round(
                max(
                    0.0,
                    unlit_avoided_m,
                ),
                2,
            ),

            "extra_distance_m": round(
                best_metrics[
                    "total_length_m"
                ]
                - shortest_length,
                2,
            ),

            "safety_gain_percent": round(
                safety_gain_percent,
                1,
            ),
        },
    }