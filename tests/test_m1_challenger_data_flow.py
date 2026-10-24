"""
Empirical Challenger Test Suite: Milestone 1 API Data Flow, Contracts & Invalidation Stress.
Tests backend endpoints (/api/status, /api/cells, /api/graph/build, /api/optimize, /api/compare)
against frontend contract expectations, edge cases, invalidation triggers, and adversarial inputs.
"""

import pytest
from fastapi.testclient import TestClient
from app import app
from schemas import (
    CellRecord,
    CenterCoordinates,
    GraphBuildRequest,
    OptimizeRequest,
)

client = TestClient(app)


def test_status_endpoint_contract():
    """Verify GET /api/status matches frontend contract expectations."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"].lower() in ["ok", "online"]
    assert "version" in data


def test_cells_get_and_post_contract_with_frontend_params():
    """
    Verify /api/cells handles all frontend query parameters:
    lat, lon, radius_m, radios, limit, aggregate_2m
    """
    # 1. Standard query
    params = {
        "lat": 28.5224,
        "lon": 77.1906,
        "radius_m": 1500,
        "radios": "4G,5G",
        "limit": 50,
        "aggregate_2m": "true",
    }
    res = client.get("/api/cells", params=params)
    assert res.status_code == 200
    data = res.json()
    assert "cells" in data
    assert "accounting" in data
    acc = data["accounting"]
    assert "available_count" in acc
    assert "eligible_count" in acc
    assert "selected_count" in acc
    assert "excluded_count" in acc
    assert acc["selected_count"] <= 50
    assert acc["selected_count"] == len(data["cells"])
    assert acc["available_count"] >= acc["eligible_count"]
    assert acc["selected_count"] <= acc["eligible_count"]
    assert acc["excluded_count"] == acc["available_count"] - acc["selected_count"]

    # 2. Strict rejection of legacy radio parameters
    for bad_radio in ["2G", "3G", "GSM", "UMTS", "CDMA", "4G,2G", "5G,3G"]:
        bad_params = dict(params, radios=bad_radio)
        bad_res = client.get("/api/cells", params=bad_params)
        assert bad_res.status_code == 400, f"Expected 400 for legacy radio '{bad_radio}', got {bad_res.status_code}"

    # 3. Limit boundary testing
    for valid_lim in [10, 50, 100, 200]:
        lim_params = dict(params, limit=valid_lim)
        lim_res = client.get("/api/cells", params=lim_params)
        assert lim_res.status_code == 200
        assert lim_res.json()["accounting"]["selected_count"] <= valid_lim

    for invalid_lim in [0, 9, 201, 500, -1]:
        inv_params = dict(params, limit=invalid_lim)
        inv_res = client.get("/api/cells", params=inv_params)
        assert inv_res.status_code == 422, f"Expected 422 for limit '{invalid_lim}', got {inv_res.status_code}"


def test_graph_build_data_contract_and_clique_prevention():
    """
    Verify POST /api/graph/build with frontend payload format.
    Ensures 2m mast aggregation prevents artificial cliques on geographically dispersed cells.
    """
    # 5 distributed cells: 2 pairs close together and 1 far away
    cells = [
        {"tower_id": "T1", "latitude": 28.520, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": 28.525, "longitude": 77.190, "range_m": 800.0, "radio": "4G"}, # ~550m from T1 (overlap)
        {"tower_id": "T3", "latitude": 28.520, "longitude": 77.195, "range_m": 800.0, "radio": "5G"}, # ~500m from T1 (overlap)
        {"tower_id": "T4", "latitude": 28.560, "longitude": 77.190, "range_m": 800.0, "radio": "4G"}, # ~4.4km north (no overlap)
        {"tower_id": "T5", "latitude": 28.520, "longitude": 77.250, "range_m": 800.0, "radio": "5G"}, # ~5.8km east (no overlap)
    ]

    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 6000,
        "cells": cells,
        "radius_override_m": None,
        "aggregate_2m": True,
    }
    build_res = client.post("/api/graph/build", json=payload)
    assert build_res.status_code == 200
    data = build_res.json()
    assert "nodes" in data
    assert "edges" in data
    assert "metrics" in data
    metrics = data["metrics"]
    for field in ["vertex_count", "edge_count", "density", "max_degree", "avg_degree", "candidate_pairs_examined", "edges_accepted", "edges_rejected"]:
        assert field in metrics, f"Missing metric field '{field}'"
    assert metrics["vertex_count"] == 5
    # Complete clique would be 5 * 4 / 2 = 10 edges. Dispersed graph must have strictly fewer!
    assert metrics["edge_count"] < 10
    assert metrics["edges_rejected"] > 0


def test_optimize_endpoint_dual_solver_and_validation():
    """
    Verify POST /api/optimize executes both DSatur and Welsh-Powell
    and validates coloring with zero conflicts on dispersed cells.
    """
    cells = [
        {"tower_id": "T1", "latitude": 28.520, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": 28.525, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T3", "latitude": 28.520, "longitude": 77.195, "range_m": 800.0, "radio": "5G"},
        {"tower_id": "T4", "latitude": 28.560, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
    ]

    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 5000,
        "cells": cells,
        "algorithm": "both",
        "radius_override_m": None,
        "aggregate_2m": True,
    }
    opt_res = client.post("/api/optimize", json=payload)
    assert opt_res.status_code == 200
    data = opt_res.json()
    assert "dsatur" in data
    assert "welsh_powell" in data
    assert "best_algorithm" in data
    assert "metrics" in data
    assert "edges" in data

    # Check DSatur results
    ds = data["dsatur"]
    assert ds["color_count"] > 0
    assert ds["runtime_ms"] >= 0
    assert ds["validation"]["is_valid"] is True
    assert ds["validation"]["conflict_count"] == 0

    # Check Welsh-Powell results
    wp = data["welsh_powell"]
    assert wp["color_count"] > 0
    assert wp["runtime_ms"] >= 0
    assert wp["validation"]["is_valid"] is True
    assert wp["validation"]["conflict_count"] == 0

    # Verify every edge (u, v) in edges has c(u) != c(v) for DSatur
    edges = data["edges"]
    ds_coloring = ds["coloring"]
    for edge in edges:
        u = edge["source_id"]
        v = edge["target_id"]
        assert ds_coloring[u] != ds_coloring[v], f"Conflict detected on edge ({u}, {v}) in DSatur"

    # Verify every edge (u, v) in edges has c(u) != c(v) for Welsh-Powell
    wp_coloring = wp["coloring"]
    for edge in edges:
        u = edge["source_id"]
        v = edge["target_id"]
        assert wp_coloring[u] != wp_coloring[v], f"Conflict detected on edge ({u}, {v}) in Welsh-Powell"


def test_compare_endpoint_contract():
    """
    Verify POST /api/compare executes benchmark comparison
    on identical graph instance and returns side-by-side metrics.
    """
    cells = [
        {"tower_id": "T1", "latitude": 28.520, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": 28.525, "longitude": 77.190, "range_m": 800.0, "radio": "4G"},
        {"tower_id": "T3", "latitude": 28.520, "longitude": 77.195, "range_m": 800.0, "radio": "5G"},
    ]

    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 2000,
        "cells": cells,
        "radius_override_m": None,
        "aggregate_2m": True,
    }
    cmp_res = client.post("/api/compare", json=payload)
    assert cmp_res.status_code == 200
    data = cmp_res.json()
    assert "dsatur" in data
    assert "welsh_powell" in data
    assert "exact" in data
    assert "comparison" in data
    assert "metrics" in data
    assert "edges" in data

    comp = data["comparison"]
    assert "fewer_colors_heuristic" in comp
    assert comp["fewer_colors_heuristic"].lower() in ["dsatur", "welsh_powell", "welsh-powell", "tie"]
    assert "summary" in comp


def test_empty_cells_error_handling():
    """Verify backend handles empty cells list gracefully when no center is provided."""
    payload = {
        "cells": [],
        "radius_override_m": None,
        "aggregate_2m": True,
    }
    res = client.post("/api/graph/build", json=payload)
    assert res.status_code == 400


def test_invalid_payload_handling():
    """Verify backend returns 422 on malformed payloads."""
    # Missing required radius_m in optimize without center or cells
    bad_payload = {
        "cells": "invalid_not_a_list",
    }
    res = client.post("/api/optimize", json=bad_payload)
    assert res.status_code == 422
