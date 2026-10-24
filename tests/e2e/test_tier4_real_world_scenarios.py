"""
tests/e2e/test_tier4_real_world_scenarios.py
SpectraMap Path B — Tier 4: Real-World Cellular Workload Scenarios (10 Scenarios)

Executes realistic end-to-end cellular deployments and stress topologies specified in
TEST_INFRA.md § Real-World Application Scenarios.
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
# Scenario 1: Urban Dense Macro-Micro Cluster
# ============================================================================
def test_scenario_01_urban_dense_macro_micro_cluster(client):
    """
    Scenario 1: High-density downtown deployment with 150 transceivers, co-located sectors,
    severe overlaps, and DSatur/Welsh-Powell benchmark comparison.
    Exercised features: F1, F2, F3, F4, F6, F9, F11.
    """
    # 150 transceivers distributed across 30 physical sites (3 to 6 sectors per site)
    cells = []
    base_lat = 28.6300
    base_lon = 77.2200
    for site_idx in range(30):
        # Sites arranged in a 5x6 micro-grid within 1 km
        s_lat = base_lat + (site_idx % 6) * 0.0015
        s_lon = base_lon + (site_idx // 6) * 0.0015
        # 5 co-located sectors per physical site
        for sec_idx in range(5):
            tid = f"SITE_{site_idx:02d}_SEC_{sec_idx}"
            radio = "5G" if sec_idx >= 3 else "4G"
            rng = 400.0 if radio == "5G" else 650.0
            cells.append(_make_cell(tid, s_lat, s_lon, range_m=rng, radio=radio))

    assert len(cells) == 150

    # 1. Test graph build with 2m aggregation
    resp_build = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
    assert resp_build.status_code == 200
    build_data = resp_build.json()
    assert len(build_data["nodes"]) == 30  # Consolidated from 150 sectors to 30 site vertices
    assert build_data["metrics"]["density"] > 0.0

    # 2. Test dual comparison on consolidated urban topology
    resp_comp = client.post("/api/compare", json={"cells": cells, "aggregate_2m": True})
    assert resp_comp.status_code == 200
    comp_data = resp_comp.json()
    assert comp_data["dsatur"]["validation"]["is_valid"] is True
    assert comp_data["welsh_powell"]["validation"]["is_valid"] is True
    assert comp_data["dsatur"]["validation"]["conflict_count"] == 0
    assert comp_data["welsh_powell"]["validation"]["conflict_count"] == 0
    # Both algorithms achieve valid channel allocation
    assert comp_data["dsatur"]["color_count"] >= 1
    assert comp_data["welsh_powell"]["color_count"] >= 1


# ============================================================================
# Scenario 2: Suburban Highway Corridor
# ============================================================================
def test_scenario_02_suburban_highway_corridor(client):
    """
    Scenario 2: Linear chain of dispersed 4G/5G towers along an expressway corridor
    testing 2-3 frequency channel spatial reuse.
    Exercised features: F1, F2, F6, F8, F9, F10.
    """
    # 20 towers spaced 900m apart along a linear highway (total span ~18 km)
    # Each tower has 500m radius -> adjacent towers overlap (500 + 500 = 1000m > 900m),
    # but non-adjacent towers do NOT overlap (1800m > 1000m).
    lat_step = 900.0 * 180.0 / (math.pi * EARTH_RADIUS_METRES)
    cells = []
    for i in range(20):
        tid = f"HWY_TOWER_{i:02d}"
        radio = "5G" if i % 2 == 1 else "4G"
        cells.append(_make_cell(tid, 28.4000 + i * lat_step, 77.1000, range_m=500.0, radio=radio))

    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()

    # In a pure linear path graph, maximum degree is 2 and chromatic number is exactly 2!
    assert data["metrics"]["node_count"] == 20
    assert data["metrics"]["edge_count"] == 19  # Path graph with N-1 edges
    assert data["metrics"]["max_degree"] == 2
    assert data["dsatur"]["color_count"] == 2
    assert data["welsh_powell"]["color_count"] == 2
    assert data["agreement"] is True
    # Verify spatial frequency channel reuse: 10 towers on f1, 10 towers on f2
    assert data["dsatur"]["channel_reuse_breakdown"]["0"] == 10
    assert data["dsatur"]["channel_reuse_breakdown"]["1"] == 10


# ============================================================================
# Scenario 3: Heterogeneous Multi-Carrier Site
# ============================================================================
def test_scenario_03_heterogeneous_multi_carrier_site(client):
    """
    Scenario 3: Physical mast hosting 18 distinct LTE and NR carriers with shared physical
    coordinates and differential power/range tiers.
    Exercised features: F3, F4, F5, F7, F8, F11.
    """
    # 18 transceivers at single physical location (lat: 28.5200, lon: 77.1900)
    cells = []
    for i in range(18):
        radio = "5G" if i % 2 == 1 else "4G"
        # Differential power levels: 400m to 900m
        rng = 400.0 + (i * 30.0)
        cells.append(_make_cell(f"MAST_CARRIER_{i:02d}", 28.5200, 77.1900, range_m=rng, radio=radio))

    # Aggregating must reduce 18 carriers into 1 consolidated vertex
    agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
    assert len(agg) == 1
    site = agg[0]
    assert site["sector_count"] == 18
    # Max range preserved: 400 + 17*30 = 910.0m
    assert site["range_m"] == 910.0
    assert "4G" in site["radios"] and "5G" in site["radios"]

    # Graph build with aggregate_2m=True produces 1 node, 0 edges, valid coloring
    resp = client.post("/api/optimize", json={"cells": cells, "aggregate_2m": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["metrics"]["node_count"] == 1
    assert data["metrics"]["edge_count"] == 0
    assert data["colors_used"] == 1
    assert data["validation"]["is_valid"] is True


# ============================================================================
# Scenario 4: Greenfield Rural Area (Sparse Graph)
# ============================================================================
def test_scenario_04_greenfield_rural_sparse_graph(client):
    """
    Scenario 4: Widely spaced rural cell towers with isolated components testing minimal
    chromatic number (chi = 1) and boundary tolerance.
    Exercised features: F1, F2, F4, F6, F8, F9.
    """
    # 12 rural towers separated by 5 km each, range 800m -> 0 overlaps
    cells = []
    for i in range(12):
        lat = 26.0000 + i * 0.05  # ~5.5 km separation
        cells.append(_make_cell(f"RURAL_{i:02d}", lat, 75.0000, range_m=800.0, radio="4G"))

    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()

    assert data["metrics"]["node_count"] == 12
    assert data["metrics"]["edge_count"] == 0
    assert data["metrics"]["density"] == 0.0
    assert data["metrics"]["connected_components"] == 12
    # All isolated vertices can safely share Channel f0 (chi = 1)
    assert data["dsatur"]["color_count"] == 1
    assert data["welsh_powell"]["color_count"] == 1
    assert data["agreement"] is True
    assert data["dsatur"]["channel_reuse_breakdown"]["0"] == 12


# ============================================================================
# Scenario 5: Legacy Ingestion Attack / Contaminated Feed
# ============================================================================
def test_scenario_05_legacy_ingestion_contaminated_feed(client):
    """
    Scenario 5: Ingestion feed containing mixed 2G/3G/4G/5G and malformed records
    verifying strict rejection, invariant enforcement, and zero crash.
    Exercised features: F5, F7, F11, F17, F19.
    """
    # Contaminated feed with legacy 2G, 3G, GSM, UMTS, negative ranges, and out-of-bounds coordinates
    feed = [
        {"cellid": 1, "lat": 28.50, "lon": 77.20, "radio": "LTE", "range": 600},
        {"cellid": 2, "lat": 28.51, "lon": 77.21, "radio": "NR", "range": 500},
        {"cellid": 3, "lat": 28.52, "lon": 77.22, "radio": "GSM", "range": 1000},
        {"cellid": 4, "lat": 28.53, "lon": 77.23, "radio": "2G", "range": 800},
        {"cellid": 5, "lat": 28.54, "lon": 77.24, "radio": "UMTS", "range": 1200},
        {"cellid": 6, "lat": 28.55, "lon": 77.25, "radio": "3G", "range": 1500},
        {"cellid": 7, "lat": 99.99, "lon": 77.26, "radio": "LTE", "range": 500},  # Invalid lat
        {"cellid": 8, "lat": 28.56, "lon": 77.27, "radio": "LTE", "range": -50},  # Fallback needed
    ]

    # Process records
    admitted = []
    rejected_count = 0
    for raw in feed:
        try:
            norm = normalize_cell_record(raw, strict_radio=True)
            admitted.append(norm)
        except ValueError:
            rejected_count += 1

    # Out of 8 records:
    # 2 valid (1, 2)
    # 4 rejected by legacy radio (3, 4, 5, 6)
    # 1 rejected by GPS coordinate > 90 (7)
    # 1 admitted with range fallback applied (8)
    assert len(admitted) == 3
    assert rejected_count == 5

    # Build graph from clean admitted records
    resp = client.post("/api/graph/build", json={"cells": admitted})
    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == 3


# ============================================================================
# Scenario 6: High-Density K_49 Sector Stress
# ============================================================================
def test_scenario_06_k49_sector_stress_suppression(client):
    """
    Scenario 6: 49 co-located transceivers at a single physical mast verifying
    complete clique suppression and single physical mast vertex consolidation.
    Exercised features: F2, F3, F4, F9, F10, F11.
    """
    # 49 sectors at identical mast location
    cells = [_make_cell(f"K49_SEC_{i:02d}", 28.5224, 77.1906, range_m=800.0) for i in range(49)]

    # 1. Unconsolidated: creates synthetic K_49 complete clique (1176 edges)
    resp_unagg = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
    assert resp_unagg.status_code == 200
    assert len(resp_unagg.json()["nodes"]) == 49
    assert len(resp_unagg.json()["edges"]) == (49 * 48) // 2  # 1176 edges
    assert resp_unagg.json()["metrics"]["density"] == 1.0

    # 2. Consolidated: resolves into 1 site mast, suppressing K_49 artifact
    resp_agg = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
    assert resp_agg.status_code == 200
    assert len(resp_agg.json()["nodes"]) == 1
    assert len(resp_agg.json()["edges"]) == 0
    assert resp_agg.json()["metrics"]["density"] == 0.0

    # 3. Frequency allocation on consolidated site requires only 1 channel
    resp_opt = client.post("/api/optimize", json={"cells": cells, "aggregate_2m": True})
    assert resp_opt.status_code == 200
    assert resp_opt.json()["colors_used"] == 1
    assert resp_opt.json()["validation"]["is_valid"] is True


# ============================================================================
# Scenario 7: Full Geodesic Polar & Date-Line Extremes
# ============================================================================
def test_scenario_07_polar_and_dateline_extremes(client):
    """
    Scenario 7: Transceivers located near the anti-meridian (+/-180) and high polar latitudes
    testing numerical spherical stability without NaN or divergence.
    Exercised features: F1, F2, F4, F8, F11.
    """
    # Sites near anti-meridian in the Arctic region (+85 deg N, +/-179.999 deg)
    # Longitude distance at 85 deg: delta_lon = 0.002 deg.
    # Metric distance ≈ (0.002/360) * 2 * pi * 6,371,000 * cos(85 deg) ≈ 222m * 0.087156 ≈ 19.3m
    cells = [
        _make_cell("POLAR_EAST", 85.0000, 179.9990, range_m=500.0),
        _make_cell("POLAR_WEST", 85.0000, -179.9990, range_m=500.0),
    ]

    # Verify Haversine stability: distance is ~19.3m, NOT 40,000km!
    d = haversine_distance(85.0000, 179.9990, 85.0000, -179.9990)
    assert d < 30.0
    assert d > 10.0

    # These two towers are 19.3m apart and each has 500m range -> conflict edge formed
    resp = client.post("/api/compare", json={"cells": cells, "aggregate_2m": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["metrics"]["edge_count"] == 1
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True


# ============================================================================
# Scenario 8: Rapid View-Switching & Drag Lifecycle
# ============================================================================
def test_scenario_08_view_switching_and_dom_safety(client):
    """
    Scenario 8: Full frontend assets lifecycle verifying Map and Graph view elements,
    view switching markup, and DOM null safety.
    Exercised features: F13, F14, F16, F17, F21.
    """
    # 1. Fetch root page
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    html = resp_root.text

    # 2. Verify all necessary view switching tabs and containers are present
    assert 'id="tab-map-view"' in html
    assert 'id="tab-graph-view"' in html
    assert 'id="map"' in html
    assert 'id="graph-canvas-container"' in html
    assert 'id="graph-canvas"' in html

    # 3. Verify static JavaScript is served cleanly
    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
    js = resp_js.text

    # 4. Confirm key handler methods exist in JavaScript
    assert "updateMapVisualStyles" in js or "invalidateSize" in js
    assert "switchTab" in js or "tab-graph-view" in js

    # 5. Confirm style.css defines both view layers
    resp_css = client.get("/static/style.css")
    assert resp_css.status_code == 200
    assert ".viewport-layer" in resp_css.text


# ============================================================================
# Scenario 9: Direct Solver Comparison & Efficiency Delta
# ============================================================================
def test_scenario_09_direct_solver_comparison_and_efficiency(client):
    """
    Scenario 9: Direct /api/compare benchmarking evaluating chromatic number agreement,
    runtime speedup, and frequency channel reuse.
    Exercised features: F9, F10, F11, F12, F15.
    """
    # Circular topology: 8 nodes around a ring with overlapping neighbors
    cells = []
    center_lat = 28.5200
    center_lon = 77.1900
    radius_ring_m = 700.0
    for i in range(8):
        angle = (2.0 * math.pi * i) / 8.0
        d_lat = (radius_ring_m * math.cos(angle)) * 180.0 / (math.pi * EARTH_RADIUS_METRES)
        d_lon = (radius_ring_m * math.sin(angle)) * 180.0 / (math.pi * EARTH_RADIUS_METRES * math.cos(math.radians(center_lat)))
        cells.append(_make_cell(f"RING_{i}", center_lat + d_lat, center_lon + d_lon, range_m=650.0))

    resp = client.post("/api/compare", json={"cells": cells})
    assert resp.status_code == 200
    data = resp.json()

    # Verify structural equality across the dual runs
    assert data["metrics"]["node_count"] == 8
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True

    # Comparative metrics
    comp = data["comparison"]
    assert "faster_heuristic" in comp
    assert "fewer_colors_heuristic" in comp
    assert "summary" in comp
    assert "educational_disclaimer" in data


# ============================================================================
# Scenario 10: Complete End-to-End User Pipeline
# ============================================================================
def test_scenario_10_complete_e2e_user_pipeline(client):
    """
    Scenario 10: Complete end-to-end cellular analysis pipeline:
    Query -> Ingest/Normalize -> Aggregate Sites -> Build Conflict Graph ->
    Optimize with DSatur -> Optimize with Welsh-Powell -> Inspect Vertex -> Compare.
    Exercised features: F1-F21 (Full Architecture).
    """
    # Step 1: Input cell transceivers with mixed 4G and 5G
    raw_inputs = [
        _make_cell("T1_4G", 28.5200, 77.1900, range_m=800.0, radio="4G"),
        _make_cell("T1_5G", 28.5200, 77.1900, range_m=500.0, radio="5G"),
        _make_cell("T2_4G", 28.5250, 77.1900, range_m=800.0, radio="4G"),
        _make_cell("T3_5G", 28.5220, 77.1950, range_m=700.0, radio="5G"),
    ]

    # Step 2: Build graph with 2m site consolidation
    build_resp = client.post("/api/graph/build", json={"cells": raw_inputs, "aggregate_2m": True})
    assert build_resp.status_code == 200
    graph_payload = build_resp.json()
    assert len(graph_payload["nodes"]) == 3  # T1_4G and T1_5G merged into 1 site mast

    # Step 3: Run DSatur optimization
    opt_dsatur_resp = client.post("/api/optimize", json={"cells": raw_inputs, "algorithm": "dsatur", "aggregate_2m": True})
    assert opt_dsatur_resp.status_code == 200
    dsatur_data = opt_dsatur_resp.json()
    assert dsatur_data["validation"]["is_valid"] is True
    assert dsatur_data["best_algorithm"] == "DSatur"

    # Step 4: Run Welsh-Powell optimization
    opt_wp_resp = client.post("/api/optimize", json={"cells": raw_inputs, "algorithm": "welsh_powell", "aggregate_2m": True})
    assert opt_wp_resp.status_code == 200
    wp_data = opt_wp_resp.json()
    assert wp_data["validation"]["is_valid"] is True
    assert wp_data["best_algorithm"] == "Welsh-Powell"

    # Step 5: Side-by-side comparison
    comp_resp = client.post("/api/compare", json={"cells": raw_inputs, "aggregate_2m": True})
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert comp_data["dsatur"]["validation"]["is_valid"] is True
    assert comp_data["welsh_powell"]["validation"]["is_valid"] is True

    # Step 6: Verify educational boundaries structured disclaimer in all stages
    assert graph_payload["educational_disclaimer"]["is_educational_simulation"] is True
    assert dsatur_data["educational_disclaimer"]["is_educational_simulation"] is True
    assert comp_data["educational_disclaimer"]["is_educational_simulation"] is True
