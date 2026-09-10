import geopandas as gpd

# Metric CRS for Delhi (UTM zone 43N). Every distance below is in metres, which
# is only true once the geometries are projected into it.
PROJECTED_CRS = 32643

# How far a lamp can stand from a road and still be treated as lighting it.
ATTACH_RADIUS_M = 25.0


def snap_lights_to_roads(roads_gdf, lights_gdf, radius=ATTACH_RADIUS_M):
    """
    Map each streetlight onto every road it plausibly lights.

    Returns {road_id: [distance_along_road_m, ...]}, each list sorted, ready
    for gap_analysis.calculate_segment_metrics.

    A lamp attaches to EVERY road within `radius`, not only the nearest one.
    sjoin_nearest returns a single match per lamp, so a light standing at a
    four-way junction was credited to whichever arm happened to be marginally
    closer while the other three were scored as though it did not exist. Since
    junctions are exactly where lamps get installed, that single-match rule was
    discarding a large share of the evidence we already have -- and roads left
    with no lamp at all fall through to observation_state='unobserved', where
    the router treats them as carrying no information whatsoever.

    This does not change what a lamp is assumed to illuminate. That is
    gap_analysis's coverage_radius, which still models a lamp as lighting
    +/- 25 m along the road centreline.
    """
    roads_projected = roads_gdf.to_crs(epsg=PROJECTED_CRS)
    lights_projected = lights_gdf.to_crs(epsg=PROJECTED_CRS)
    roads_indexed = roads_projected.set_index("id")

    # Join on a disc around each lamp instead of nearest-neighbour, so one lamp
    # can match several roads. The original point is carried in its own column
    # because the projection below has to measure from the lamp itself, not
    # from the edge of its buffer.
    lights_buffered = lights_projected.copy()
    lights_buffered["light_point"] = lights_projected.geometry
    lights_buffered["geometry"] = lights_projected.geometry.buffer(radius)

    joined = gpd.sjoin(
        lights_buffered,
        roads_projected,
        how="inner",
        predicate="intersects",
    )

    snapped_data = {}

    for _, row in joined.iterrows():
        road_id = row["id_right"]
        road_geom = roads_indexed.loc[road_id, "geometry"]
        point_geom = row["light_point"]

        # Distance from the road's start point to the point on the road
        # nearest the lamp. gap_analysis turns these into lit intervals.
        distance_along_road = road_geom.project(point_geom)

        snapped_data.setdefault(road_id, []).append(distance_along_road)

    for road_id in snapped_data:
        snapped_data[road_id].sort()

    return snapped_data
