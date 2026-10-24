"""
Comprehensive Specification Tests for Milestone 1:
Backend Mathematical Core & Modern Cellular Data Filtering.

Covers:
  1. Spherical Haversine (R=6,371,000m, SI metres, 1um numerical precision).
  2. Co-Located Mast Resolution (<= 2m) with pre-FPS aggregation & range_source inheritance.
  3. Graph Topological Diagnostics: coordinate_diversity in [0.0, 1.0] and delta_g.
  4. Modern Cellular Filtering: Strictly 4G/5G, legacy 2G/3G rejected on schemas and endpoints.
  5. Deterministic FPS Sampling: monotonic Haversine a-value, deterministic tie-breaking.
  6. Data Provenance Accounting: available >= eligible >= selected >= 0, excluded breakdown.
  7. Coverage Radii Fallback Hierarchy: 4G=800m, 5G=500m, clamped [50m, 10000m].
  8. Algorithmic Solvers: DSatur saturation stats, Welsh-Powell degree ordering, reuse breakdown.
  9. Independent 100% Validator: color collisions, zero-distance edges, boundary violations.
  10. Educational Boundaries Structured Object: EducationalDisclaimer across POST responses.
"""

import pytest
from fastapi.testclient import TestClient
import networkx as nx

from app import app
from data_service import (
    haversine_distance,
    EARTH_RADIUS_METRES,
    RADIO_FALLBACK_RADII,
    DEFAULT_FALLBACK_RADIUS,
    normalize_radio_type,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    aggregate_towers_within_distance,
    normalize_cell_record,
)
from graph_engine import (
    build_interference_graph,
    get_graph_metrics,
    validate_coloring,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
)
from schemas import (
    CellRecord,
    SiteEntity,
    AccountingMetadata,
    GraphBuildRequest,
    OptimizeRequest,
    CompareRequest,
    EDUCATIONAL_DISCLAIMER_DEFAULT,
)


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# 1. Spherical Haversine (R=6,371,000m, SI metres, 1um precision)
# ==============================================================================
def test_spherical_haversine_precision_and_si_constants():
    """Verify Haversine uses spherical Earth radius R=6,371,000m with micrometre precision."""
    assert EARTH_RADIUS_METRES == 6_371_000.0

    # Distance at identical coordinates is exactly 0.0m
    d_zero = haversine_distance(28.52000, 77.19000, 28.52000, 77.19000)
    assert d_zero == 0.0

    # 1 micrometre separation test (0.00000001 deg lat is ~1.11 mm; 0.00000000001 is sub-um)
    d_sub_mm = haversine_distance(0.0, 0.0, 0.00000001, 0.0)
    assert 0.001 < d_sub_mm < 0.0012  # ~1.11 mm

    # Quarter meridian (Equator to Pole): pi/2 * 6,371,000 m = ~10,007,543.4m
    d_quarter = haversine_distance(0.0, 0.0, 90.0, 0.0)
    expected_quarter = (3.141592653589793 / 2.0) * 6_371_000.0
    assert abs(d_quarter - expected_quarter) < 1.0


# ==============================================================================
# 2. Co-Located Mast Resolution (<= 2m)
# ==============================================================================
def test_colocated_aggregation_preserves_range_source_from_max_sector():
    """Verify aggregate_towers_within_distance preserves range_source from the max_range sector."""
    cluster = [
        {
            "tower_id": "SEC_1",
            "latitude": 28.52000,
            "longitude": 77.19000,
            "range_m": 400.0,
            "range_source": "fallback_default",
            "fallback_reason": "missing_range",
            "radio": "4G",
        },
        {
            "tower_id": "SEC_2",
            "latitude": 28.520005,
            "longitude": 77.19000,
            "range_m": 950.0,
            "range_source": "reported",
            "fallback_reason": None,
            "radio": "5G",
        },
    ]

    aggregated = aggregate_towers_within_distance(cluster, 2.0)
    assert len(aggregated) == 1
    mast = aggregated[0]
    assert mast["range_m"] == 950.0
    assert mast["range_source"] == "reported"
    assert mast["fallback_reason"] is None
    assert mast["radio"] == "5G"
    assert mast["is_co_located"] is True
    assert mast["sector_count"] == 2


def test_native_aggregate_2m_in_build_interference_graph():
    """Verify native aggregate_2m parameter in build_interference_graph merges <= 2m sites."""
    cells = [
        {"tower_id": f"S1_{i}", "latitude": 28.52000, "longitude": 77.19000, "range_m": 800.0, "radio": "4G"}
        for i in range(5)
    ]
    # Without aggregate_2m: 5 nodes, complete clique (10 edges)
    g_raw = build_interference_graph(cells, aggregate_2m=False)
    assert g_raw.number_of_nodes() == 5
    assert g_raw.number_of_edges() == 10

    # With aggregate_2m: 1 node, 0 edges
    g_agg = build_interference_graph(cells, aggregate_2m=True)
    assert g_agg.number_of_nodes() == 1
    assert g_agg.number_of_edges() == 0


def test_process_tower_records_pre_fps_aggregation(client, monkeypatch):
    """Verify that aggregate_2m runs before FPS in _process_tower_records."""
    # Create 10 cells total: 6 cells at site A, 4 cells at site B
    mock_cells = []
    for i in range(6):
        mock_cells.append({
            "tower_id": f"SITE_A_{i}",
            "latitude": 28.52000,
            "longitude": 77.19000,
            "radio": "LTE",
            "range_m": 800.0,
        })
    for i in range(4):
        mock_cells.append({
            "tower_id": f"SITE_B_{i}",
            "latitude": 28.53000,
            "longitude": 77.19000,
            "radio": "NR",
            "range_m": 500.0,
        })

    async def fake_fetch(*args, **kwargs):
        return mock_cells, [], False

    monkeypatch.setattr("app.fetch_opencellid_records", fake_fetch)

    # Calling GET /api/towers with aggregate_2m=true consolidates the 10 cells into 2 sites
    res = client.get("/api/towers?lat=28.52&lon=77.19&radius_m=2000&aggregate_2m=true&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2
    assert len(data["towers"]) == 2
    assert data["accounting"]["available_count"] == 10
    assert data["accounting"]["eligible_count"] == 10
    assert data["accounting"]["selected_count"] == 2
    assert data["accounting"]["excluded_count"] == 8


# ==============================================================================
# 3. Graph Topological Diagnostics: coordinate_diversity & delta_g
# ==============================================================================
def test_coordinate_diversity_and_delta_g():
    """Verify coordinate_diversity and delta_g are accurate topological invariants."""
    # Graph 1: 4 nodes at identical coordinates (diversity = 1/4 = 0.25, delta_g = 3)
    clique_cells = [
        {"tower_id": f"C_{i}", "latitude": 28.52000, "longitude": 77.19000, "range_m": 800.0, "radio": "4G"}
        for i in range(4)
    ]
    g_clique = build_interference_graph(clique_cells)
    metrics_clique = get_graph_metrics(g_clique)
    assert metrics_clique["coordinate_diversity"] == 0.25
    assert metrics_clique["delta_g"] == 3
    assert metrics_clique["max_degree"] == 3

    # Graph 2: 4 nodes at distinct dispersed coordinates (diversity = 4/4 = 1.0)
    dispersed_cells = [
        {"tower_id": f"D_{i}", "latitude": 28.52000 + i * 0.01, "longitude": 77.19000, "range_m": 800.0, "radio": "4G"}
        for i in range(4)
    ]
    g_dispersed = build_interference_graph(dispersed_cells)
    metrics_dispersed = get_graph_metrics(g_dispersed)
    assert metrics_dispersed["coordinate_diversity"] == 1.0


# ==============================================================================
# 4. Modern Cellular Filtering: Strictly 4G/5G, legacy 2G/3G rejected
# ==============================================================================
def test_legacy_radios_purged_from_fallback_radii():
    """Verify dead legacy radio entries are purged from RADIO_FALLBACK_RADII."""
    assert "GSM" not in RADIO_FALLBACK_RADII
    assert "2G" not in RADIO_FALLBACK_RADII
    assert "CDMA" not in RADIO_FALLBACK_RADII
    assert "UMTS" not in RADIO_FALLBACK_RADII
    assert "3G" not in RADIO_FALLBACK_RADII
    assert set(RADIO_FALLBACK_RADII.keys()) == {"4G", "5G", "LTE", "NR"}


def test_post_endpoints_strictly_reject_legacy_radios(client):
    """Verify POST /api/graph/build, /api/optimize, and /api/compare reject GSM/2G/3G with 422."""
    legacy_cells = [
        {"tower_id": "LEGACY_1", "latitude": 28.52, "longitude": 77.19, "radio": "GSM", "range_m": 800.0}
    ]

    for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
        payload = {"cells": legacy_cells}
        if endpoint != "/api/graph/build":
            payload["algorithm"] = "both"
        res = client.post(endpoint, json=payload)
        assert res.status_code == 422, f"{endpoint} should reject GSM with 422, got {res.status_code}"


# ==============================================================================
# 5. Deterministic FPS Sampling & Ceilings
# ==============================================================================
def test_fps_sampling_determinism_and_limit():
    """Verify FPS sampling respects limits and produces identical results regardless of input order."""
    records = [
        {"tower_id": f"T_{i}", "latitude": 28.52 + (i % 5) * 0.005, "longitude": 77.19 + (i // 5) * 0.005, "radio": "4G"}
        for i in range(25)
    ]

    selected_1 = select_spatially_dispersed_records(records, 28.52, 77.19, limit=10)
    assert len(selected_1) == 10

    # Reversed order input
    reversed_records = list(reversed(records))
    selected_2 = select_spatially_dispersed_records(reversed_records, 28.52, 77.19, limit=10)
    assert [r["tower_id"] for r in selected_1] == [r["tower_id"] for r in selected_2]


# ==============================================================================
# 6. Data Provenance Accounting Invariants
# ==============================================================================
def test_accounting_invariants():
    """Verify AccountingMetadata satisfies all mathematical reduction invariants."""
    meta = AccountingMetadata(
        available_count=100,
        eligible_count=70,
        selected_count=50,
        excluded_count=50,
        excluded_radio_count=30,
        excluded_limit_count=20,
    )
    assert meta.available_count >= meta.eligible_count >= meta.selected_count >= 0
    assert meta.excluded_count == meta.excluded_radio_count + meta.excluded_limit_count

    # Invalid invariant must raise ValueError
    with pytest.raises(ValueError):
        AccountingMetadata(
            available_count=50,
            eligible_count=70,  # eligible cannot exceed available
            selected_count=50,
            excluded_count=0,
            excluded_radio_count=-20,
            excluded_limit_count=20,
        )


# ==============================================================================
# 7. Coverage Radii Fallback Hierarchy & Clamping
# ==============================================================================
def test_fallback_radii_hierarchy():
    """Verify 4G=800m, 5G=500m, clamping to [50m, 10000m]."""
    rec_4g = normalize_cell_record({"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 0})
    assert rec_4g["range_m"] == 800.0
    assert rec_4g["is_range_estimated"] is True

    rec_5g = normalize_cell_record({"cellid": 2, "lat": 28.5, "lon": 77.2, "radio": "5G", "range": 0})
    assert rec_5g["range_m"] == 500.0
    assert rec_5g["is_range_estimated"] is True

    # Clamping
    rec_low = normalize_cell_record({"cellid": 3, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 10})
    assert rec_low["range_m"] == 50.0
    assert rec_low["is_range_estimated"] is True

    rec_high = normalize_cell_record({"cellid": 4, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 25000})
    assert rec_high["range_m"] == 10000.0
    assert rec_high["is_range_estimated"] is True


# ==============================================================================
# 8. Algorithmic Solvers: Diagnostic stats & Channel Reuse Breakdown
# ==============================================================================
def test_solver_diagnostics_and_breakdown():
    """Verify Welsh-Powell and DSatur produce diagnostics and channel_reuse_breakdown."""
    cells = [
        {"tower_id": f"T_{i}", "latitude": 28.520 + i * 0.002, "longitude": 77.190, "range_m": 800.0, "radio": "4G"}
        for i in range(6)
    ]
    graph = build_interference_graph(cells)

    res_wp = color_welsh_powell(graph)
    assert "degree_ordering_stats" in res_wp
    assert "channel_reuse_breakdown" in res_wp
    assert "chi_heuristic" in res_wp
    assert res_wp["degree_ordering_stats"]["max_degree"] == get_graph_metrics(graph)["max_degree"]

    res_ds = color_dsatur(graph)
    assert "saturation_stats" in res_ds
    assert "channel_reuse_breakdown" in res_ds
    assert "chi_heuristic" in res_ds
    assert len(res_ds["saturation_stats"]["selection_order"]) == 6


# ==============================================================================
# 9. Independent 100% Validator: Zero-distance & Boundary violations
# ==============================================================================
def test_validator_zero_distance_and_boundary_violations():
    """Verify independent validator detects zero-distance edges and boundary violations."""
    # Build graph with 2 co-located vertices (0m separation) and 1 distant vertex
    G = nx.Graph()
    G.add_node("C1")
    G.add_node("C2")
    G.add_node("D1")

    # Add zero-distance edge between C1 and C2
    G.add_edge("C1", "C2", distance_m=0.0, threshold_m=1600.0)

    # Valid coloring with distinct colors
    val1 = validate_coloring(G, {"C1": 0, "C2": 1, "D1": 0})
    assert val1["is_valid"] is True
    assert val1["edges_inspected"] == 1
    assert val1["zero_distance_count"] == 1
    assert len(val1["zero_distance_edges"]) == 1
    assert val1["boundary_violation_count"] == 0

    # Now add an edge that violates geometric boundary (dist=2000m > threshold=1000m)
    G.add_edge("C1", "D1", distance_m=2000.0, threshold_m=1000.0)
    val2 = validate_coloring(G, {"C1": 0, "C2": 1, "D1": 2})
    assert val2["is_valid"] is False  # Invalidation due to boundary violation
    assert val2["boundary_violation_count"] == 1
    assert val2["edges_inspected"] == 2


# ==============================================================================
# 10. Educational Boundaries Structured Object
# ==============================================================================
def test_educational_disclaimer_present_in_responses(client):
    """Verify educational_disclaimer and agreement flag are exposed in API responses."""
    cells = [
        {"tower_id": "T1", "latitude": 28.520, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": 28.525, "longitude": 77.190, "range_m": 800.0, "radio": "5G"},
    ]

    # Graph build response
    r_build = client.post("/api/graph/build", json={"cells": cells})
    assert r_build.status_code == 200
    data_build = r_build.json()
    assert "educational_disclaimer" in data_build
    assert data_build["educational_disclaimer"]["is_educational_simulation"] is True

    # Optimize response
    r_opt = client.post("/api/optimize", json={"cells": cells, "algorithm": "both"})
    assert r_opt.status_code == 200
    data_opt = r_opt.json()
    assert "educational_disclaimer" in data_opt
    assert "colors_used" in data_opt
    assert "chi_heuristic" in data_opt
    assert "runtime_ms" in data_opt

    # Compare response
    r_comp = client.post("/api/compare", json={"cells": cells})
    assert r_comp.status_code == 200
    data_comp = r_comp.json()
    assert "educational_disclaimer" in data_comp
    assert "agreement" in data_comp
    assert isinstance(data_comp["agreement"], bool)
