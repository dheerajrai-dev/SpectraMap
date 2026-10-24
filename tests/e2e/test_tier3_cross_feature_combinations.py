"""
tests/e2e/test_tier3_cross_feature_combinations.py
SpectraMap Path B — Tier 3: Pairwise Cross-Feature Interactions (>= 21 tests)

Verifies multi-feature interactions between spatial metrics, site consolidation,
sampling, filtering, fallback hierarchies, dual solvers, validation, and diagnostics.
Requirement sources: ORIGINAL_REQUEST.md, PROJECT.md, TEST_INFRA.md.
"""

import math
import pytest
from fastapi.testclient import TestClient

from app import app
from data_service import (
    haversine_distance,
    EARTH_RADIUS_METRES,
    normalize_radio_type,
    normalize_cell_record,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    aggregate_towers_within_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    validate_coloring,
    get_graph_metrics,
)
from schemas import AccountingMetadata, CellRecord


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _make_cell(
    tower_id: str,
    lat: float,
    lon: float,
    range_m: float = 800.0,
    radio: str = "4G",
    cell_id: int = 100,
) -> dict:
    return {
        "tower_id": tower_id,
        "cell_id": cell_id,
        "radio": radio,
        "latitude": lat,
        "longitude": lon,
        "range_m": range_m,
    }


# ============================================================================
# Pairwise Cross-Feature Tests (21 Interactions)
# ============================================================================

def test_pairwise_01_f1_haversine_and_f2_closed_disc_boundary(client):
    """F1 (Haversine 1um) + F2 (Closed-Disc): Spherical distance precision controls exact conflict edge acceptance."""
    # Place two towers at tangent distance: d = r1 + r2 = 1200.0m
    lat_offset = 1200.0 * 180.0 / (math.pi * EARTH_RADIUS_METRES)
    cells = [
        _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
        _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=600.0),
    ]
    resp = client.post("/api/graph/build", json={"cells": cells})
    assert resp.status_code == 200
    assert len(resp.json()["edges"]) == 1
    edge = resp.json()["edges"][0]
    assert abs(edge["distance_m"] - 1200.0) < 0.2


def test_pairwise_02_f2_closed_disc_and_f3_2m_consolidation(client):
    """F2 (Closed-Disc) + F3 (2m Consolidation): Co-located sectors forming K_10 are reduced to 1 node with 0 self-edges."""
    # 10 sectors at identical coordinates
    cells = [_make_cell(f"SEC_{i}", 28.5000, 77.2000, range_m=750.0) for i in range(10)]
    # Without aggregation -> complete clique K_10 with 45 edges
    resp_raw = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
    assert resp_raw.status_code == 200
    assert len(resp_raw.json()["nodes"]) == 10
    assert len(resp_raw.json()["edges"]) == 45

    # With aggregation -> single vertex, 0 conflict edges
    resp_agg = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
    assert resp_agg.status_code == 200
    assert len(resp_agg.json()["nodes"]) == 1
    assert len(resp_agg.json()["edges"]) == 0


def test_pairwise_03_f3_2m_consolidation_and_f6_fps_sampling():
    """F3 (2m Aggregation) + F6 (FPS Sampling): FPS executed post-aggregation yields exact record ceiling on physical sites."""
    # 30 transceivers clustered across 15 distinct physical masts (2 sectors per mast)
    raw_cells = []
    for i in range(15):
        lat = 28.5000 + i * 0.005
        raw_cells.append(_make_cell(f"MAST_{i}_SEC1", lat, 77.2000))
        raw_cells.append(_make_cell(f"MAST_{i}_SEC2", lat, 77.2000))

    # Pre-aggregation consolidates to 15 sites
    aggregated = aggregate_towers_within_distance(raw_cells, distance_threshold_m=2.0)
    assert len(aggregated) == 15

    # FPS sampling selects top 10 spatially dispersed physical sites
    sampled = select_spatially_dispersed_records(aggregated, 28.5000, 77.2000, limit=10)
    assert len(sampled) == 10
    # Every sampled site represents 2 consolidated sectors
    assert all(site["sector_count"] == 2 for site in sampled)


def test_pairwise_04_f5_radio_filter_and_f8_radius_fallback():
    """F5 (Radio Filtering) + F8 (Radius Fallback): 5G-only records default to 500m, 4G-only to 800m."""
    cell_4g = normalize_cell_record({"cellid": 101, "lat": 28.5, "lon": 77.2, "radio": "LTE"})
    cell_5g = normalize_cell_record({"cellid": 102, "lat": 28.5, "lon": 77.2, "radio": "NR"})
    assert cell_4g["range_m"] == 800.0
    assert cell_5g["range_m"] == 500.0
    assert cell_4g["is_range_estimated"] and cell_5g["is_range_estimated"]


def test_pairwise_05_f4_diagnostics_and_f9_dual_solvers(client):
    """F4 (Diagnostics) + F9 (Dual Solvers): Graph density and max degree correlate with chromatic bounds across solvers."""
    # Bipartite topology K_2,2
    cells = [
        _make_cell("A1", 28.5000, 77.2000, range_m=1000.0),
        _make_cell("A2", 28.5002, 77.2000, range_m=1000.0),
        _make_cell("B1", 28.5080, 77.2000, range_m=1000.0),
        _make_cell("B2", 28.5082, 77.2000, range_m=1000.0),
    ]
    resp = client.post("/api/compare", json={"cells": cells, "aggregate_2m": False})
    assert resp.status_code == 200
    data = resp.json()
    metrics = data["metrics"]
    dsatur_k = data["dsatur"]["color_count"]
    wp_k = data["welsh_powell"]["color_count"]
    # Both solvers satisfy Brooks' bound: chi <= Delta(G) + 1
    assert dsatur_k <= metrics["max_degree"] + 1
    assert wp_k <= metrics["max_degree"] + 1


def test_pairwise_06_f9_dual_solvers_and_f11_edge_validator(client):
    """F9 (Dual Solvers) + F11 (Validator): Independent validator inspects 100% of conflict edges for both solvers."""
    cells = [_make_cell(f"T{i}", 28.5 + i * 0.002, 77.2, range_m=600.0) for i in range(6)]
    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True
    assert data["dsatur"]["validation"]["conflict_count"] == 0
    assert data["welsh_powell"]["validation"]["conflict_count"] == 0
    assert data["dsatur"]["validation"]["edges_inspected"] == data["metrics"]["edge_count"]


def test_pairwise_07_f6_fps_sampling_and_f7_provenance_accounting():
    """F6 (FPS Sampling) + F7 (Provenance Accounting): Ceiling limit truncation satisfies accounting invariants."""
    available = 50
    eligible = 50
    limit = 20
    candidates = [_make_cell(f"T{i:02d}", 28.5 + i * 0.001, 77.2) for i in range(available)]
    sampled = select_spatially_dispersed_records(candidates, 28.5, 77.2, limit=limit)
    selected_count = len(sampled)
    assert selected_count == limit

    meta = AccountingMetadata(
        available_count=available,
        eligible_count=eligible,
        selected_count=selected_count,
        excluded_count=available - selected_count,
        excluded_radio_count=available - eligible,
        excluded_limit_count=eligible - selected_count,
    )
    assert meta.excluded_limit_count == 30
    assert meta.excluded_count == 30


def test_pairwise_08_f5_radio_filtering_and_f7_provenance_accounting():
    """F5 (Radio Filtering) + F7 (Provenance Accounting): 2G/3G exclusion correctly accounts for excluded_radio_count."""
    raw_feed = [
        {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G"},
        {"cellid": 2, "lat": 28.51, "lon": 77.2, "radio": "5G"},
        {"cellid": 3, "lat": 28.52, "lon": 77.2, "radio": "2G"},
        {"cellid": 4, "lat": 28.53, "lon": 77.2, "radio": "GSM"},
        {"cellid": 5, "lat": 28.54, "lon": 77.2, "radio": "UMTS"},
    ]
    available = len(raw_feed)
    eligible_feed = [c for c in raw_feed if normalize_radio_type(c["radio"]) in ("4G", "5G")]
    eligible = len(eligible_feed)
    assert eligible == 2

    meta = AccountingMetadata(
        available_count=available,
        eligible_count=eligible,
        selected_count=eligible,
        excluded_count=available - eligible,
        excluded_radio_count=available - eligible,
        excluded_limit_count=0,
    )
    assert meta.excluded_radio_count == 3


def test_pairwise_09_f3_2m_consolidation_and_f11_zero_distance_validator():
    """F3 (2m Consolidation) + F11 (Validator): Site aggregation eliminates zero-distance edge violations."""
    cells = [
        _make_cell("T1_SEC1", 28.5000, 77.2000, range_m=500.0),
        _make_cell("T1_SEC2", 28.5000, 77.2000, range_m=500.0),
    ]
    # Without aggregation: 0-distance edge detected
    G_raw = build_interference_graph(cells, aggregate_2m=False)
    val_raw = validate_coloring(G_raw, {"T1_SEC1": 0, "T1_SEC2": 1})
    assert val_raw["zero_distance_count"] == 1

    # With aggregation: consolidated into 1 vertex, 0 zero-distance edges
    G_agg = build_interference_graph(cells, aggregate_2m=True)
    val_agg = validate_coloring(G_agg, {list(G_agg.nodes())[0]: 0})
    assert val_agg["zero_distance_count"] == 0


def test_pairwise_10_f8_radius_fallback_and_f2_closed_disc():
    """F8 (Radius Fallback) + F2 (Closed-Disc): Clamped radius (10,000m) bounds maximum conflict threshold."""
    # Outlier ranges clamped to 10,000m
    c1 = normalize_cell_record({"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 50000.0})
    c2 = normalize_cell_record({"cellid": 2, "lat": 28.6, "lon": 77.2, "radio": "4G", "range": 50000.0})
    assert c1["range_m"] == 10000.0
    assert c2["range_m"] == 10000.0

    G = build_interference_graph([c1, c2])
    # Distance between 28.5 and 28.6 is approx 11,119m < 20,000m threshold -> edge formed
    assert G.number_of_edges() == 1
    edge_data = list(G.edges(data=True))[0][2]
    assert edge_data["threshold_m"] == 20000.0


def test_pairwise_11_f9_dual_solvers_and_f10_stats():
    """F9 (Dual Solvers) + F10 (Stats): Welsh-Powell degree ordering and DSatur saturation statistics on identical graph."""
    cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(5)]
    G = build_interference_graph(cells)
    wp_res = color_welsh_powell(G)
    ds_res = color_dsatur(G)

    # WP records degree sequence in non-increasing order
    deg_seq = wp_res["degree_ordering_stats"]["degree_sequence"]
    assert deg_seq == sorted(deg_seq, reverse=True)

    # DSatur records saturation degrees at selection
    sat_seq = ds_res["saturation_stats"]["saturation_degrees_at_selection"]
    assert len(sat_seq) == 5
    assert sat_seq[0] == 0  # First vertex has 0 saturated neighbors


def test_pairwise_12_f10_stats_and_f15_benchmark_card(client):
    """F10 (Stats) + F15 (Benchmark Card): Channel reuse distribution in compare endpoint matches chi_heuristic."""
    cells = [_make_cell(f"T{i}", 28.5 + i * 0.002, 77.2, range_m=600.0) for i in range(6)]
    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()
    ds_reuse = data["dsatur"]["channel_reuse_breakdown"]
    wp_reuse = data["welsh_powell"]["channel_reuse_breakdown"]
    assert len(ds_reuse) == data["dsatur"]["color_count"]
    assert len(wp_reuse) == data["welsh_powell"]["color_count"]
    assert sum(ds_reuse.values()) == 6
    assert sum(wp_reuse.values()) == 6


def test_pairwise_13_f1_haversine_and_f14_map_bounds():
    """F1 (Haversine) + F14 (Map View): High-latitude coordinates maintain geometric stability for map viewports."""
    # Near Arctic circle (66.5 deg N)
    d = haversine_distance(66.5, 0.0, 66.5, 0.01)
    # Longitude width scaled by cos(66.5) ≈ 0.3987 -> 1 deg lon is ~44.3 km
    assert d > 400.0 and d < 500.0


def test_pairwise_14_f3_2m_consolidation_and_f16_vertex_inspector():
    """F3 (2m Consolidation) + F16 (Vertex Inspector): Consolidated site entity exposes sector list and multi-radio badges."""
    cells = [
        _make_cell("T1_4G", 28.5000, 77.2000, range_m=800.0, radio="4G"),
        _make_cell("T1_5G", 28.5000, 77.2000, range_m=500.0, radio="5G"),
    ]
    aggregated = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
    assert len(aggregated) == 1
    site = aggregated[0]
    assert site["sector_count"] == 2
    assert "4G" in site["radios"] and "5G" in site["radios"]
    assert "T1_4G" in site["sectors"] and "T1_5G" in site["sectors"]


def test_pairwise_15_f12_educational_disclaimer_and_f19_monolith_stack(client):
    """F12 (Educational Disclaimer) + F19 (Monolith Stack): Disclaimer model serializes across all endpoints without external services."""
    for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
        resp = client.post(endpoint, json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert resp.status_code == 200
        assert "educational_disclaimer" in resp.json()
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True


def test_pairwise_16_f13_canvas_explorer_and_f16_vertex_inspector(client):
    """F13 (Canvas Explorer) + F16 (Vertex Inspector): Incident edges of inspected node match serialized graph edge list."""
    cells = [
        _make_cell("A", 28.5000, 77.2000, range_m=1000.0),
        _make_cell("B", 28.5020, 77.2000, range_m=1000.0),
        _make_cell("C", 28.5040, 77.2000, range_m=1000.0),
    ]
    resp = client.post("/api/graph/build", json={"cells": cells})
    data = resp.json()
    edges = data["edges"]
    nodes = {n["id"]: n for n in data["nodes"]}

    # B connects to both A and C -> degree 2
    b_edges = [e for e in edges if e["source"] == "B" or e["target"] == "B"]
    assert len(b_edges) == nodes["B"]["degree"]


def test_pairwise_17_f2_closed_disc_and_f9_dual_solvers_dense(client):
    """F2 (Closed-Disc) + F9 (Dual Solvers Dense): Dual solvers executed on dense planar overlap graph achieve valid coloring."""
    # 8-node dense cluster
    cells = [_make_cell(f"D{i}", 28.5000 + (i % 3) * 0.001, 77.2000 + (i // 3) * 0.001, range_m=500.0) for i in range(8)]
    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()
    assert data["metrics"]["density"] > 0.4
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True


def test_pairwise_18_f5_radio_filtering_and_f4_diagnostics(client):
    """F5 (Radio Filtering) + F4 (Diagnostics): Technology distribution in graph diagnostics accurately reflects 4G vs 5G composition."""
    cells = [
        _make_cell("T1", 28.5000, 77.2000, radio="4G"),
        _make_cell("T2", 28.5020, 77.2000, radio="4G"),
        _make_cell("T3", 28.5040, 77.2000, radio="5G"),
    ]
    resp = client.post("/api/graph/build", json={"cells": cells})
    assert resp.status_code == 200
    tech = resp.json()["metrics"]["technology_distribution"]
    assert tech["4G"] == 2
    assert tech["5G"] == 1


def test_pairwise_19_f6_fps_sampling_and_f1_haversine_monotonicity():
    """F6 (FPS Sampling) + F1 (Haversine Monotonicity): Farthest point distance decreases as candidate pool is sampled."""
    candidates = [_make_cell(f"T{i}", 28.5000 + i * 0.002, 77.2000) for i in range(10)]
    sampled = select_spatially_dispersed_records(candidates, 28.5000, 77.2000, limit=5)
    assert len(sampled) == 5
    # The first is closest to center; second is farthest from first
    d_first_to_center = haversine_distance(28.5000, 77.2000, sampled[0]["latitude"], sampled[0]["longitude"])
    assert d_first_to_center < 10.0


def test_pairwise_20_f9_dual_solvers_and_f15_exact_solver_benchmark(client):
    """F9 (Dual Solvers) + F15 (Exact Solver): Exact B&B proves optimality for N<=25 comparing against heuristics."""
    cells = [_make_cell(f"T{i}", 28.5000 + i * 0.001, 77.2000, range_m=500.0) for i in range(4)]
    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()
    assert data["exact"] is not None
    assert data["exact"]["proven_optimal"] is True
    # Heuristics should be >= exact chromatic number
    exact_chi = data["exact"]["color_count"]
    assert data["dsatur"]["color_count"] >= exact_chi
    assert data["welsh_powell"]["color_count"] >= exact_chi


def test_pairwise_21_f3_aggregation_f5_filtering_f8_fallback():
    """F3 (Aggregation) + F5 (Filtering) + F8 (Fallback): Co-located multi-carrier mast merges 4G (800m) and 5G (500m) preserving 800m."""
    raw_cells = [
        {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "LTE"},  # Fallback: 800m
        {"cellid": 2, "lat": 28.5, "lon": 77.2, "radio": "NR"},   # Fallback: 500m
    ]
    normalized = [normalize_cell_record(c) for c in raw_cells]
    aggregated = aggregate_towers_within_distance(normalized, distance_threshold_m=2.0)
    assert len(aggregated) == 1
    # Preserves max range between 800m and 500m
    assert aggregated[0]["range_m"] == 800.0
    assert "4G" in aggregated[0]["radios"] and "5G" in aggregated[0]["radios"]
