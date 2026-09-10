import networkx as nx

from app.services.routing import (
    find_optimal_route,
    AVOID_UNKNOWN_WEIGHT,
    _calculate_edge_weight,
    _get_path_metrics,
    _path_geometry,
    _time_of_day_weight,
)


def _parallel(**attrs):
    """
    Wrap one edge's attributes the way NetworkX hands them to a weight
    function: a dict keyed by parallel-edge index.
    """
    return {0: attrs}


# --------------------------------------------------------------------------
# Edge cost
# --------------------------------------------------------------------------

def test_edge_weight_scales_with_lambda():
    """cost = length + lambda * (dark_fraction * length)"""
    edge = _parallel(
        length_m=100.0,
        dark_fraction=0.5,
        observation_state="predicted",
    )

    assert _calculate_edge_weight(edge, lam=0.0) == 100.0
    assert _calculate_edge_weight(edge, lam=2.0) == 200.0
    assert _calculate_edge_weight(edge, lam=10.0) == 600.0


def test_edge_weight_picks_cheapest_parallel_edge():
    """With parallel edges between the same nodes, the cheapest one wins."""
    edges = {
        0: dict(
            length_m=100.0,
            dark_fraction=0.9,
            observation_state="predicted",
        ),
        1: dict(
            length_m=110.0,
            dark_fraction=0.0,
            observation_state="predicted",
        ),
    }

    assert _calculate_edge_weight(edges, lam=0.0) == 100.0
    assert _calculate_edge_weight(edges, lam=2.0) == 110.0


def test_unknown_segment_is_not_priced_as_dark():
    """An unobserved road costs plain distance under the neutral policy."""
    edge = _parallel(
        length_m=100.0,
        dark_fraction=None,
        observation_state="unobserved",
    )

    assert (
        _calculate_edge_weight(
            edge,
            lam=10.0,
            unknown_policy="neutral",
        )
        == 100.0
    )


def test_avoid_policy_penalises_unknown_segments():
    """Under 'avoid', unknown roads cost a multiple of their own length."""
    edge = _parallel(
        length_m=100.0,
        dark_fraction=None,
        observation_state="unobserved",
    )

    neutral = _calculate_edge_weight(
        edge,
        lam=2.0,
        unknown_policy="neutral",
    )

    avoid = _calculate_edge_weight(
        edge,
        lam=2.0,
        unknown_policy="avoid",
    )

    assert avoid > neutral

    # Stated as the rule rather than a magic number, so tuning the weight does
    # not silently invalidate the test. Previously this asserted 1300.0, which
    # pinned the flat "+ 500 m" formula that penalised short streets far more
    # harshly than long ones.
    assert avoid == 100.0 * (1.0 + 2.0 * AVOID_UNKNOWN_WEIGHT)


# --------------------------------------------------------------------------
# Path metrics
# --------------------------------------------------------------------------

def test_metrics_on_empty_path_do_not_raise():
    """
    Regression test for a single-node path with no edges.
    """
    G = nx.MultiDiGraph()
    G.add_node((0.0, 0.0))

    metrics = _get_path_metrics(
        G,
        [(0.0, 0.0)],
    )

    assert metrics["total_length_m"] == 0.0
    assert metrics["coverage_ratio"] == 0.0
    assert metrics["dark_fraction"] == 0.0


def test_unknown_length_is_separate_from_unlit(unknown_graph):
    """Unobserved road counts as unknown, never as unlit."""
    metrics = _get_path_metrics(
        unknown_graph,
        [
            (0.0, 0.0),
            (0.0, 1.0),
            (1.0, 1.0),
        ],
    )

    assert metrics["total_length_m"] == 120.0
    assert metrics["unlit_length_m"] == 0.0
    assert metrics["unknown_length_m"] == 120.0
    assert metrics["coverage_ratio"] == 0.0


# --------------------------------------------------------------------------
# Route selection
# --------------------------------------------------------------------------

def test_lambda_sweep_selects_safer_detour(mock_graph):
    """Routing trades extra distance for lower unlit exposure."""
    result = find_optimal_route(
        G=mock_graph,
        origin_coords=(0.0, 0.0),
        dest_coords=(1.0, 1.0),
        alpha=1.30,
    )

    assert result["status"] == "success"

    baseline = result["baseline_route"]["metrics"]

    assert baseline["total_length_m"] == 100.0
    assert baseline["dark_fraction"] == 0.9

    chiraag = result["chiraag_route"]["metrics"]

    assert chiraag["total_length_m"] == 120.0
    assert chiraag["dark_fraction"] == 0.0

    assert (
        result["evidence_summary"]["unlit_meters_avoided"]
        == 90.0
    )

    assert (
        result["evidence_summary"]["extra_distance_m"]
        == 20.0
    )

    assert (
        result["evidence_summary"]["safety_gain_percent"]
        == 100.0
    )


def test_detour_cap_rejects_the_safer_route(mock_graph):
    """
    With alpha=1.10 the 120 m detour exceeds the 110 m budget,
    so the dark baseline must be returned unchanged.
    """
    result = find_optimal_route(
        G=mock_graph,
        origin_coords=(0.0, 0.0),
        dest_coords=(1.0, 1.0),
        alpha=1.10,
    )

    assert (
        result["chiraag_route"]["metrics"]["total_length_m"]
        == 100.0
    )

    assert (
        result["evidence_summary"]["unlit_meters_avoided"]
        == 0.0
    )

    assert (
        result["evidence_summary"]["extra_distance_m"]
        == 0.0
    )


def test_graph_is_traversable_in_both_directions(mock_graph):
    """
    Routing backwards must work as well as forwards.
    """
    result = find_optimal_route(
        G=mock_graph,
        origin_coords=(1.0, 1.0),
        dest_coords=(0.0, 0.0),
        alpha=1.30,
    )

    assert (
        result["chiraag_route"]["metrics"]["total_length_m"]
        == 120.0
    )


def test_unknown_policy_avoid_prefers_the_known_road(unknown_graph):
    """
    Under 'avoid', a known-dark road beats an unobserved detour.
    """
    result = find_optimal_route(
        G=unknown_graph,
        origin_coords=(0.0, 0.0),
        dest_coords=(1.0, 1.0),
        alpha=1.30,
        unknown_policy="avoid",
    )

    assert (
        result["chiraag_route"]["metrics"]["total_length_m"]
        == 100.0
    )


def _unknown_edge(length):
    return _parallel(
        length_m=length,
        dark_fraction=None,
        observation_state="unobserved",
    )


def test_avoid_penalty_scales_with_length():
    """
    A long unobserved street must cost proportionally more than a short one.

    The original formula added a flat 500 m, so a 20 m link was penalised
    about 18x while a 500 m road -- carrying twenty-five times as much unknown
    exposure -- got away with roughly 2x. Same multiplier at every length now.
    """
    lam = 0.65
    short = _calculate_edge_weight(_unknown_edge(20.0), lam=lam, unknown_policy="avoid")
    long_ = _calculate_edge_weight(_unknown_edge(500.0), lam=lam, unknown_policy="avoid")

    assert abs((short / 20.0) - (long_ / 500.0)) < 1e-9
    assert long_ > short


def test_the_three_policies_are_actually_distinct():
    """
    Each stance must price an unobserved street differently.

    'show_gaps' used to occupy this slot and was byte-for-byte identical to
    neutral, so selecting it in the UI changed precisely nothing.
    """
    lam = 0.65
    edge = _unknown_edge(100.0)

    neutral = _calculate_edge_weight(edge, lam=lam, unknown_policy="neutral")
    typical = _calculate_edge_weight(edge, lam=lam, unknown_policy="assume_typical")
    avoid = _calculate_edge_weight(edge, lam=lam, unknown_policy="avoid")

    assert neutral == 100.0
    assert neutral < typical < avoid


def test_show_gaps_still_behaves_as_neutral_for_older_clients():
    """
    Deprecated alias: a front end deployed before the rename must not break.
    """
    edge = _unknown_edge(100.0)

    assert (
        _calculate_edge_weight(edge, lam=0.65, unknown_policy="show_gaps")
        == _calculate_edge_weight(edge, lam=0.65, unknown_policy="neutral")
    )


def test_assume_typical_changes_which_route_wins():
    """
    The prior must be strong enough to matter and mild enough not to ban.

    A known road 45% dark against an unobserved detour: neutral takes the
    detour because it looks free, avoid refuses it outright, and
    assume_typical prices it as an average street and picks the known road.
    """
    G = nx.MultiDiGraph()
    A, MID, D = (0.0, 0.0), (0.0, 1.0), (1.0, 1.0)

    for u, v, attrs in (
        (A, D, dict(id=1, length_m=100.0, dark_fraction=0.45,
                    observation_state="predicted")),
        (A, MID, dict(id=2, length_m=60.0, dark_fraction=None,
                      observation_state="unobserved")),
        (MID, D, dict(id=3, length_m=60.0, dark_fraction=None,
                      observation_state="unobserved")),
    ):
        G.add_edge(u, v, **attrs)
        G.add_edge(v, u, **attrs)

    def route(policy):
        return find_optimal_route(
            G=G, origin_coords=A, dest_coords=D,
            alpha=1.30, unknown_policy=policy,
        )["chiraag_route"]["metrics"]["total_length_m"]

    assert route("neutral") == 120.0          # unobserved detour looks free
    assert route("assume_typical") == 100.0   # priced as typical -> known road
    assert route("avoid") == 100.0            # refused outright -> known road


# --------------------------------------------------------------------------
# Time-of-day weighting
# --------------------------------------------------------------------------

def test_time_of_day_weight_is_bounded():
    assert _time_of_day_weight(12) == 1.0
    assert _time_of_day_weight(20) == 1.15
    assert _time_of_day_weight(23) == 1.30
    assert _time_of_day_weight(3) == 1.30


def test_time_of_day_can_change_route_choice():
    """
    Night weighting can justify a modestly longer,
    better-lit bypass.
    """
    G = nx.MultiDiGraph()

    A = (0.0, 0.0)
    M = (0.0, 1.0)
    D = (1.0, 1.0)

    def add_bidirectional(u, v, **attrs):
        G.add_edge(u, v, **attrs)
        G.add_edge(v, u, **attrs)

    add_bidirectional(
        A,
        D,
        id=1,
        length_m=100.0,
        dark_fraction=0.30,
        observation_state="predicted",
    )

    add_bidirectional(
        A,
        M,
        id=2,
        length_m=57.5,
        dark_fraction=0.05,
        observation_state="audited",
    )

    add_bidirectional(
        M,
        D,
        id=3,
        length_m=57.5,
        dark_fraction=0.05,
        observation_state="audited",
    )

    day = find_optimal_route(
        G,
        A,
        D,
        alpha=1.20,
        hour=12,
    )

    night = find_optimal_route(
        G,
        A,
        D,
        alpha=1.20,
        hour=23,
    )

    assert day["time_weighting_factor"] == 1.0
    assert night["time_weighting_factor"] == 1.30

    assert (
        day["chiraag_route"]["metrics"]["total_length_m"]
        == 100.0
    )

    assert (
        night["chiraag_route"]["metrics"]["total_length_m"]
        == 115.0
    )

    assert (
        day["baseline_route"]["metrics"]
        == night["baseline_route"]["metrics"]
    )


# --------------------------------------------------------------------------
# Returned geometry
# --------------------------------------------------------------------------

def test_path_geometry_includes_interior_vertices(curved_graph):
    """
    Returned coordinates follow the street,
    not straight chords between intersections.
    """
    A = (77.2120, 28.6120)
    B = (77.2120, 28.6135)
    C = (77.2125, 28.6150)

    coords = _path_geometry(
        curved_graph,
        [A, B, C],
    )

    assert len(coords) > 3
    assert tuple(coords[0]) == A
    assert tuple(coords[-1]) == C

    assert (
        77.2128,
        28.6142,
    ) in [tuple(c) for c in coords]


def test_path_geometry_orients_reversed_edges(curved_graph):
    """
    Reversed street geometry must be returned
    in traversal order.
    """
    A = (77.2120, 28.6120)
    B = (77.2120, 28.6135)
    C = (77.2125, 28.6150)

    coords = [
        tuple(c)
        for c in _path_geometry(
            curved_graph,
            [A, B, C],
        )
    ]

    assert (
        coords.index(B)
        < coords.index((77.2128, 28.6142))
        < coords.index(C)
    )

    assert len(coords) == len(set(coords))


def test_path_geometry_falls_back_without_geometry(mock_graph):
    """Synthetic graphs without geometry return endpoints."""
    coords = _path_geometry(
        mock_graph,
        [
            (0.0, 0.0),
            (1.0, 1.0),
        ],
    )

    assert [
        tuple(c)
        for c in coords
    ] == [
        (0.0, 0.0),
        (1.0, 1.0),
    ]