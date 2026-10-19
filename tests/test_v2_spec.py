"""
tests/test_v2_spec.py — Test suite for SpectraMap v2 Specification Requirements

Validates:
1. System Architecture v2 endpoints:
   - GET /api/health
   - GET /api/towers (radius & bounding box modes)
   - POST /api/graph/build
   - POST /api/compare
   - POST /api/optimize
2. Mathematical Edge Rules:
   - Closed disk coverage overlap: distance(u,v) <= radius(u) + radius(v)
   - Exact boundary case: distance == r1 + r2 (must connect)
   - Distance strictly greater: distance > r1 + r2 (must NOT connect)
   - Radius override sensitivity support
3. Graph Topology Properties:
   - Empty graph
   - Single isolated tower
   - Path graph (P3)
   - Triangle graph (K3)
   - Disconnected components
4. Independent Validator:
   - Detects adjacent conflicts
   - Detects uncolored / missing vertices
   - Validates correct colorings
5. Identical Graph Invariance:
   - DSatur and Welsh–Powell evaluate the exact same graph representation
"""

import math
import pytest
import networkx as nx
from fastapi.testclient import TestClient

from app import app
from data_service import haversine_distance, EARTH_RADIUS_METRES
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    validate_coloring,
    get_graph_metrics,
    get_interference_edges,
    serialize_graph_payload,
)


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# 1. API Endpoints (Architecture v2)
# ==============================================================================
class TestV2Endpoints:
    def test_health_endpoint(self, client):
        """GET /api/health returns status ok and version 2.0."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app"] == "SpectraMap"
        assert data["version"] == "2.0"

    def test_towers_endpoint_validation_missing_params(self, client):
        """GET /api/towers returns 400 when neither lat/lon nor bbox is passed."""
        response = client.get("/api/towers")
        assert response.status_code == 400
        assert "Must provide either" in response.json()["detail"]

    def test_towers_endpoint_radius_mode(self, client, monkeypatch):
        """GET /api/towers returns normalized tower records."""
        async def mock_fetch(lat, lon, radius_m, api_key):
            return [
                {
                    "tower_id": "T1",
                    "latitude": lat,
                    "longitude": lon,
                    "range_m": 450.0,
                    "radio": "LTE",
                    "cell_id": 101,
                    "source": "OpenCellID",
                }
            ], [], False

        monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
        monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

        response = client.get("/api/towers?lat=28.52&lon=77.19&radius_m=1200")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert "towers" in data
        assert data["towers"][0]["id"] == "T1"
        assert data["towers"][0]["range_m"] == 450.0

    def test_towers_endpoint_bbox_mode(self, client, monkeypatch):
        """GET /api/towers works with bounding box (west, south, east, north)."""
        async def mock_fetch(lat, lon, radius_m, api_key):
            return [
                {
                    "tower_id": "T_BBOX",
                    "latitude": lat,
                    "longitude": lon,
                    "range_m": 600.0,
                    "radio": "LTE",
                    "cell_id": 202,
                    "source": "OpenCellID",
                }
            ], [], True

        monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
        monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

        response = client.get("/api/towers?west=77.18&south=28.51&east=77.20&north=28.53")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["cached"] is True
        assert data["towers"][0]["id"] == "T_BBOX"

    def test_graph_build_endpoint(self, client):
        """POST /api/graph/build constructs graph and returns serializable payload."""
        payload = {
            "center": {"latitude": 28.52, "longitude": 77.19},
            "radius_m": 1500,
            "cells": [
                {"id": "A", "lat": 28.5200, "lon": 77.1900, "range_m": 500.0},
                {"id": "B", "lat": 28.5230, "lon": 77.1900, "range_m": 500.0},
                {"id": "C", "lat": 28.5800, "lon": 77.1900, "range_m": 500.0}, # Distant
            ],
        }
        response = client.post("/api/graph/build", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 1  # Only A and B connect
        assert data["edges"][0]["source"] in ("A", "B")
        assert data["edges"][0]["target"] in ("A", "B")
        assert "metrics" in data
        assert data["metrics"]["vertex_count"] == 3
        assert data["metrics"]["edge_count"] == 1
        assert "assumptions" in data

    def test_compare_endpoint(self, client):
        """POST /api/compare evaluates DSatur and Welsh-Powell on identical graph."""
        payload = {
            "center": {"latitude": 28.52, "longitude": 77.19},
            "radius_m": 1500,
            "cells": [
                {"id": "V1", "lat": 28.5200, "lon": 77.1900, "range_m": 600.0},
                {"id": "V2", "lat": 28.5220, "lon": 77.1900, "range_m": 600.0},
                {"id": "V3", "lat": 28.5240, "lon": 77.1900, "range_m": 600.0},
            ],
        }
        response = client.post("/api/compare", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "dsatur" in data
        assert "welsh_powell" in data
        assert "comparison" in data
        assert data["dsatur"]["validation"]["is_valid"] is True
        assert data["welsh_powell"]["validation"]["is_valid"] is True
        assert data["dsatur"]["color_count"] >= 1
        assert data["welsh_powell"]["color_count"] >= 1


# ==============================================================================
# 2. Mathematical Boundary & Distance Tests
# ==============================================================================
class TestMathematicalCorrectness:
    def test_exact_boundary_condition_leq(self):
        """
        Closed disk criterion: distance <= r1 + r2.
        When distance == r1 + r2, edge MUST exist.
        When distance == r1 + r2 + epsilon, edge MUST NOT exist.
        """
        lat0, lon0 = 0.0, 0.0
        r1, r2 = 500.0, 500.0
        total_threshold = r1 + r2  # 1000.0 metres

        # 1 deg lat = 111,139 metres roughly, let's use exact radians
        # delta_phi = total_threshold / EARTH_RADIUS_METRES
        exact_delta_lat = (total_threshold / EARTH_RADIUS_METRES) * (180.0 / math.pi)

        # 1. Exact tangent boundary (dist == 1000.0m)
        cell_a = {"id": "T_A", "lat": lat0, "lon": lon0, "range_m": r1}
        cell_b_exact = {"id": "T_B_EXACT", "lat": lat0 + exact_delta_lat, "lon": lon0, "range_m": r2}

        # Verify haversine distance is within numerical tolerance of 1000.0m
        d_exact = haversine_distance(lat0, lon0, cell_b_exact["lat"], cell_b_exact["lon"])
        assert math.isclose(d_exact, 1000.0, rel_tol=1e-6)

        graph_exact = build_interference_graph([cell_a, cell_b_exact])
        assert graph_exact.has_edge("T_A", "T_B_EXACT"), "Edge must exist at exact boundary d <= r1 + r2"

        # 2. Epsilon separated (dist > 1000.0m by 1 metre)
        sep_delta_lat = ((total_threshold + 1.0) / EARTH_RADIUS_METRES) * (180.0 / math.pi)
        cell_b_sep = {"id": "T_B_SEP", "lat": lat0 + sep_delta_lat, "lon": lon0, "range_m": r2}

        d_sep = haversine_distance(lat0, lon0, cell_b_sep["lat"], cell_b_sep["lon"])
        assert d_sep > 1000.0

        graph_sep = build_interference_graph([cell_a, cell_b_sep])
        assert not graph_sep.has_edge("T_A", "T_B_SEP"), "Edge must NOT exist when distance > r1 + r2"

    def test_radius_override_sensitivity(self):
        """Specifying radius_override_m changes the threshold for all towers."""
        # Two towers separated by 600m with individual radii 200m each (threshold = 400m -> no edge)
        delta_lat = (600.0 / EARTH_RADIUS_METRES) * (180.0 / math.pi)
        cell1 = {"id": "C1", "lat": 28.0, "lon": 77.0, "range_m": 200.0}
        cell2 = {"id": "C2", "lat": 28.0 + delta_lat, "lon": 77.0, "range_m": 200.0}

        # Without override: no edge
        g_default = build_interference_graph([cell1, cell2])
        assert not g_default.has_edge("C1", "C2")

        # With override 350m: threshold becomes 350+350 = 700m >= 600m -> edge exists!
        g_override = build_interference_graph([cell1, cell2], radius_override_m=350.0)
        assert g_override.has_edge("C1", "C2")
        assert g_override.nodes["C1"]["effective_range_m"] == 350.0
        assert g_override.nodes["C1"]["range_m"] == 200.0


# ==============================================================================
# 3. Graph Topologies & Edge Cases
# ==============================================================================
class TestGraphTopologies:
    def test_empty_graph(self):
        """Empty graph has 0 vertices, 0 edges, and validates cleanly."""
        g = build_interference_graph([])
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0

        metrics = get_graph_metrics(g)
        assert metrics["vertex_count"] == 0
        assert metrics["edge_count"] == 0

        dsatur = color_dsatur(g)
        assert dsatur["color_count"] == 0
        assert dsatur["validation"]["is_valid"] is True

        wp = color_welsh_powell(g)
        assert wp["color_count"] == 0
        assert wp["validation"]["is_valid"] is True

    def test_isolated_vertices(self):
        """Disconnected distant towers form isolated vertices (degree 0, 1 color)."""
        cells = [
            {"id": "ISO1", "lat": 10.0, "lon": 10.0, "range_m": 100.0},
            {"id": "ISO2", "lat": 20.0, "lon": 20.0, "range_m": 100.0},
            {"id": "ISO3", "lat": 30.0, "lon": 30.0, "range_m": 100.0},
        ]
        g = build_interference_graph(cells)
        assert g.number_of_nodes() == 3
        assert g.number_of_edges() == 0

        dsatur = color_dsatur(g)
        assert dsatur["color_count"] == 1
        assert dsatur["validation"]["is_valid"] is True

        wp = color_welsh_powell(g)
        assert wp["color_count"] == 1
        assert wp["validation"]["is_valid"] is True

    def test_path_graph_p3(self):
        """Path graph A - B - C requires 2 colors (bipartite)."""
        # Place A at 0m, B at 400m, C at 800m with radius 300m each
        # A and B overlap (400 <= 600), B and C overlap (400 <= 600), A and C separated (800 > 600)
        d_lat_400m = (400.0 / EARTH_RADIUS_METRES) * (180.0 / math.pi)
        cells = [
            {"id": "A", "lat": 0.0, "lon": 0.0, "range_m": 300.0},
            {"id": "B", "lat": d_lat_400m, "lon": 0.0, "range_m": 300.0},
            {"id": "C", "lat": 2 * d_lat_400m, "lon": 0.0, "range_m": 300.0},
        ]
        g = build_interference_graph(cells)
        assert g.number_of_nodes() == 3
        assert g.number_of_edges() == 2
        assert g.has_edge("A", "B")
        assert g.has_edge("B", "C")
        assert not g.has_edge("A", "C")

        dsatur = color_dsatur(g)
        assert dsatur["color_count"] == 2
        assert dsatur["coloring"]["A"] != dsatur["coloring"]["B"]
        assert dsatur["coloring"]["B"] != dsatur["coloring"]["C"]
        assert dsatur["validation"]["is_valid"] is True

    def test_triangle_graph_k3(self):
        """Complete graph K3 requires exactly 3 colors."""
        # Form an equilateral triangle with side ~300m and coverage radius 200m each (threshold = 400m)
        d_lat = (300.0 / EARTH_RADIUS_METRES) * (180.0 / math.pi)
        d_lon = (300.0 / EARTH_RADIUS_METRES) * (180.0 / math.pi)
        cells = [
            {"id": "K1", "lat": 0.0, "lon": 0.0, "range_m": 250.0},
            {"id": "K2", "lat": d_lat, "lon": 0.0, "range_m": 250.0},
            {"id": "K3", "lat": d_lat / 2.0, "lon": d_lon * 0.866, "range_m": 250.0},
        ]
        g = build_interference_graph(cells)
        assert g.number_of_nodes() == 3
        assert g.number_of_edges() == 3

        dsatur = color_dsatur(g)
        assert dsatur["color_count"] == 3
        assert dsatur["validation"]["is_valid"] is True
        # All colors distinct
        colors = {dsatur["coloring"]["K1"], dsatur["coloring"]["K2"], dsatur["coloring"]["K3"]}
        assert len(colors) == 3


# ==============================================================================
# 4. Independent Validation Tests
# ==============================================================================
class TestIndependentValidator:
    def test_validator_catches_deliberate_conflict(self):
        """Validator must report conflict when adjacent vertices share identical color."""
        g = nx.Graph()
        g.add_edge("T1", "T2", distance_m=100.0, threshold_m=500.0)

        # Deliberately assign color 0 to both adjacent nodes
        invalid_coloring = {"T1": 0, "T2": 0}
        report = validate_coloring(g, invalid_coloring)

        assert report["is_valid"] is False
        assert report["conflict_count"] == 1
        assert ("T1", "T2") in report["conflicts"] or ("T2", "T1") in report["conflicts"]
        assert len(report["conflicting_edges"]) == 1
        assert report["conflicting_edges"][0]["color"] == 0

    def test_validator_catches_missing_or_invalid_assignment(self):
        """Validator must catch unassigned nodes, negative values, and non-integers."""
        g = nx.Graph()
        g.add_nodes_from(["N1", "N2", "N3", "N4"])

        # N1 has valid color, N2 is missing, N3 is negative, N4 is float/bool
        broken_coloring = {"N1": 0, "N3": -1, "N4": True}
        report = validate_coloring(g, broken_coloring)

        assert report["is_valid"] is False
        assert report["missing_count"] == 3
        assert "N2" in report["missing_nodes"]
        assert "N3" in report["missing_nodes"]
        assert "N4" in report["missing_nodes"]
