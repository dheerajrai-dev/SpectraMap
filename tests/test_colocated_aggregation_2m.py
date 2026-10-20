"""
Unit and API integration tests for the 2-metre tower aggregation requirement:
"if there are N number of tower within 2 metre range than treat those towers as 1 tower."
"""

import pytest
from fastapi.testclient import TestClient
from app import app
from data_service import (
    haversine_distance,
    group_cells_into_sites,
    aggregate_towers_within_distance,
)
from graph_engine import build_interference_graph, color_dsatur, color_welsh_powell, validate_coloring


@pytest.fixture
def client():
    return TestClient(app)


def test_haversine_small_distances():
    """Verify haversine distance precision on sub-5m scales."""
    # 0.00001 deg lat is ~1.11m
    d_1m = haversine_distance(28.52000, 77.19000, 28.52001, 77.19000)
    assert 1.0 < d_1m < 1.2

    # 0.00003 deg lat is ~3.33m
    d_3m = haversine_distance(28.52000, 77.19000, 28.52003, 77.19000)
    assert 3.2 < d_3m < 3.5


def test_aggregate_towers_within_2m_merges_colocated():
    """Verify N towers within 2.0m range are merged into exactly 1 tower."""
    # 3 towers at the same mast: 2 separated by 0m, 1 separated by 1.1m (all <= 2m)
    towers = [
        {"tower_id": "4G_SEC_1", "latitude": 28.520000, "longitude": 77.190000, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "4G_SEC_2", "latitude": 28.520000, "longitude": 77.190000, "range_m": 750.0, "radio": "4G"},
        {"tower_id": "5G_SEC_3", "latitude": 28.520010, "longitude": 77.190000, "range_m": 500.0, "radio": "5G"},
    ]

    aggregated = aggregate_towers_within_distance(towers, distance_threshold_m=2.0)
    assert len(aggregated) == 1, f"Expected 1 merged tower, got {len(aggregated)}"

    merged = aggregated[0]
    assert merged["sector_count"] == 3
    assert set(merged["sectors"]) == {"4G_SEC_1", "4G_SEC_2", "5G_SEC_3"}
    assert set(merged["radios"]) == {"4G", "5G"}
    assert merged["range_m"] == 800.0  # Max coverage of the site
    assert merged["radio"] == "5G"      # High-speed tier classification
    assert merged["is_co_located"] is True


def test_aggregate_towers_distinguishes_distant_sites():
    """Verify towers > 2m apart are not merged."""
    towers = [
        # Site 1 (2 sectors within 1m)
        {"tower_id": "T1_A", "latitude": 28.520000, "longitude": 77.190000, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T1_B", "latitude": 28.520005, "longitude": 77.190000, "range_m": 800.0, "radio": "4G"},
        # Site 2 (100m away)
        {"tower_id": "T2_A", "latitude": 28.520900, "longitude": 77.190000, "range_m": 800.0, "radio": "5G"},
    ]

    aggregated = aggregate_towers_within_distance(towers, distance_threshold_m=2.0)
    assert len(aggregated) == 2, f"Expected 2 distinct towers, got {len(aggregated)}"

    site1 = next(t for t in aggregated if t["sector_count"] == 2)
    site2 = next(t for t in aggregated if t["sector_count"] == 1)

    assert set(site1["sectors"]) == {"T1_A", "T1_B"}
    assert site2["sectors"] == ["T2_A"]


def test_aggregate_towers_graph_construction_no_clique():
    """
    Verify that 49 co-located towers that would form a K_49 complete clique
    become 1 vertex with 0 conflict edges when aggregate_2m is enabled.
    """
    # 49 sectors co-located within 1m of (28.52, 77.19)
    raw_cells = [
        {
            "tower_id": f"CELL_{i}",
            "latitude": 28.520000 + (0.000005 if i % 2 == 1 else 0.0),
            "longitude": 77.190000,
            "range_m": 800.0,
            "radio": "4G" if i % 2 == 0 else "5G",
        }
        for i in range(49)
    ]

    # Without aggregation: 49 vertices, 1,176 edges (K_49 clique)
    G_raw = build_interference_graph(raw_cells)
    assert G_raw.number_of_nodes() == 49
    assert G_raw.number_of_edges() == 1176

    # With 2m aggregation: exactly 1 tower vertex, 0 edges!
    merged_cells = aggregate_towers_within_distance(raw_cells, 2.0)
    assert len(merged_cells) == 1

    G_merged = build_interference_graph(merged_cells)
    assert G_merged.number_of_nodes() == 1
    assert G_merged.number_of_edges() == 0

    # Color assignment requires exactly 1 channel
    res_ds = color_dsatur(G_merged)
    assert res_ds["validation"]["is_valid"] is True
    assert res_ds["color_count"] == 1


def test_api_graph_build_aggregate_2m_param(client):
    """Verify POST /api/graph/build with aggregate_2m=true merges co-located towers."""
    # 6 co-located cells at Site A, 4 co-located cells at Site B (1000m apart)
    cells = []
    # Site A
    for i in range(6):
        cells.append({
            "tower_id": f"SITE_A_{i}",
            "latitude": 28.52000,
            "longitude": 77.19000,
            "range_m": 800.0,
            "radio": "4G",
        })
    # Site B (1000m away, overlapping coverage because 800 + 800 = 1600m > 1000m)
    for i in range(4):
        cells.append({
            "tower_id": f"SITE_B_{i}",
            "latitude": 28.52900,
            "longitude": 77.19000,
            "range_m": 800.0,
            "radio": "5G",
        })

    # Unaggregated build: 10 vertices
    res_unagg = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
    assert res_unagg.status_code == 200
    data_unagg = res_unagg.json()
    assert len(data_unagg["nodes"]) == 10

    # Aggregated build (treat towers within 2m as 1): exactly 2 vertices!
    res_agg = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
    assert res_agg.status_code == 200
    data_agg = res_agg.json()
    assert len(data_agg["nodes"]) == 2
    assert len(data_agg["edges"]) == 1  # 1 conflict edge between Site A and Site B
    assert data_agg["metrics"]["vertex_count"] == 2
    assert data_agg["metrics"]["edge_count"] == 1


def test_api_optimize_aggregate_2m_param(client):
    """Verify POST /api/optimize runs correctly on aggregated 2m towers."""
    # 3 sites in a line, each 800m apart (total 2400m), each site having 3 transceivers
    cells = []
    for site_idx, lat in enumerate([28.520, 28.527, 28.534]):
        for sec in range(3):
            cells.append({
                "tower_id": f"S{site_idx}_SEC{sec}",
                "latitude": lat,
                "longitude": 77.190,
                "range_m": 800.0,
                "radio": "4G" if sec < 2 else "5G",
            })

    res = client.post("/api/optimize", json={"cells": cells, "algorithm": "both", "aggregate_2m": True})
    assert res.status_code == 200
    data = res.json()

    assert data["metrics"]["vertex_count"] == 3
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True
    assert data["dsatur"]["color_count"] <= 3


def test_api_cells_aggregate_2m_query_param(client, monkeypatch):
    """Verify GET /api/cells?aggregate_2m=true consolidates sectors into single site towers."""
    # Mock 10 cells across 2 sites
    mock_cells = []
    for i in range(5):
        mock_cells.append({
            "tower_id": f"LTE_404_10_SITE1_{i}",
            "latitude": 28.52000,
            "longitude": 77.19000,
            "radio": "LTE",
            "range_m": 800.0,
            "is_range_estimated": False,
        })
    for i in range(5):
        mock_cells.append({
            "tower_id": f"NR_404_10_SITE2_{i}",
            "latitude": 28.52800,
            "longitude": 77.19000,
            "radio": "NR",
            "range_m": 500.0,
            "is_range_estimated": False,
        })

    async def fake_fetch(lat, lon, radius_m, api_key):
        return mock_cells, [], False

    monkeypatch.setattr("app.fetch_opencellid_records", fake_fetch)

    # Without aggregation: returns 10 towers
    r1 = client.get("/api/cells?lat=28.52&lon=77.19&radius_m=2000&aggregate_2m=false")
    assert r1.status_code == 200
    assert len(r1.json()["towers"]) == 10

    # With aggregate_2m=true: returns exactly 2 towers!
    r2 = client.get("/api/cells?lat=28.52&lon=77.19&radius_m=2000&aggregate_2m=true")
    assert r2.status_code == 200
    assert len(r2.json()["towers"]) == 2
