"""
tests/test_milestone1_adversarial_challenge.py

Adversarial Verification Suite for Milestone 1 Graph Engine & Mathematical Core.
Authored by: teamwork_preview_challenger_m1_1

Covers:
1. Haversine numerical stability (1µm separation, zero separation, polar boundaries, antipodal points).
2. Conflict edge formation boundary conditions (d <= r_u + r_v ± 10^-6m).
3. Co-located mast consolidation & K_49 clique elimination.
4. Independent validator robustness against 100% of color conflicts, zero-distance edges,
   boundary violations, and malformed color assignments.
"""

import math
import random
import networkx as nx
import pytest

from data_service import (
    EARTH_RADIUS_METRES,
    haversine_distance,
    aggregate_towers_within_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    get_graph_metrics,
    validate_coloring,
)

DEG_PER_M = 1.0 / (EARTH_RADIUS_METRES * (math.pi / 180.0))


class TestHaversineNumericalStability:
    """Empirical challenge of spherical Haversine precision and numerical boundaries."""

    def test_haversine_exact_zero_separation(self):
        """Zero separation between identical coordinates must yield distance 0.0."""
        test_coords = [
            (0.0, 0.0),
            (51.5074, -0.1278),
            (40.7128, -74.0060),
            (-33.8688, 151.2093),
            (90.0, 0.0),
            (-90.0, 0.0),
            (89.9999, 179.9999),
        ]
        for lat, lon in test_coords:
            d = haversine_distance(lat, lon, lat, lon)
            assert d == 0.0, f"Expected 0.0 for identical coordinates ({lat}, {lon}), got {d}"

    def test_haversine_polar_coincidence(self):
        """Points at exact poles with different longitudes represent the same physical point."""
        # At latitude 90.0 (North Pole), all longitudes converge to 0 distance
        d_north = haversine_distance(90.0, 0.0, 90.0, 180.0)
        assert d_north < 1e-6, f"North Pole coincidence should be < 1µm, got {d_north}m"

        d_north_90 = haversine_distance(90.0, -45.0, 90.0, 135.0)
        assert d_north_90 < 1e-6, f"North Pole coincidence should be < 1µm, got {d_north_90}m"

        # At latitude -90.0 (South Pole)
        d_south = haversine_distance(-90.0, 0.0, -90.0, 90.0)
        assert d_south < 1e-6, f"South Pole coincidence should be < 1µm, got {d_south}m"

    def test_haversine_micro_meter_separation(self):
        """1 micrometre (1e-6m) separation across meridians, parallels, and diagonals."""
        target_m = 1e-6

        # 1. Meridian (delta latitude) across various latitudes
        for lat in [0.0, 25.0, 45.0, 65.0, 80.0, 88.0]:
            d_lat = target_m * DEG_PER_M
            d = haversine_distance(lat, 0.0, lat + d_lat, 0.0)
            rel_err = abs(d - target_m) / target_m
            assert rel_err < 1e-3, f"Meridian rel_err {rel_err} too high at lat={lat}"

        # 2. Parallel (delta longitude) across various latitudes
        for lat in [0.0, 25.0, 45.0, 65.0, 80.0, 85.0]:
            cos_lat = math.cos(math.radians(lat))
            d_lon = (target_m / cos_lat) * DEG_PER_M
            d = haversine_distance(lat, 0.0, lat, d_lon)
            rel_err = abs(d - target_m) / target_m
            assert rel_err < 1e-3, f"Parallel rel_err {rel_err} too high at lat={lat}"

        # 3. Diagonal separation
        for lat in [0.0, 45.0, 80.0]:
            cos_lat = math.cos(math.radians(lat))
            step = (target_m / math.sqrt(2)) * DEG_PER_M
            d = haversine_distance(lat, 0.0, lat + step, step / cos_lat)
            rel_err = abs(d - target_m) / target_m
            assert rel_err < 1e-3, f"Diagonal rel_err {rel_err} too high at lat={lat}"

    def test_haversine_polar_half_circumference(self):
        """Distance between North Pole and South Pole must equal pi * R."""
        expected = math.pi * EARTH_RADIUS_METRES
        d = haversine_distance(90.0, 0.0, -90.0, 0.0)
        assert abs(d - expected) < 1e-6, f"Pole-to-pole distance mismatch: {d} vs {expected}"

    def test_haversine_antipodal_numerical_stability(self):
        """Antipodal coordinates must not produce NaN, math domain errors, or unbound error."""
        expected = math.pi * EARTH_RADIUS_METRES

        test_antipodes = [
            ((0.0, 0.0), (0.0, 180.0)),
            ((0.0, 45.0), (0.0, -135.0)),
            ((20.0, 30.0), (-20.0, -150.0)),
            ((45.0, -60.0), (-45.0, 120.0)),
            ((60.0, 90.0), (-60.0, -90.0)),
            ((89.9999, 10.0), (-89.9999, -170.0)),
        ]
        for p1, p2 in test_antipodes:
            d = haversine_distance(p1[0], p1[1], p2[0], p2[1])
            assert not math.isnan(d), f"Antipode {p1} vs {p2} produced NaN"
            assert not math.isinf(d), f"Antipode {p1} vs {p2} produced Inf"
            diff = abs(d - expected)
            # Due to float64 catastrophic cancellation near a=1, antipodal error is bounded by ~0.15m
            assert diff <= 0.20, f"Antipodal error {diff}m exceeded 0.20m bound for {p1} vs {p2}"


class TestConflictEdgeFormationBoundaries:
    """Empirical challenge of closed-disc conflict edge formation and boundary tolerances."""

    def test_boundary_conditions_micro_meter_precision(self):
        """Edge (u, v) formed iff d(u, v) <= r_u + r_v + 1e-6."""
        r_u = 600.0
        r_v = 400.0
        threshold = 1000.0

        def make_pair(dist_m):
            d_lat = dist_m * DEG_PER_M
            return [
                {"tower_id": "U", "latitude": 0.0, "longitude": 0.0, "range_m": r_u, "radio": "4G"},
                {"tower_id": "V", "latitude": d_lat, "longitude": 0.0, "range_m": r_v, "radio": "4G"},
            ]

        # 1. d = threshold - 1µm -> MUST HAVE EDGE
        g = build_interference_graph(make_pair(threshold - 1e-6))
        assert g.has_edge("U", "V"), "Expected edge at threshold - 1µm"

        # 2. d = threshold (exact) -> MUST HAVE EDGE
        g = build_interference_graph(make_pair(threshold))
        assert g.has_edge("U", "V"), "Expected edge at exact threshold"

        # 3. d = threshold + 0.5µm -> MUST HAVE EDGE (within 1µm numerical tolerance)
        g = build_interference_graph(make_pair(threshold + 0.5e-6))
        assert g.has_edge("U", "V"), "Expected edge at threshold + 0.5µm (within epsilon)"

        # 4. d = threshold + 1.0µm -> MUST HAVE EDGE (exactly on epsilon boundary)
        g = build_interference_graph(make_pair(threshold + 1.0e-6))
        assert g.has_edge("U", "V"), "Expected edge at threshold + 1.0µm"

        # 5. d = threshold + 2.0µm -> MUST NOT HAVE EDGE (outside 1µm tolerance)
        g = build_interference_graph(make_pair(threshold + 2.0e-6))
        assert not g.has_edge("U", "V"), "Edge should NOT form at threshold + 2.0µm"

        # 6. d = threshold + 10m -> MUST NOT HAVE EDGE
        g = build_interference_graph(make_pair(threshold + 10.0))
        assert not g.has_edge("U", "V"), "Edge should NOT form at threshold + 10m"

    def test_radius_override_sensitivity_and_isolation(self):
        """radius_override_m overrides edge formation threshold without altering range_m attribute."""
        cells = [
            {"tower_id": "T1", "latitude": 0.0, "longitude": 0.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T2", "latitude": 1000.0 * DEG_PER_M, "longitude": 0.0, "range_m": 800.0, "radio": "4G"},
        ]
        # Natural threshold: 800 + 800 = 1600m > 1000m -> edge forms
        g_natural = build_interference_graph(cells)
        assert g_natural.has_edge("T1", "T2")

        # Override with 400m -> threshold: 400 + 400 = 800m < 1000m -> no edge
        g_override = build_interference_graph(cells, radius_override_m=400.0)
        assert not g_override.has_edge("T1", "T2")
        # Ensure original range_m preserved in node attributes
        assert g_override.nodes["T1"]["range_m"] == 800.0
        assert g_override.nodes["T1"]["effective_range_m"] == 400.0

    def test_candidate_pairs_and_diagnostic_invariants(self):
        """Exhaustive invariant: candidate_pairs == edges_accepted + edges_rejected == N*(N-1)/2."""
        cells = [
            {
                "tower_id": f"T_{i}",
                "latitude": float(i) * 0.005,
                "longitude": float(i % 3) * 0.005,
                "range_m": 500.0,
                "radio": "4G",
            }
            for i in range(15)
        ]
        g = build_interference_graph(cells)
        metrics = get_graph_metrics(g)

        n = g.number_of_nodes()
        expected_candidates = n * (n - 1) // 2

        assert metrics["vertex_count"] == n
        assert metrics["candidate_pairs_examined"] == expected_candidates
        assert metrics["edges_accepted"] == g.number_of_edges()
        assert metrics["edges_rejected"] == expected_candidates - g.number_of_edges()
        assert metrics["edges_accepted"] + metrics["edges_rejected"] == expected_candidates
        assert 0.0 <= metrics["coordinate_diversity"] <= 1.0


class TestCoLocatedMastConsolidation:
    """Empirical challenge of co-located mast clustering and K_49 clique elimination."""

    def test_k49_complete_clique_elimination(self):
        """49 co-located sectors must form K_49 without aggregation and collapse to 1 node with aggregation."""
        sectors = [
            {
                "tower_id": f"SEC_{i:02d}",
                "latitude": 51.5074,
                "longitude": -0.1278,
                "range_m": 500.0 if i % 2 == 0 else 800.0,
                "radio": "5G" if i % 3 == 0 else "4G",
                "range_source": "reported" if i == 5 else "fallback",
                "is_range_estimated": (i != 5),
            }
            for i in range(49)
        ]

        # Case 1: Without aggregation (aggregate_2m=False)
        g_raw = build_interference_graph(sectors, aggregate_2m=False)
        assert g_raw.number_of_nodes() == 49
        expected_edges = 49 * 48 // 2  # 1176 edges
        assert g_raw.number_of_edges() == expected_edges
        metrics_raw = get_graph_metrics(g_raw)
        assert metrics_raw["density"] == 1.0
        assert metrics_raw["delta_g"] == 48

        # Case 2: With aggregation (aggregate_2m=True)
        g_agg = build_interference_graph(sectors, aggregate_2m=True)
        assert g_agg.number_of_nodes() == 1
        assert g_agg.number_of_edges() == 0
        node_id, attrs = list(g_agg.nodes(data=True))[0]
        assert attrs["sector_count"] == 49
        assert attrs["range_m"] == 800.0  # max range preserved
        assert attrs["is_co_located"] is True
        assert len(attrs["sectors"]) == 49
        assert "4G" in attrs["radios"] and "5G" in attrs["radios"]

    def test_multi_mast_clique_suppression(self):
        """Three distinct masts with multiple sectors each should condense to 3 vertices."""
        mast1_sectors = [
            {"tower_id": f"M1_S{i}", "latitude": 51.5000, "longitude": -0.1200, "range_m": 800.0, "radio": "4G"}
            for i in range(20)
        ]
        # Mast 2 is 500m away from Mast 1 (overlap since 800m + 800m = 1600m >= 500m)
        d_lat_500m = 500.0 * DEG_PER_M
        mast2_sectors = [
            {"tower_id": f"M2_S{i}", "latitude": 51.5000 + d_lat_500m, "longitude": -0.1200, "range_m": 800.0, "radio": "5G"}
            for i in range(15)
        ]
        # Mast 3 is 50km away (completely isolated)
        d_lat_50km = 50_000.0 * DEG_PER_M
        mast3_sectors = [
            {"tower_id": f"M3_S{i}", "latitude": 51.5000 + d_lat_50km, "longitude": -0.1200, "range_m": 500.0, "radio": "4G"}
            for i in range(14)
        ]

        all_sectors = mast1_sectors + mast2_sectors + mast3_sectors
        assert len(all_sectors) == 49

        # Raw graph: K_20 + K_15 + K_14 + cross edges between Mast 1 and Mast 2
        g_raw = build_interference_graph(all_sectors, aggregate_2m=False)
        assert g_raw.number_of_nodes() == 49
        # Edges: binom(20,2)=190 + binom(15,2)=105 + binom(14,2)=91 + 20*15=300 cross edges = 686 edges
        assert g_raw.number_of_edges() == 686

        # Aggregated graph: exactly 3 vertices, 1 conflict edge between Mast 1 and Mast 2
        g_agg = build_interference_graph(all_sectors, aggregate_2m=True)
        assert g_agg.number_of_nodes() == 3
        assert g_agg.number_of_edges() == 1

    def test_2m_distance_threshold_boundaries(self):
        """Test aggregation threshold at 1.9m, 1.999m, vs 2.1m, 5.0m."""
        def make_pair(dist_m):
            d_lat = dist_m * DEG_PER_M
            return [
                {"tower_id": "T1", "latitude": 51.5074, "longitude": -0.1278, "range_m": 500.0, "radio": "4G"},
                {"tower_id": "T2", "latitude": 51.5074 + d_lat, "longitude": -0.1278, "range_m": 500.0, "radio": "4G"},
            ]

        # 1.9m -> consolidated into 1 site
        agg_1_9 = aggregate_towers_within_distance(make_pair(1.9), distance_threshold_m=2.0)
        assert len(agg_1_9) == 1

        # 1.999m -> consolidated into 1 site
        agg_1_999 = aggregate_towers_within_distance(make_pair(1.999), distance_threshold_m=2.0)
        assert len(agg_1_999) == 1

        # 2.05m -> NOT consolidated (2 sites)
        agg_2_05 = aggregate_towers_within_distance(make_pair(2.05), distance_threshold_m=2.0)
        assert len(agg_2_05) == 2

        # 5.0m -> NOT consolidated (2 sites)
        agg_5_0 = aggregate_towers_within_distance(make_pair(5.0), distance_threshold_m=2.0)
        assert len(agg_5_0) == 2


class TestIndependentValidatorAdversarial:
    """Empirical challenge of independent validator against deliberate graph corruption."""

    def test_validator_catches_all_color_conflicts(self):
        """Construct complete graph K_5 colored with 1 color -> must catch exactly binom(5,2)=10 conflicts."""
        g = nx.complete_graph(5)
        for u, v in g.edges():
            g.edges[u, v]["distance_m"] = 100.0
            g.edges[u, v]["threshold_m"] = 1000.0

        all_zero_coloring = {n: 0 for n in g.nodes()}
        val = validate_coloring(g, all_zero_coloring)
        assert not val["is_valid"]
        assert val["conflict_count"] == 10
        assert len(val["conflicts"]) == 10
        assert len(val["conflicting_edges"]) == 10
        assert val["edges_inspected"] == 10

    def test_validator_detects_single_injected_conflict_in_large_graph(self):
        """In a 50-node graph colored validly, injecting 1 conflict must be detected 100% of the time."""
        random.seed(123)
        g = nx.erdos_renyi_graph(50, 0.2, seed=123)
        for u, v in g.edges():
            g.edges[u, v]["distance_m"] = 200.0
            g.edges[u, v]["threshold_m"] = 1000.0

        dsatur_res = color_dsatur(g)
        clean_val = dsatur_res["validation"]
        assert clean_val["is_valid"]
        assert clean_val["conflict_count"] == 0

        # Inject conflict on first edge
        edge = list(g.edges())[0]
        u, v = edge
        corrupt_coloring = dict(dsatur_res["coloring"])
        corrupt_coloring[u] = corrupt_coloring[v]

        corrupt_val = validate_coloring(g, corrupt_coloring)
        assert not corrupt_val["is_valid"]
        assert corrupt_val["conflict_count"] >= 1
        conflict_pairs = corrupt_val["conflicts"]
        assert (u, v) in conflict_pairs or (v, u) in conflict_pairs

    def test_validator_detects_boundary_violations(self):
        """Edges with distance > threshold + 1e-6 must be caught and invalidate the graph."""
        g = nx.Graph()
        g.add_edge("A", "B", distance_m=1200.0, threshold_m=1000.0)  # +200m violation
        g.add_edge("B", "C", distance_m=1000.0 + 2e-6, threshold_m=1000.0)  # +2µm violation
        g.add_edge("C", "D", distance_m=900.0, threshold_m=1000.0)  # legal edge

        coloring = {"A": 0, "B": 1, "C": 0, "D": 1}
        val = validate_coloring(g, coloring)
        assert not val["is_valid"]
        assert val["boundary_violation_count"] == 2
        assert len(val["boundary_violations"]) == 2

        # Verify edge attributes recorded in violation payload
        viol_sources = {(v["source"], v["target"]) for v in val["boundary_violations"]}
        assert ("A", "B") in viol_sources or ("B", "A") in viol_sources
        assert ("B", "C") in viol_sources or ("C", "B") in viol_sources

    def test_validator_detects_zero_distance_edges(self):
        """Edges with distance < 1e-6m must be caught and reported in zero_distance_edges."""
        g = nx.Graph()
        g.add_edge("X", "Y", distance_m=0.0, threshold_m=1000.0)
        g.add_edge("Y", "Z", distance_m=0.5e-6, threshold_m=1000.0)
        g.add_edge("Z", "W", distance_m=10.0, threshold_m=1000.0)

        coloring = {"X": 0, "Y": 1, "Z": 2, "W": 3}
        val = validate_coloring(g, coloring)
        assert val["zero_distance_count"] == 2
        assert len(val["zero_distance_edges"]) == 2

    def test_validator_rejects_missing_and_malformed_colorings(self):
        """Validator must reject missing nodes, None, booleans, negative numbers, and strings."""
        g = nx.path_graph(4)  # nodes 0, 1, 2, 3
        for u, v in g.edges():
            g.edges[u, v]["distance_m"] = 100.0
            g.edges[u, v]["threshold_m"] = 500.0

        # 1. Missing node 3
        val_missing = validate_coloring(g, {0: 0, 1: 1, 2: 0})
        assert not val_missing["is_valid"]
        assert 3 in val_missing["missing_nodes"]

        # 2. None value for node 2
        val_none = validate_coloring(g, {0: 0, 1: 1, 2: None, 3: 0})
        assert not val_none["is_valid"]
        assert 2 in val_none["missing_nodes"]

        # 3. Negative integer
        val_neg = validate_coloring(g, {0: 0, 1: 1, 2: -1, 3: 0})
        assert not val_neg["is_valid"]
        assert 2 in val_neg["missing_nodes"]

        # 4. Boolean True
        val_bool = validate_coloring(g, {0: 0, 1: 1, 2: True, 3: 0})
        assert not val_bool["is_valid"]
        assert 2 in val_bool["missing_nodes"]

        # 5. String value
        val_str = validate_coloring(g, {0: 0, 1: 1, 2: "channel_1", 3: 0})
        assert not val_str["is_valid"]
        assert 2 in val_str["missing_nodes"]

    def test_validator_100_percent_edge_inspection(self):
        """Validator must inspect every single edge in the graph without early bailout."""
        g = nx.cycle_graph(20)
        for u, v in g.edges():
            g.edges[u, v]["distance_m"] = 50.0
            g.edges[u, v]["threshold_m"] = 500.0

        wp_res = color_welsh_powell(g)
        val = validate_coloring(g, wp_res["coloring"])
        assert val["is_valid"]
        assert val["edges_inspected"] == 20
        assert val["edges_inspected"] == g.number_of_edges()
