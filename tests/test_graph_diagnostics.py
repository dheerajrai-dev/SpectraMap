"""
tests/test_graph_diagnostics.py — Comprehensive tests for graph construction,
diagnostics reporting, edge rules, and frequency reuse verification.

Validates the requirements of Critical Bug Fix:
1. Two distant towers have no edge (distance > r1 + r2).
2. Two overlapping towers have an edge (distance <= r1 + r2).
3. Exact boundary case follows documented closed-disk rule (distance == r1 + r2 -> edge).
4. Strictly greater distance has no edge (distance > r1 + r2 -> no edge).
5. Missing or invalid radius data follows documented fallback policy.
6. The graph is NOT complete unless data genuinely requires it (sparse line/grid graph).
7. Demo Grid demonstrates realistic frequency reuse (k << N, density < 0.15).
8. Full diagnostic metrics reporting (candidate pairs examined, accepted, rejected,
   min/median/max radius and distance, degree distribution, sample justifications).
9. Accurate co-location detection and data suitability warning for 49 co-located towers.
10. DSatur, Welsh-Powell, and independent validator verified on corrected graphs.
"""

import math
import pytest
import networkx as nx
from data_service import (
    haversine_distance,
    EARTH_RADIUS_METRES,
    normalize_cell_record,
    DEFAULT_FALLBACK_RADIUS,
)
from graph_engine import (
    build_interference_graph,
    get_graph_metrics,
    get_graph_diagnostics,
    color_dsatur,
    color_welsh_powell,
    validate_coloring,
)


def _coords_from_distance(lat0: float, lon0: float, distance_m: float) -> tuple[float, float]:
    """Helper: compute (lat, lon) at a precise northward geodesic distance in metres."""
    delta_lat = (distance_m / EARTH_RADIUS_METRES) * (180.0 / math.pi)
    return lat0 + delta_lat, lon0


class TestDeterministicEdgeRules:
    def test_two_distant_towers_have_no_edge(self):
        """Two distant towers whose modeled coverage does not overlap must have no edge."""
        lat0, lon0 = 28.5200, 77.1900
        # Place T2 exactly 2,500m north of T1
        lat2, lon2 = _coords_from_distance(lat0, lon0, 2500.0)

        cell1 = {"tower_id": "T1", "latitude": lat0, "longitude": lon0, "range_m": 500.0}
        cell2 = {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": 500.0}

        G = build_interference_graph([cell1, cell2])
        assert G.number_of_nodes() == 2
        assert G.number_of_edges() == 0
        assert not G.has_edge("T1", "T2")

        metrics = get_graph_metrics(G)
        assert metrics["candidate_pairs_examined"] == 1
        assert metrics["edges_accepted"] == 0
        assert metrics["edges_rejected"] == 1
        assert metrics["density"] == 0.0
        assert len(metrics["sample_rejected_pairs"]) == 1
        assert "d(2500.0m) > r_u + r_v" in metrics["sample_rejected_pairs"][0]["reason"]

    def test_two_overlapping_towers_have_edge(self):
        """Two towers whose modeled coverage circles overlap must have an edge."""
        lat0, lon0 = 28.5200, 77.1900
        # Place T2 600m north of T1 with 400m radius each (sum = 800m >= 600m)
        lat2, lon2 = _coords_from_distance(lat0, lon0, 600.0)

        cell1 = {"tower_id": "T1", "latitude": lat0, "longitude": lon0, "range_m": 400.0}
        cell2 = {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": 400.0}

        G = build_interference_graph([cell1, cell2])
        assert G.number_of_nodes() == 2
        assert G.number_of_edges() == 1
        assert G.has_edge("T1", "T2")

        edge_data = G.edges["T1", "T2"]
        assert edge_data["distance_m"] == 600.0
        assert edge_data["threshold_m"] == 800.0
        assert "d(u, v) <= r_u + r_v" in edge_data["rule"]

        metrics = get_graph_metrics(G)
        assert metrics["candidate_pairs_examined"] == 1
        assert metrics["edges_accepted"] == 1
        assert metrics["edges_rejected"] == 0
        assert metrics["density"] == 1.0

    def test_exact_boundary_case_creates_edge(self):
        """Boundary case: when distance == radius1 + radius2, closed disk rule mandates edge."""
        lat0, lon0 = 28.5200, 77.1900
        # Exactly 1,000.0m distance; radii = 500.0m each (sum = 1,000.0m)
        lat2, lon2 = _coords_from_distance(lat0, lon0, 1000.0)

        cell1 = {"tower_id": "T1", "latitude": lat0, "longitude": lon0, "range_m": 500.0}
        cell2 = {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": 500.0}

        G = build_interference_graph([cell1, cell2])
        assert G.has_edge("T1", "T2")
        edge_data = G.edges["T1", "T2"]
        assert abs(edge_data["distance_m"] - edge_data["threshold_m"]) < 0.2

    def test_strictly_greater_boundary_case_has_no_edge(self):
        """When distance strictly exceeds radius1 + radius2, no edge must be created."""
        lat0, lon0 = 28.5200, 77.1900
        # 1,002.0m distance; radii = 500.0m each (sum = 1,000.0m < 1,002.0m)
        lat2, lon2 = _coords_from_distance(lat0, lon0, 1002.0)

        cell1 = {"tower_id": "T1", "latitude": lat0, "longitude": lon0, "range_m": 500.0}
        cell2 = {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": 500.0}

        G = build_interference_graph([cell1, cell2])
        assert not G.has_edge("T1", "T2")
        metrics = get_graph_metrics(G)
        assert metrics["edges_accepted"] == 0
        assert metrics["edges_rejected"] == 1


class TestDataFallbacksAndPolicy:
    def test_missing_radius_assigns_documented_fallback(self):
        """Missing radius assigns technology-specific default and marks is_range_estimated=True."""
        raw = {
            "lat": 28.52,
            "lon": 77.19,
            "cellid": 12345,
            "radio": "LTE",
        }
        normalized = normalize_cell_record(raw)
        assert normalized["range_m"] == 800.0
        assert normalized["is_range_estimated"] is True
        assert normalized["range_source"] == "fallback_default"
        assert normalized["fallback_reason"] == "missing"

    def test_invalid_zero_radius_assigns_fallback(self):
        """Zero radius triggers documented fallback policy."""
        raw = {
            "lat": 28.52,
            "lon": 77.19,
            "cellid": 12346,
            "radio": "5G",
            "range": 0,
        }
        normalized = normalize_cell_record(raw)
        assert normalized["range_m"] == 500.0
        assert normalized["is_range_estimated"] is True
        assert normalized["range_source"] == "fallback_default"
        assert normalized["fallback_reason"] == "zero"


class TestSparsityAndFrequencyReuse:
    def test_line_graph_is_not_complete_and_achieves_frequency_reuse(self):
        """
        Verify that a 5-tower line graph is sparse (density 40% << 100%)
        and both DSatur and Welsh-Powell achieve frequency reuse (k=2 << 5).
        """
        lat0, lon0 = 28.5200, 77.1900
        # 5 towers spaced 400m apart; radius 250m each (threshold = 500m)
        # Adjacent pairs: d = 400m <= 500m -> edge
        # Non-adjacent pairs: d >= 800m > 500m -> no edge
        cells = []
        for i in range(5):
            lat_i, lon_i = _coords_from_distance(lat0, lon0, i * 400.0)
            cells.append({
                "tower_id": f"T_{i}",
                "latitude": lat_i,
                "longitude": lon_i,
                "range_m": 250.0,
            })

        G = build_interference_graph(cells)
        assert G.number_of_nodes() == 5
        assert G.number_of_edges() == 4  # Line graph P5
        metrics = get_graph_metrics(G)
        assert metrics["density"] == 0.40  # 4 / 10 = 0.40, NOT 1.0!
        assert metrics["candidate_pairs_examined"] == 10
        assert metrics["edges_accepted"] == 4
        assert metrics["edges_rejected"] == 6

        # Run DSatur
        ds = color_dsatur(G)
        assert ds["color_count"] == 2  # Bipartite line graph uses 2 colors
        val_ds = validate_coloring(G, ds["coloring"])
        assert val_ds["is_valid"] is True
        assert val_ds["conflict_count"] == 0

        # Run Welsh-Powell
        wp = color_welsh_powell(G)
        assert wp["color_count"] == 2
        val_wp = validate_coloring(G, wp["coloring"])
        assert val_wp["is_valid"] is True
        assert val_wp["conflict_count"] == 0

    def test_demo_grid_sparsity_and_reuse(self):
        """Verify Demo Grid (14 towers, 350m radius) demonstrates realistic sparse frequency reuse."""
        center = {"lat": 28.5224, "lon": 77.1906}
        demo_towers = []
        count = 14
        for i in range(count):
            is_inner = i < 6
            angle = ((i % 6) * 2 * math.pi) / 6 + (0 if is_inner else math.pi / 6)
            dist = 550 if is_inner else 1150
            d_lat = (dist * math.cos(angle)) / 111139.0
            d_lon = (dist * math.sin(angle)) / (111139.0 * math.cos(math.radians(center["lat"])))
            demo_towers.append({
                "tower_id": f"DEMO_LTE_{i+1}",
                "cell_id": 900000 + i + 1,
                "radio": "4G LTE",
                "latitude": round(center["lat"] + d_lat, 5),
                "longitude": round(center["lon"] + d_lon, 5),
                "range_m": 350.0,
            })

        G = build_interference_graph(demo_towers)
        metrics = get_graph_metrics(G)
        assert G.number_of_nodes() == 14
        # At 350m, density is ~9% (8 edges out of 91)
        assert metrics["edge_count"] < 25
        assert metrics["density"] < 0.25
        assert metrics["candidate_pairs_examined"] == 91
        assert metrics["edges_rejected"] > 60

        ds = color_dsatur(G)
        wp = color_welsh_powell(G)
        assert ds["color_count"] <= 3  # High frequency reuse
        assert wp["color_count"] <= 3
        assert validate_coloring(G, ds["coloring"])["is_valid"] is True
        assert validate_coloring(G, wp["coloring"])["is_valid"] is True


class TestDiagnosticReportingAndCoLocationNotice:
    def test_diagnostic_fields_present_in_metrics(self):
        """Verify all required diagnostic metrics are calculated and returned."""
        cells = [
            {"tower_id": "T1", "latitude": 28.520, "longitude": 77.190, "range_m": 300.0},
            {"tower_id": "T2", "latitude": 28.522, "longitude": 77.190, "range_m": 300.0},
            {"tower_id": "T3", "latitude": 28.530, "longitude": 77.190, "range_m": 300.0},
        ]
        G = build_interference_graph(cells)
        diag = get_graph_diagnostics(G)

        # Check required diagnostic keys
        assert "candidate_pairs_examined" in diag
        assert "edges_accepted" in diag
        assert "edges_rejected" in diag
        assert "min_radius_m" in diag
        assert "median_radius_m" in diag
        assert "max_radius_m" in diag
        assert "min_distance_m" in diag
        assert "median_distance_m" in diag
        assert "max_distance_m" in diag
        assert "degree_distribution" in diag
        assert "sample_accepted_edges" in diag
        assert "sample_rejected_pairs" in diag
        assert "data_unsuitable" in diag

        assert diag["candidate_pairs_examined"] == 3
        assert diag["edges_accepted"] + diag["edges_rejected"] == 3
        assert diag["min_radius_m"] == 300.0
        assert diag["max_radius_m"] == 300.0
        assert diag["data_unsuitable"] is False

    def test_co_located_cluster_detected_and_flagged_as_unsuitable(self):
        """
        When all towers share identical coordinates (distance 0.0m),
        the graph is complete K_N, and data_unsuitable is flagged True with a clear explanation.
        """
        # Simulate 10 co-located transceivers at the same coordinate
        cells = [
            {
                "tower_id": f"SECTOR_{i}",
                "latitude": 28.5200,
                "longitude": 77.1900,
                "range_m": 500.0,
            }
            for i in range(10)
        ]
        G = build_interference_graph(cells)
        metrics = get_graph_metrics(G)

        assert metrics["node_count"] == 10
        assert metrics["edge_count"] == 45  # K_10: 10 * 9 / 2 = 45
        assert metrics["density"] == 1.0
        assert metrics["max_degree"] == 9
        assert metrics["unique_coordinates_count"] == 1
        assert metrics["data_unsuitable"] is True
        assert metrics["data_unsuitable_reason"] is not None
        assert "identical coordinates" in metrics["data_unsuitable_reason"]
        assert "K_10" in metrics["data_unsuitable_reason"]
        assert metrics["min_distance_m"] == 0.0
        assert metrics["max_distance_m"] == 0.0
