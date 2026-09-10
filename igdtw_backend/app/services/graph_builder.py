import math

import networkx as nx
import shapely.wkb
from sqlalchemy import text


def _distance_m(a, b):

    lon1, lat1 = a
    lon2, lat2 = b

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    dlat = lat2 - lat1
    dlon = math.radians(lon2 - lon1)

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * 6371000 * math.asin(math.sqrt(h))


def _routing_bbox(origin_coords, dest_coords):

    ox, oy = origin_coords
    dx, dy = dest_coords
#f
    straight_distance_m = _distance_m(
        origin_coords,
        dest_coords,
    )

    # Rough conversion from metres to degrees.
    lat_margin = max(
        0.015,
        (straight_distance_m * 0.25) / 111000.0,
    )

    # Longitude degrees are narrower at Delhi's latitude.
    mean_lat = math.radians((oy + dy) / 2)
    lon_metres_per_degree = 111320.0 * math.cos(mean_lat)

    lon_margin = max(
        0.015,
        (straight_distance_m * 0.25)
        / lon_metres_per_degree,
    )

    min_lon = min(ox, dx) - lon_margin
    max_lon = max(ox, dx) + lon_margin

    min_lat = min(oy, dy) - lat_margin
    max_lat = max(oy, dy) + lat_margin

    return (
        min_lon,
        min_lat,
        max_lon,
        max_lat,
    )


def build_graph_from_db(
    db_session,
    origin_coords=None,
    dest_coords=None,
) -> nx.MultiDiGraph:


    G = nx.MultiDiGraph()

    params = {}

    if origin_coords is not None and dest_coords is not None:
        (
            min_lon,
            min_lat,
            max_lon,
            max_lat,
        ) = _routing_bbox(
            origin_coords,
            dest_coords,
        )

        params = {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
        }

        query = text("""
            SELECT
                id,
                osm_id,
                length_m,
                dark_fraction,
                longest_gap_m,
                calibrated_lighting_prob,
                observation_state,
                ST_AsBinary(geom) AS geom_wkb
            FROM road_segments
            WHERE geom && ST_MakeEnvelope(
                :min_lon,
                :min_lat,
                :max_lon,
                :max_lat,
                4326
            )
            AND ST_Intersects(
                geom,
                ST_MakeEnvelope(
                    :min_lon,
                    :min_lat,
                    :max_lon,
                    :max_lat,
                    4326
                )
            )
        """)

    else:
        # Backwards-compatible fallback.
        #
        # The router will be updated to always provide coordinates, so this
        # path should not be used during normal routing.
        query = text("""
            SELECT
                id,
                osm_id,
                length_m,
                dark_fraction,
                longest_gap_m,
                calibrated_lighting_prob,
                observation_state,
                ST_AsBinary(geom) AS geom_wkb
            FROM road_segments
        """)

    result = db_session.execute(
        query,
        params,
    ).fetchall()

    for row in result:
        if row.geom_wkb is None:
            continue

        line_geom = shapely.wkb.loads(
            bytes(row.geom_wkb)
        )

        coords = list(line_geom.coords)

        if len(coords) < 2:
            continue

        start_node = coords[0]
        end_node = coords[-1]

        edge_attrs = dict(
            id=row.id,
            osm_id=row.osm_id,
            length_m=float(
                row.length_m or 0.0
            ),


            dark_fraction=(
                float(row.dark_fraction)
                if row.dark_fraction is not None
                else None
            ),

            longest_gap_m=(
                float(row.longest_gap_m)
                if row.longest_gap_m is not None
                else None
            ),

            calibrated_prob=(
                float(
                    row.calibrated_lighting_prob
                )
                if row.calibrated_lighting_prob is not None
                else 0.5
            ),

            observation_state=row.observation_state,


            geometry=line_geom,
        )

        G.add_edge(
            start_node,
            end_node,
            **edge_attrs,
        )

        G.add_edge(
            end_node,
            start_node,
            **edge_attrs,
        )

    return G