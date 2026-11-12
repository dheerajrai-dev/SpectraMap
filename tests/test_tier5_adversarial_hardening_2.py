"""
test_tier5_adversarial_hardening_2.py — Tier 5 Adversarial Coverage Hardening

White-box adversarial verification of the FastAPI application layer (app.py)
and frontend integration contracts (static/app.js & static/index.html):

Coverage Groups:
1. HTTP Error Resilience & Status Code Contracts (405 Method Not Allowed, 422 Unprocessable, 503 Service Unavailable)
2. Query Boundaries & Coordinate Validation on /api/towers & /api/cells (lat/lon extremes, non-numeric, clamp invariants, radio filters)
3. POST Endpoints Boundary Validation (/api/graph/build, /api/optimize, /api/compare) with extreme topologies and radio purity
4. Concurrent Solver Execution & State Isolation Stress Test (20 concurrent threads across all algorithms)
5. Frontend Integration Contracts & DOM Element Parity (response payload shapes, accounting invariants, channel reuse breakdown, DOM IDs)
"""

import concurrent.futures
import math
import re
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app import app
from schemas import (
    CellRecord,
    CompareResponse,
    GraphBuildResponse,
    OptimizeResponse,
    TowersResponse,
)


@pytest.fixture
def client():
    """Test client for SpectraMap FastAPI application."""
    return TestClient(app)


def make_cell(
    tower_id: str,
    lat: float,
    lon: float,
    radio: str = "4G",
    range_m: float = 800.0,
    cell_id: int = 1,
) -> dict[str, Any]:
    """Helper to create a normalized cell dictionary for testing."""
    return {
        "tower_id": tower_id,
        "cell_id": cell_id,
        "radio": radio,
        "latitude": lat,
        "longitude": lon,
        "lat": lat,
        "lon": lon,
        "range_m": range_m,
        "is_range_estimated": True,
        "range_source": "fallback_default",
        "site_id": f"SITE_{lat:.5f}_{lon:.5f}",
        "is_co_located": False,
    }


# ==============================================================================
# Group 1: HTTP Error Resilience & Status Code Contracts
# ==============================================================================

class TestHttpErrorResilienceAndMethodContracts:
    """Stress-test HTTP methods, invalid content types, corrupted bodies, and service availability."""

    @pytest.mark.parametrize(
        "method,endpoint",
        [
            ("post", "/api/health"),
            ("post", "/api/status"),
            ("put", "/api/towers"),
            ("delete", "/api/cells"),
            ("get", "/api/graph/build"),
            ("get", "/api/optimize"),
            ("get", "/api/compare"),
        ],
    )
    def test_unsupported_http_methods_return_405(self, client, method: str, endpoint: str):
        """Verify that unsupported HTTP verbs on API endpoints strictly return 405 Method Not Allowed."""
        http_method = getattr(client, method)
        response = http_method(endpoint)
        assert response.status_code == 405, f"Expected 405 for {method.upper()} {endpoint}, got {response.status_code}"

    @pytest.mark.parametrize("endpoint", ["/api/graph/build", "/api/optimize", "/api/compare"])
    def test_corrupted_json_syntax_returns_422(self, client, endpoint: str):
        """Verify that syntactically invalid JSON payload returns 422 Unprocessable Entity."""
        corrupted_payload = b'{"cells": [{"tower_id": "T1", "latitude": 28.5,'  # unclosed JSON
        response = client.post(
            endpoint,
            content=corrupted_payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("endpoint", ["/api/graph/build", "/api/optimize", "/api/compare"])
    def test_empty_request_body_returns_422(self, client, endpoint: str):
        """Verify that completely empty request body with application/json header returns 422."""
        response = client.post(
            endpoint,
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("endpoint", ["/api/graph/build", "/api/optimize", "/api/compare"])
    @pytest.mark.parametrize("invalid_primitive", ['"plain string"', "12345", "[1, 2, 3]"])
    def test_json_primitives_instead_of_object_returns_422(self, client, endpoint: str, invalid_primitive: str):
        """Verify that non-object JSON bodies return 422."""
        response = client.post(
            endpoint,
            content=invalid_primitive.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_missing_api_key_returns_503(self, client, monkeypatch):
        """Verify that missing OpenCellID API key returns HTTP 503 across coordinate-fetching paths."""
        monkeypatch.setattr("app._get_api_key", lambda: None)

        # GET /api/towers
        resp_towers = client.get("/api/towers?lat=28.52&lon=77.19")
        assert resp_towers.status_code == 503
        assert "API key" in resp_towers.json()["detail"]

        # GET /api/cells
        resp_cells = client.get("/api/cells?lat=28.52&lon=77.19")
        assert resp_cells.status_code == 503
        assert "API key" in resp_cells.json()["detail"]

        # POST /api/graph/build without cells, with center
        resp_build = client.post(
            "/api/graph/build",
            json={"center": {"latitude": 28.52, "longitude": 77.19}, "radius_m": 1000},
        )
        assert resp_build.status_code == 503

        # POST /api/optimize without cells, with center
        resp_opt = client.post(
            "/api/optimize",
            json={"center": {"latitude": 28.52, "longitude": 77.19}, "radius_m": 1000},
        )
        assert resp_opt.status_code == 503

        # POST /api/compare without cells, with center
        resp_comp = client.post(
            "/api/compare",
            json={"center": {"latitude": 28.52, "longitude": 77.19}, "radius_m": 1000},
        )
        assert resp_comp.status_code == 503

    def test_health_and_status_endpoints(self, client):
        """Verify health check contracts match v2 architectural specification."""
        for endpoint in ["/api/health", "/api/status"]:
            resp = client.get(endpoint)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["app"] == "SpectraMap"
            assert data["version"] == "2.0"


# ==============================================================================
# Group 2: Query Boundaries & Coordinate Validation on /api/towers & /api/cells
# ==============================================================================

class TestQueryBoundariesAndCoordinateValidation:
    """Stress-test numerical boundaries, coordinate domains, limits, and radio filtering."""

    @pytest.mark.parametrize("invalid_lat", [90.0001, -90.0001, 180.0, -999.0])
    def test_latitude_out_of_bounds_returns_422(self, client, invalid_lat: float):
        """Verify latitudes strictly outside [-90, 90] trigger HTTP 422."""
        resp = client.get(f"/api/towers?lat={invalid_lat}&lon=0.0")
        assert resp.status_code == 422

    @pytest.mark.parametrize("invalid_lon", [180.0001, -180.0001, 360.0, -500.0])
    def test_longitude_out_of_bounds_returns_422(self, client, invalid_lon: float):
        """Verify longitudes strictly outside [-180, 180] trigger HTTP 422."""
        resp = client.get(f"/api/towers?lat=0.0&lon={invalid_lon}")
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "bad_coord_param",
        [
            "lat=not_a_number&lon=77.2",
            "lat=28.5&lon=not_a_number",
            "lat=NaN&lon=77.2",
            "lat=28.5&lon=Infinity",
        ],
    )
    def test_non_numeric_coordinates_return_422(self, client, bad_coord_param: str):
        """Verify non-numeric or NaN/Inf coordinate representations return 422."""
        resp = client.get(f"/api/towers?{bad_coord_param}")
        assert resp.status_code == 422

    def test_missing_or_partial_coordinates_return_400(self, client):
        """Verify omitting coordinate sets returns HTTP 400 with actionable error detail."""
        # Neither (lat, lon) nor bounding box
        resp = client.get("/api/towers")
        assert resp.status_code == 400
        assert "Must provide either (lat, lon) or bounding box" in resp.json()["detail"]

        # Only lat provided
        resp_lat = client.get("/api/towers?lat=28.5")
        assert resp_lat.status_code == 400

        # Only lon provided
        resp_lon = client.get("/api/towers?lon=77.2")
        assert resp_lon.status_code == 400

        # Incomplete bounding box (3 of 4)
        resp_bbox = client.get("/api/towers?west=77.0&south=28.0&east=77.5")
        assert resp_bbox.status_code == 400

    @pytest.mark.parametrize("invalid_radius", [0, -1.0, -1500.0, 5000.1, 10000.0])
    def test_radius_query_boundaries_return_422(self, client, invalid_radius: float):
        """Verify radius_m must be strictly > 0 and <= 5000.0 metres."""
        resp = client.get(f"/api/towers?lat=28.5&lon=77.2&radius_m={invalid_radius}")
        assert resp.status_code == 422

    @pytest.mark.parametrize("invalid_limit", [0, 1, 9, 201, 500])
    def test_limit_query_boundaries_return_422(self, client, invalid_limit: int):
        """Verify limit must be within [10, 200] range."""
        resp = client.get(f"/api/towers?lat=28.5&lon=77.2&limit={invalid_limit}")
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "invalid_radio",
        ["2G", "3G", "GSM", "UMTS", "EDGE", "CDMA", "GPRS", "6G", "WIFI", "bluetooth"],
    )
    def test_legacy_or_invalid_radios_return_400(self, client, invalid_radio: str):
        """Verify requesting legacy or non-cellular radio technologies returns HTTP 400."""
        resp = client.get(f"/api/towers?lat=28.5&lon=77.2&radios={invalid_radio}")
        assert resp.status_code == 400
        assert "Invalid radio technology" in resp.json()["detail"] or "Allowed values: 4G, 5G" in resp.json()["detail"]

    def test_mixed_legacy_and_valid_radios_strictly_rejected(self, client):
        """Verify that combining valid with legacy radios (e.g. 4G,2G) is strictly rejected with 400."""
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G,2G")
        assert resp.status_code == 400

    def test_empty_radios_query_returns_400(self, client):
        """Verify empty radio string returns 400."""
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=")
        assert resp.status_code == 400

    def test_bounding_box_adversarial_geometry(self, client, monkeypatch):
        """Verify bounding box calculation handles inverted or degenerate coordinates without crashing."""
        async def mock_fetch(lat, lon, r, key):
            return [], [], False

        monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
        monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

        # Inverted latitudes (south > north): Haversine distance still computes and radius is clamped
        resp = client.get("/api/towers?west=77.0&south=29.0&east=77.5&north=28.0")
        assert resp.status_code == 200
        data = resp.json()
        assert 500.0 <= data["radius_m"] <= 5000.0

        # Degenerate point (south == north, west == east): half diagonal is 0, clamped to min 500.0
        resp_pt = client.get("/api/towers?west=77.2&south=28.5&east=77.2&north=28.5")
        assert resp_pt.status_code == 200
        assert resp_pt.json()["radius_m"] == 500.0


# ==============================================================================
# Group 3: POST Endpoints Boundary Validation & Extreme Graph Topologies
# ==============================================================================

class TestPostEndpointsBoundaryAndGeometryValidation:
    """Stress-test /api/graph/build, /api/optimize, and /api/compare under extreme topologies."""

    def test_zero_cells_and_no_center_returns_error(self, client):
        """Verify submitting empty cells and no center returns appropriate client error status codes."""
        # /api/graph/build -> 400
        resp_build = client.post("/api/graph/build", json={"cells": []})
        assert resp_build.status_code == 400

        # /api/optimize -> 422 (Pydantic model validator requires center if cells empty)
        resp_opt = client.post("/api/optimize", json={"cells": []})
        assert resp_opt.status_code == 422

        # /api/compare -> 422
        resp_comp = client.post("/api/compare", json={"cells": []})
        assert resp_comp.status_code == 422

    def test_tower_ids_filtering_to_zero_cells_returns_400(self, client):
        """Verify filtering by non-matching tower_ids returns HTTP 400 with zero valid records."""
        cell = make_cell("4G_1", 28.52, 77.19)
        resp = client.post(
            "/api/graph/build",
            json={"cells": [cell], "tower_ids": ["NON_EXISTENT_ID"]},
        )
        assert resp.status_code == 400
        assert "Zero valid tower records" in resp.json()["detail"]

    @pytest.mark.parametrize("legacy_radio", ["2G", "GSM", "3G", "UMTS"])
    def test_legacy_radio_injection_in_payload_rejected_by_pydantic(self, client, legacy_radio: str):
        """Verify submitting cell records with legacy radio technologies is rejected with HTTP 422."""
        payload = {
            "cells": [
                {
                    "tower_id": "BAD_RADIO_1",
                    "latitude": 28.52,
                    "longitude": 77.19,
                    "radio": legacy_radio,
                }
            ]
        }
        resp = client.post("/api/graph/build", json=payload)
        assert resp.status_code == 422
        assert "Only '4G' and '5G' are supported" in str(resp.json())

    @pytest.mark.parametrize("invalid_override", [0, -100.0, 20000.1])
    def test_radius_override_boundaries(self, client, invalid_override: float):
        """Verify radius_override_m boundaries (> 0 and <= 20000.0)."""
        cell = make_cell("4G_1", 28.52, 77.19)
        resp = client.post(
            "/api/graph/build",
            json={"cells": [cell], "radius_override_m": invalid_override},
        )
        assert resp.status_code == 422

    def test_single_cell_isolated_graph_behavior(self, client):
        """Verify single isolated vertex is colored with 1 color and passes 100% edge validation."""
        cell = make_cell("4G_ISOLATED", 28.52, 77.19)
        
        # 1. /api/graph/build
        resp_build = client.post("/api/graph/build", json={"cells": [cell]})
        assert resp_build.status_code == 200
        data_build = resp_build.json()
        assert len(data_build["nodes"]) == 1
        assert len(data_build["edges"]) == 0
        assert data_build["metrics"]["density"] == 0.0
        assert data_build["metrics"]["max_degree"] == 0

        # 2. /api/optimize
        for algo in ["dsatur", "welsh_powell", "exact", "both"]:
            resp_opt = client.post(
                "/api/optimize",
                json={"cells": [cell], "algorithm": algo},
            )
            assert resp_opt.status_code == 200
            data_opt = resp_opt.json()
            assert data_opt["colors_used"] == 1
            assert data_opt["assignments"]["4G_ISOLATED"] == 0
            assert data_opt["validation"]["is_valid"] is True
            assert data_opt["validation"]["conflict_count"] == 0

        # 3. /api/compare
        resp_comp = client.post("/api/compare", json={"cells": [cell]})
        assert resp_comp.status_code == 200
        data_comp = resp_comp.json()
        assert data_comp["dsatur"]["color_count"] == 1
        assert data_comp["welsh_powell"]["color_count"] == 1
        assert data_comp["exact"]["color_count"] == 1
        assert data_comp["agreement"] is True

    def test_disconnected_subgraphs_multi_component(self, client):
        """Verify two cells separated by 50km form a disconnected graph with 0 edges and 1 color."""
        # Delhi and Jaipur (~240 km apart)
        cell1 = make_cell("4G_DELHI", 28.6139, 77.2090, range_m=1000.0)
        cell2 = make_cell("4G_JAIPUR", 26.9124, 75.7873, range_m=1000.0)

        resp_opt = client.post(
            "/api/optimize",
            json={"cells": [cell1, cell2], "algorithm": "both"},
        )
        assert resp_opt.status_code == 200
        data = resp_opt.json()
        assert data["metrics"]["edge_count"] == 0
        assert data["colors_used"] == 1
        # Both can reuse the same channel (color 0) safely
        assert data["assignments"]["4G_DELHI"] == 0
        assert data["assignments"]["4G_JAIPUR"] == 0
        assert data["validation"]["is_valid"] is True

    def test_complete_clique_and_aggregation_resolution(self, client):
        """
        Verify that 4 co-located transceivers at identical coordinates:
        - without aggregation: form a complete clique K_4 requiring 4 colors.
        - with aggregate_2m: True: consolidate into 1 mast vertex requiring 1 color.
        """
        co_located_cells = [
            make_cell(f"4G_SECTOR_{i}", 28.52000, 77.19000, range_m=800.0, cell_id=i)
            for i in range(1, 5)
        ]

        # Case A: Without aggregation -> K_4 complete clique
        resp_no_agg = client.post(
            "/api/optimize",
            json={"cells": co_located_cells, "aggregate_2m": False},
        )
        assert resp_no_agg.status_code == 200
        data_no_agg = resp_no_agg.json()
        assert data_no_agg["metrics"]["node_count"] == 4
        assert data_no_agg["metrics"]["edge_count"] == 6  # 4 * 3 / 2
        assert data_no_agg["metrics"]["density"] == 1.0
        assert data_no_agg["colors_used"] == 4
        assert data_no_agg["validation"]["is_valid"] is True

        # Case B: With aggregation -> 1 consolidated mast
        resp_agg = client.post(
            "/api/optimize",
            json={"cells": co_located_cells, "aggregate_2m": True},
        )
        assert resp_agg.status_code == 200
        data_agg = resp_agg.json()
        assert data_agg["metrics"]["node_count"] == 1
        assert data_agg["metrics"]["edge_count"] == 0
        assert data_agg["colors_used"] == 1

    def test_star_topology_bipartite_coloring(self, client):
        """
        Verify star topology (1 central hub overlapping 6 peripheral spokes).
        Peripheral spokes are spaced such that they don't overlap each other.
        Bipartite graph: chromatic number must be exactly 2.
        """
        hub = make_cell("HUB", 28.52000, 77.19000, range_m=600.0)
        spokes = []
        # Radius = 600m; place spokes at distance ~500m (angle = 60 deg apart)
        # Distance between adjacent spokes at 500m radius and 60 deg angle is 500m.
        # Spoke range = 200m -> spoke-to-spoke threshold = 400m < 500m separation (no spoke-spoke edge).
        # Hub range (600m) + spoke range (200m) = 800m > 500m separation (hub-spoke edge exists).
        angles_deg = [0, 60, 120, 180, 240, 300]
        r_deg = 500.0 / 111320.0  # approximate metres to degrees
        for idx, ang in enumerate(angles_deg):
            rad = math.radians(ang)
            lat = 28.52000 + r_deg * math.cos(rad)
            lon = 77.19000 + (r_deg * math.sin(rad)) / math.cos(math.radians(28.52000))
            spokes.append(make_cell(f"SPOKE_{idx}", lat, lon, range_m=200.0, cell_id=idx + 10))

        all_nodes = [hub] + spokes
        resp = client.post("/api/optimize", json={"cells": all_nodes, "algorithm": "both"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["node_count"] == 7
        assert data["metrics"]["edge_count"] == 6  # strictly 6 edges incident to HUB
        assert data["metrics"]["max_degree"] == 6
        assert data["colors_used"] == 2
        # Verify hub has a different color from all spokes, and all spokes share the other color
        hub_color = data["assignments"]["HUB"]
        spoke_colors = [data["assignments"][f"SPOKE_{i}"] for i in range(6)]
        assert all(c != hub_color for c in spoke_colors)
        assert data["validation"]["is_valid"] is True

    def test_exact_solver_size_limit_cutoff(self, client):
        """Verify exact solver is executed for N <= 25 and cleanly skipped for N > 25."""
        # 1. N = 5 (within limit)
        cells_small = [
            make_cell(f"4G_NODE_{i}", 28.52 + i * 0.002, 77.19, range_m=500.0, cell_id=i)
            for i in range(5)
        ]
        resp_small = client.post(
            "/api/optimize",
            json={"cells": cells_small, "algorithm": "exact"},
        )
        assert resp_small.status_code == 200
        assert resp_small.json()["exact"]["proven_optimal"] is True

        # 2. N = 26 (exceeds limit N <= 25)
        cells_large = [
            make_cell(f"4G_NODE_{i}", 28.52 + i * 0.002, 77.19, range_m=500.0, cell_id=i)
            for i in range(26)
        ]
        resp_large = client.post(
            "/api/optimize",
            json={"cells": cells_large, "algorithm": "exact"},
        )
        assert resp_large.status_code == 200
        exact_res = resp_large.json()["exact"]
        assert exact_res["status"] == "skipped_size_limit"
        assert exact_res["proven_optimal"] is False


# ==============================================================================
# Group 4: Concurrent Solver Execution & State Isolation Stress Test
# ==============================================================================

class TestConcurrentExecutionAndStateIsolation:
    """Stress-test concurrent solver executions to verify thread-safety and state isolation."""

    def test_concurrent_multi_solver_requests(self, client):
        """
        Execute 20 concurrent requests across /api/optimize and /api/compare with different algorithms.
        Assert that all 20 succeed with HTTP 200, valid colorings, and zero cross-request pollution.
        """
        def send_request(request_idx: int) -> dict[str, Any]:
            # Generate distinct cellular topology per request
            base_lat = 28.50 + request_idx * 0.01
            base_lon = 77.15 + request_idx * 0.01
            node_count = 8 + (request_idx % 6)
            cells = [
                make_cell(
                    f"REQ_{request_idx}_CELL_{i}",
                    base_lat + (i * 0.001),
                    base_lon + (i * 0.001),
                    radio="4G" if i % 2 == 0 else "5G",
                    range_m=700.0,
                    cell_id=i + 1,
                )
                for i in range(node_count)
            ]

            endpoint = "/api/compare" if (request_idx % 2 == 0) else "/api/optimize"
            algo = ["dsatur", "welsh_powell", "both"][request_idx % 3]
            payload = {
                "cells": cells,
                "algorithm": algo,
                "aggregate_2m": False,
            }
            res = client.post(endpoint, json=payload)
            return {
                "req_idx": request_idx,
                "status_code": res.status_code,
                "endpoint": endpoint,
                "data": res.json(),
                "node_count": node_count,
            }

        concurrency = 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(send_request, i) for i in range(concurrency)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == concurrency
        for r in results:
            assert r["status_code"] == 200, f"Request {r['req_idx']} failed: {r}"
            data = r["data"]
            # Check validation
            if r["endpoint"] == "/api/optimize":
                assert data["validation"]["is_valid"] is True
                assert data["validation"]["conflict_count"] == 0
                assert data["metrics"]["node_count"] == r["node_count"]
                # Verify that assignments only contain IDs matching this request's prefix
                expected_prefix = f"REQ_{r['req_idx']}_"
                assert all(k.startswith(expected_prefix) for k in data["assignments"].keys())
            else:
                assert data["dsatur"]["validation"]["is_valid"] is True
                assert data["welsh_powell"]["validation"]["is_valid"] is True
                assert data["metrics"]["node_count"] == r["node_count"]

    def test_concurrent_exact_solver_stress(self, client):
        """Execute 8 parallel requests invoking the exact B&B solver on dense subgraphs."""
        def send_exact_request(idx: int) -> int:
            cells = [
                make_cell(
                    f"EXACT_{idx}_C_{i}",
                    28.520 + (i * 0.0005),
                    77.190 + (i * 0.0005),
                    range_m=800.0,
                    cell_id=i,
                )
                for i in range(12)
            ]
            resp = client.post("/api/optimize", json={"cells": cells, "algorithm": "exact"})
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(send_exact_request, i) for i in range(8)]
            statuses = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert all(s == 200 for s in statuses)


# ==============================================================================
# Group 5: Frontend Integration Contracts & DOM Element Parity
# ==============================================================================

class TestFrontendIntegrationContracts:
    """Verify backend JSON response schemas conform strictly to frontend static/app.js contracts."""

    def test_cells_response_schema_matches_frontend_contract(self, client, monkeypatch):
        """Verify /api/cells returns all fields consumed in app.js fetchCells()."""
        raw_mock = [
            make_cell("4G_1", 28.52, 77.19, "4G", 800.0, 1),
            make_cell("5G_2", 28.53, 77.20, "5G", 500.0, 2),
        ]
        async def mock_fetch(lat, lon, r, key):
            return raw_mock, [], False

        monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
        monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

        resp = client.get("/api/cells?lat=28.52&lon=77.19&radius_m=1500&radios=4G,5G&limit=50")
        assert resp.status_code == 200
        data = resp.json()

        # Contract fields accessed in static/app.js lines 1519-1545:
        assert "cells" in data
        assert "accounting" in data
        assert "sites" in data
        assert "tech_distribution" in data
        assert "center" in data
        assert "radius_m" in data
        assert "warnings" in data
        assert "cached" in data

        # Accounting fields accessed in updateAccountingDisplay()
        acc = data["accounting"]
        for k in ["available_count", "eligible_count", "selected_count", "excluded_count"]:
            assert k in acc
            assert isinstance(acc[k], int)

    def test_compare_response_schema_matches_frontend_contract(self, client):
        """Verify /api/compare matches all fields accessed in runComparisonDirectly()."""
        cells = [
            make_cell("4G_1", 28.520, 77.190, range_m=600.0),
            make_cell("4G_2", 28.523, 77.193, range_m=600.0),
        ]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()

        # Contract fields accessed in static/app.js lines 2493-2509:
        assert "metrics" in data
        assert "dsatur" in data
        assert "welsh_powell" in data
        assert "exact" in data
        assert "comparison" in data
        assert "edges" in data
        assert "educational_disclaimer" in data

        comp = data["comparison"]
        assert "colors_difference" in comp
        assert "faster_heuristic" in comp
        assert "fewer_colors_heuristic" in comp
        assert "summary" in comp

        # Channel reuse breakdown accessed in renderCompareModalContent()
        assert "channel_reuse_breakdown" in data["dsatur"]
        assert "channel_reuse_breakdown" in data["welsh_powell"]

    def test_educational_disclaimer_structured_object_contract(self, client):
        """Verify educational_disclaimer adheres to schema across all POST endpoints."""
        cells = [make_cell("4G_1", 28.52, 77.19)]
        for endpoint, payload in [
            ("/api/graph/build", {"cells": cells}),
            ("/api/optimize", {"cells": cells}),
            ("/api/compare", {"cells": cells}),
        ]:
            resp = client.post(endpoint, json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert "educational_disclaimer" in data
            disc = data["educational_disclaimer"]
            assert disc["is_educational_simulation"] is True
            assert "propagation_model" in disc
            assert "disclaimer" in disc
            assert "recommended_use" in disc

    def test_frontend_dom_ids_integrity(self):
        """
        Verify that all active UI element IDs accessed in static/app.js
        exist in static/index.html to guarantee seamless frontend DOM binding.
        """
        html_path = Path("static/index.html")
        assert html_path.exists(), "static/index.html must exist"
        html_content = html_path.read_text(encoding="utf-8")

        # Active UI element IDs queried and bound by static/app.js (Prompt 6 excised canvas and decorative badges)
        critical_element_ids = [
            "map",
            "status-badge",
            "preset-select",
            "input-lat",
            "input-lon",
            "radius-slider",
            "radius-label",
            "map-overlay",
            "control-dock",
            "limit-slider",
            "limit-label",
            "acc-avail",
            "acc-elig",
            "acc-sel",
            "acc-excl",
            "range-min",
            "range-med",
            "range-max",
            "override-slider",
            "btn-fetch",
            "btn-build-graph",
            "btn-optimize",
            "btn-compare-action",
            "cells-status",
            "vertex-inspector",
            "inspector-cell-id",
            "btn-close-inspector",
            "compare-modal",
            "compare-modal-body",
            "metric-towers",
            "metric-edges",
            "metric-degree",
            "metric-density",
            "btn-locate",
            "btn-demo",
            "btn-guide",
        ]

        missing_ids = []
        for elem_id in critical_element_ids:
            # Match id="elem_id" or id='elem_id'
            pattern = rf'id=["\']{re.escape(elem_id)}["\']'
            if not re.search(pattern, html_content):
                missing_ids.append(elem_id)

        assert not missing_ids, f"Critical DOM element IDs missing from static/index.html: {missing_ids}"

    def test_frontend_null_safety_guards_in_app_js(self):
        """
        Verify that static/app.js strictly guards DOM element lookups with null checks
        (e.g. if (el) or optional chaining ?.) so that any absent element never throws unhandled errors.
        """
        app_js_path = Path("static/app.js")
        assert app_js_path.exists(), "static/app.js must exist"
        app_js_content = app_js_path.read_text(encoding="utf-8")

        # 1. setElemText and setElemHtml helper guards
        assert "function setElemText(id, text) {\n    const el = document.getElementById(id);\n    if (el) el.textContent = text;\n}" in app_js_content
        assert "function setElemHtml(id, html) {\n    const el = document.getElementById(id);\n    if (el) el.innerHTML = html;\n}" in app_js_content

        # 2. Verify legacy pill references in app.js use optional chaining ?.
        assert "document.getElementById(id)?.classList.remove" in app_js_content
        assert "[pillDsatur, pillWp, pillExact].forEach((p) => p?.classList.remove" in app_js_content

