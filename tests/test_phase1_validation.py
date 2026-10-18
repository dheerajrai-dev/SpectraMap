r"""
tests/test_phase1_validation.py — Comprehensive Phase 1 Verification Test Suite

Validates all 7 items of Phase 1: Mathematical and Data Correctness:
1. Geolocation and coordinate handling (poles, antipodes, antimeridian, precision stability).
2. Individual estimated coverage radii with explicit 4-tier fallback hierarchy, metadata flags, and warnings.
3. Documented closed-disk overlap graph model ($d \le r_1 + r_2$) with distance and threshold attributes.
4. Dual heuristic graph invariance and deterministic execution on identical graph representations.
5. Bounded exact chromatic number solver (DSatur B&B for N <= 25, 500ms monotonic clock timeout,
   N=26 size bound, discrepancy proof case where Exact=4 beats DSatur=5 and Welsh-Powell=5).
6. Independent coloring validation engine (zero adjacent conflicts, 100% vertex coverage, type safety).
7. End-to-end integration through `/api/optimize` ensuring exact solver results are surfaced.
"""

import copy
import math
import time
import pytest
import networkx as nx
from fastapi.testclient import TestClient

from app import app
import app as app_module
from data_service import (
    haversine_distance,
    calculate_bounding_box,
    validate_cell_record,
    normalize_cell_record,
    parse_opencellid_response,
    RADIO_FALLBACK_RADII,
    DEFAULT_FALLBACK_RADIUS,
    MIN_VALID_RANGE_M,
    MAX_VALID_RANGE_M,
    EARTH_RADIUS_METRES,
)
from graph_engine import (
    build_interference_graph,
    color_welsh_powell,
    color_dsatur,
    color_exact_dsatur_bnb,
    validate_coloring,
    optimize_graph_frequencies,
    get_graph_metrics,
    get_interference_edges,
)


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# ITEM 1: Geolocation & Coordinate Handling
# ==============================================================================
class TestPhase1Item1GeolocationCoordinates:
    """Verifies spherical Haversine math, coordinate limits, polar singularites, and stability."""

    def test_haversine_exact_poles_and_polar_distance(self):
        """Distance from North Pole to South Pole must equal pi * R with zero domain errors."""
        north_pole = (90.0, 0.0)
        south_pole = (-90.0, 0.0)
        dist = haversine_distance(north_pole[0], north_pole[1], south_pole[0], south_pole[1])
        expected_dist = math.pi * EARTH_RADIUS_METRES
        assert math.isclose(dist, expected_dist, rel_tol=1e-5)

        # Distance from North Pole to North Pole is 0.0 (regardless of arbitrary longitude)
        assert math.isclose(haversine_distance(90.0, 45.0, 90.0, -120.0), 0.0, abs_tol=1e-6)

    def test_haversine_antipodal_points_clamping(self):
        """Opposite sides of the globe (180 deg apart) must not trigger math domain error."""
        test_pairs = [
            ((0.0, 0.0), (0.0, 180.0)),
            ((0.0, 0.0), (0.0, -180.0)),
            ((45.0, -75.0), (-45.0, 105.0)),
            ((-30.0, 120.0), (30.0, -60.0)),
        ]
        expected_half_circumference = math.pi * EARTH_RADIUS_METRES
        for (lat1, lon1), (lat2, lon2) in test_pairs:
            dist = haversine_distance(lat1, lon1, lat2, lon2)
            assert not math.isnan(dist)
            assert not math.isinf(dist)
            assert math.isclose(dist, expected_half_circumference, rel_tol=1e-4)

    def test_haversine_antimeridian_crossing(self):
        """Shortest distance across 180/-180 meridian must be direct, not circumferential."""
        lat = 0.0
        lon_west = 179.95
        lon_east = -179.95
        # Angular separation is 0.1 degree
        dist = haversine_distance(lat, lon_west, lat, lon_east)
        expected_direct = (0.1 * math.pi / 180.0) * EARTH_RADIUS_METRES
        assert math.isclose(dist, expected_direct, rel_tol=1e-4)
        assert dist < 15_000.0  # ~11.1 km, NOT ~40,000 km circumferential wrap

    def test_haversine_numerical_precision_and_zero_distance(self):
        """Identical coordinates must evaluate to 0.0; microscopic deltas remain positive."""
        assert haversine_distance(28.6139, 77.2090, 28.6139, 77.2090) == 0.0

        # Sub-meter delta (~1.1 meter)
        dist_micro = haversine_distance(28.6139, 77.2090, 28.61390001, 77.2090)
        assert dist_micro > 0.0
        assert dist_micro < 0.01

    def test_bounding_box_meridian_convergence_and_polar_protection(self):
        """Polar protection must wrap longitude to [-180, 180] when latitude approaches +/-90."""
        # Near North Pole (89.95 deg N)
        min_lat, min_lon, max_lat, max_lon = calculate_bounding_box(89.95, 0.0, 5000.0)
        assert min_lon == -180.0
        assert max_lon == 180.0
        assert max_lat <= 90.0
        assert min_lat < max_lat

        # Near South Pole (-89.99 deg S)
        min_lat, min_lon, max_lat, max_lon = calculate_bounding_box(-89.99, 10.0, 5000.0)
        assert min_lon == -180.0
        assert max_lon == 180.0
        assert min_lat >= -90.0
        assert min_lat < max_lat

        # Mid-latitude: longitude delta correctly expands due to cos(lat) convergence
        _, min_lon_eq, _, max_lon_eq = calculate_bounding_box(0.0, 0.0, 10000.0)
        _, min_lon_mid, _, max_lon_mid = calculate_bounding_box(60.0, 0.0, 10000.0)
        delta_eq = max_lon_eq - min_lon_eq
        delta_mid = max_lon_mid - min_lon_mid
        assert delta_mid > delta_eq  # cos(60) = 0.5, delta_mid ~ 2 * delta_eq

    def test_strict_coordinate_validation_bounds(self):
        """validate_cell_record must accept [-90, 90] and [-180, 180] and reject out-of-bounds."""
        base_valid = {"cellid": 100, "lat": 0.0, "lon": 0.0, "range": 500}
        assert validate_cell_record(base_valid) is True

        # Boundary extremes
        for lat in [-90.0, 90.0]:
            for lon in [-180.0, 180.0]:
                assert validate_cell_record({"cellid": 1, "lat": lat, "lon": lon, "range": 500}) is True

        # Out of bounds
        assert validate_cell_record({"cellid": 1, "lat": 90.001, "lon": 0.0, "range": 500}) is False
        assert validate_cell_record({"cellid": 1, "lat": -90.001, "lon": 0.0, "range": 500}) is False
        assert validate_cell_record({"cellid": 1, "lat": 0.0, "lon": 180.001, "range": 500}) is False
        assert validate_cell_record({"cellid": 1, "lat": 0.0, "lon": -180.001, "range": 500}) is False


# ==============================================================================
# ITEM 2: Coverage Radii & 4-Tier Fallback Hierarchy
# ==============================================================================
class TestPhase1Item2CoverageRadiiFallbacks:
    """Verifies coverage radii fallback assignments, anomaly handling, and metadata tracking."""

    @pytest.mark.parametrize(
        "radio_str,expected_radius",
        [
            ("GSM", 1000.0),
            ("gsm", 1000.0),
            ("2G", 1000.0),
            ("CDMA", 1000.0),
            ("cdma", 1000.0),
            ("UMTS", 800.0),
            ("umts", 800.0),
            ("3G", 800.0),
            ("LTE", 800.0),
            ("lte", 800.0),
            ("4G", 800.0),
            ("NR", 500.0),
            ("nr", 500.0),
            ("5G", 500.0),
            ("UNKNOWN", 800.0),
            ("WIFI", 800.0),
            ("", 800.0),
            (None, 800.0),
        ],
    )
    def test_fallback_radii_by_radio_technology(self, radio_str, expected_radius):
        """Missing or non-positive range must assign standard radio default radius."""
        raw = {"cellid": 101, "lat": 28.5, "lon": 77.2, "range": 0, "radio": radio_str}
        assert validate_cell_record(raw) is True
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == expected_radius
        assert norm["is_range_estimated"] is True
        assert norm["range_source"] == "fallback_default"
        assert norm["fallback_reason"] == "zero"
        assert len(norm["warnings"]) == 1

    @pytest.mark.parametrize(
        "raw_range,expected_reason",
        [
            (None, "null"),
            (0, "zero"),
            (0.0, "zero"),
            ("0", "zero"),
            (-100, "negative"),
            (-0.01, "negative"),
            ("-50.5", "negative"),
            ("not_a_num", "non_numeric"),
            ("N/A", "non_numeric"),
        ],
    )
    def test_fallback_reasons_and_metadata_flags(self, raw_range, expected_reason):
        """Verify explicit fallback_reason metadata string and is_range_estimated flag."""
        raw = {"cellid": 202, "lat": 28.5, "lon": 77.2, "range": raw_range, "radio": "LTE"}
        norm = normalize_cell_record(raw)
        assert norm["is_range_estimated"] is True
        assert norm["range_source"] == "fallback_default"
        assert norm["fallback_reason"] == expected_reason
        assert norm["range_m"] == 800.0
        assert len(norm["warnings"]) == 1
        assert "applied default estimate" in norm["warnings"][0]

    def test_missing_range_key_entirely(self):
        """Cell record lacking 'range' key entirely must be assigned missing fallback."""
        raw = {"cellid": 303, "lat": 28.5, "lon": 77.2, "radio": "NR"}
        assert validate_cell_record(raw) is True
        norm = normalize_cell_record(raw)
        assert norm["is_range_estimated"] is True
        assert norm["range_source"] == "fallback_default"
        assert norm["fallback_reason"] == "missing"
        assert norm["range_m"] == 500.0

    def test_outlier_range_clamping(self):
        """Ranges > 10000m clamped to 10000m, ranges < 50m clamped to 50m."""
        # High outlier
        raw_high = {"cellid": 404, "lat": 28.5, "lon": 77.2, "range": 25000.0, "radio": "LTE"}
        norm_high = normalize_cell_record(raw_high)
        assert norm_high["range_m"] == MAX_VALID_RANGE_M  # 10000.0
        assert norm_high["is_range_estimated"] is True
        assert norm_high["range_source"] == "fallback_clamped"
        assert norm_high["fallback_reason"] == "outlier"
        assert "clamped" in norm_high["warnings"][0]

        # Low outlier
        raw_low = {"cellid": 405, "lat": 28.5, "lon": 77.2, "range": 15.0, "radio": "LTE"}
        norm_low = normalize_cell_record(raw_low)
        assert norm_low["range_m"] == MIN_VALID_RANGE_M  # 50.0
        assert norm_low["is_range_estimated"] is True
        assert norm_low["range_source"] == "fallback_clamped"
        assert norm_low["fallback_reason"] == "outlier"
        assert "clamped" in norm_low["warnings"][0]

    def test_valid_reported_range_preservation(self):
        """Valid reported range [50, 10000] is preserved as-is with is_range_estimated = False."""
        valid_ranges = [50.0, 350.0, 1200.0, 10000.0]
        for rng in valid_ranges:
            raw = {"cellid": 501, "lat": 28.5, "lon": 77.2, "range": rng, "radio": "LTE"}
            norm = normalize_cell_record(raw)
            assert norm["range_m"] == rng
            assert norm["is_range_estimated"] is False
            assert norm["range_source"] == "reported"
            assert norm["fallback_reason"] is None
            assert len(norm["warnings"]) == 0

    def test_parse_opencellid_response_aggregates_warnings(self):
        """parse_opencellid_response collects fallback warnings without dropping valid cell positions."""
        payload = {
            "cells": [
                {"cellid": 1, "lat": 28.5, "lon": 77.2, "range": 500, "radio": "LTE"},
                {"cellid": 2, "lat": 28.51, "lon": 77.21, "range": 0, "radio": "GSM"},
                {"cellid": 3, "lat": 28.52, "lon": 77.22, "range": 25000, "radio": "NR"},
                {"cellid": 4, "lat": 150.0, "lon": 77.22, "range": 500, "radio": "NR"},  # Invalid lat -> dropped
            ]
        }
        cells, warnings = parse_opencellid_response(payload)
        assert len(cells) == 3
        # 3 warnings: 2 coverage fallbacks (zero and outlier) + 1 rejected invalid coordinate record
        assert len(warnings) == 3
        assert any("applied default estimate" in w for w in warnings)
        assert any("clamped" in w for w in warnings)
        assert any("Rejected invalid cell record" in w for w in warnings)


# ==============================================================================
# ITEM 3: Documented Overlap-Based Graph Model
# ==============================================================================
class TestPhase1Item3OverlapGraphModel:
    """Verifies closed-disk overlap criterion (d <= r1 + r2) and edge attributes."""

    def test_closed_disk_overlap_criterion(self):
        """Edge exists iff d(u, v) <= r_u + r_v. Interior, tangent, and separated pairs."""
        center_lat, center_lon = 28.6000, 77.2000
        # Calculate coordinate offsets
        # At latitude 28.6, 1 deg lat ~ 111,195 m; 0.004 deg ~ 444.8 m
        dist_approx = haversine_distance(28.6000, 77.2000, 28.6040, 77.2000)

        # 1. Overlapping interior: r1 + r2 = 300 + 300 = 600m > dist (~445m)
        cells_overlap = [
            {"tower_id": "T1", "latitude": 28.6000, "longitude": 77.2000, "range_m": 300.0, "radio": "LTE", "cell_id": 1},
            {"tower_id": "T2", "latitude": 28.6040, "longitude": 77.2000, "range_m": 300.0, "radio": "LTE", "cell_id": 2},
        ]
        g1 = build_interference_graph(cells_overlap)
        assert g1.has_edge("T1", "T2")

        # 2. Separated exterior: r1 + r2 = 200 + 200 = 400m < dist (~445m)
        cells_separated = [
            {"tower_id": "T1", "latitude": 28.6000, "longitude": 77.2000, "range_m": 200.0, "radio": "LTE", "cell_id": 1},
            {"tower_id": "T2", "latitude": 28.6040, "longitude": 77.2000, "range_m": 200.0, "radio": "LTE", "cell_id": 2},
        ]
        g2 = build_interference_graph(cells_separated)
        assert not g2.has_edge("T1", "T2")

        # 3. Tangent boundary: r1 + r2 == dist
        exact_r = dist_approx / 2.0
        cells_tangent = [
            {"tower_id": "T1", "latitude": 28.6000, "longitude": 77.2000, "range_m": exact_r, "radio": "LTE", "cell_id": 1},
            {"tower_id": "T2", "latitude": 28.6040, "longitude": 77.2000, "range_m": exact_r, "radio": "LTE", "cell_id": 2},
        ]
        g3 = build_interference_graph(cells_tangent)
        assert g3.has_edge("T1", "T2")

    def test_edge_attributes_distance_and_threshold(self):
        """Edges must store 'distance_m' and 'threshold_m' rounded to 1 decimal place."""
        cells = [
            {"tower_id": "A", "latitude": 28.6000, "longitude": 77.2000, "range_m": 500.0, "radio": "LTE", "cell_id": 1},
            {"tower_id": "B", "latitude": 28.6030, "longitude": 77.2000, "range_m": 600.0, "radio": "LTE", "cell_id": 2},
        ]
        g = build_interference_graph(cells)
        assert g.has_edge("A", "B")
        edge_data = g["A"]["B"]
        assert "distance_m" in edge_data
        assert "threshold_m" in edge_data
        assert edge_data["threshold_m"] == 1100.0
        assert edge_data["distance_m"] <= edge_data["threshold_m"]
        assert isinstance(edge_data["distance_m"], float)

    def test_node_attributes_preservation(self):
        """All metadata on cell records must be preserved on graph nodes."""
        cells = [
            {
                "tower_id": "Tower_Alpha",
                "latitude": 28.6000,
                "longitude": 77.2000,
                "range_m": 800.0,
                "radio": "GSM",
                "is_range_estimated": True,
                "range_source": "fallback_default",
                "cell_id": 999,
            }
        ]
        g = build_interference_graph(cells)
        node_data = g.nodes["Tower_Alpha"]
        assert node_data["tower_id"] == "Tower_Alpha"
        assert node_data["latitude"] == 28.6000
        assert node_data["longitude"] == 77.2000
        assert node_data["range_m"] == 800.0
        assert node_data["radio"] == "GSM"
        assert node_data["is_range_estimated"] is True
        assert node_data["range_source"] == "fallback_default"
        assert node_data["cell_id"] == 999

    def test_get_interference_edges_formatting(self):
        """get_interference_edges outputs endpoint coordinates and distance for map rendering."""
        cells = [
            {"tower_id": "A", "latitude": 28.6000, "longitude": 77.2000, "range_m": 500.0, "radio": "LTE", "cell_id": 1},
            {"tower_id": "B", "latitude": 28.6020, "longitude": 77.2000, "range_m": 500.0, "radio": "LTE", "cell_id": 2},
        ]
        g = build_interference_graph(cells)
        edges = get_interference_edges(g)
        assert len(edges) == 1
        e = edges[0]
        assert e["source_id"] == "A"
        assert e["target_id"] == "B"
        assert e["source_coords"] == [28.6000, 77.2000]
        assert e["target_coords"] == [28.6020, 77.2000]
        assert e["distance_m"] > 0.0


# ==============================================================================
# ITEM 4: Dual Heuristic Graph Invariance & Determinism
# ==============================================================================
class TestPhase1Item4DualHeuristicGraphInvariance:
    """Verifies DSatur and Welsh-Powell operate on identical immutable graph instances."""

    def test_graph_immutability_across_solvers(self):
        """Solvers must not add/remove nodes, edges, or mutate node/edge dictionaries."""
        g = nx.erdos_renyi_graph(15, 0.4, seed=42)
        # Add rich attributes
        for n in g.nodes():
            g.nodes[n]["attr_test"] = f"val_{n}"
        for u, v in g.edges():
            g[u][v]["distance_m"] = 100.0

        nodes_before = copy.deepcopy(dict(g.nodes(data=True)))
        edges_before = copy.deepcopy(dict(g.adjacency()))

        # Run Welsh-Powell, DSatur, Exact
        wp_res = color_welsh_powell(g)
        ds_res = color_dsatur(g)
        ex_res = color_exact_dsatur_bnb(g)

        nodes_after = copy.deepcopy(dict(g.nodes(data=True)))
        edges_after = copy.deepcopy(dict(g.adjacency()))

        assert nodes_before == nodes_after
        assert edges_before == edges_after
        assert wp_res["validation"]["is_valid"] is True
        assert ds_res["validation"]["is_valid"] is True
        assert ex_res["validation"]["is_valid"] is True

    def test_deterministic_solver_reproducibility(self):
        """Consecutive runs on identical graphs must yield identical color assignments."""
        g = nx.erdos_renyi_graph(20, 0.35, seed=123)
        initial_wp = color_welsh_powell(g)
        initial_ds = color_dsatur(g)
        initial_ex = color_exact_dsatur_bnb(g)

        for _ in range(5):
            assert color_welsh_powell(g)["coloring"] == initial_wp["coloring"]
            assert color_dsatur(g)["coloring"] == initial_ds["coloring"]
            assert color_exact_dsatur_bnb(g)["coloring"] == initial_ex["coloring"]


# ==============================================================================
# ITEM 5: Bounded Exact Chromatic Solver & Discrepancy Case
# ==============================================================================
class TestPhase1Item5BoundedExactChromaticSolver:
    """Verifies exact DSatur B&B solver, bounds (N<=25), monotonic timeout, and discrepancy case."""

    @pytest.mark.parametrize(
        "graph_factory,expected_chi",
        [
            (lambda: nx.Graph(), 0),                              # Empty
            (lambda: nx.path_graph(1), 1),                         # Single vertex
            (lambda: nx.empty_graph(5), 1),                        # 5 isolated nodes
            (lambda: nx.complete_graph(3), 3),                     # K_3
            (lambda: nx.complete_graph(5), 5),                     # K_5
            (lambda: nx.complete_graph(10), 10),                   # K_10
            (lambda: nx.cycle_graph(4), 2),                        # C_4 (even)
            (lambda: nx.cycle_graph(6), 2),                        # C_6 (even)
            (lambda: nx.cycle_graph(5), 3),                        # C_5 (odd)
            (lambda: nx.cycle_graph(7), 3),                        # C_7 (odd)
            (lambda: nx.complete_bipartite_graph(4, 5), 2),       # K_4,5
            (lambda: nx.star_graph(15), 2),                        # S_15
            (lambda: nx.wheel_graph(5), 3),                        # W_5 (K_1 * C_4)
            (lambda: nx.wheel_graph(6), 4),                        # W_6 (K_1 * C_5)
            (lambda: nx.petersen_graph(), 3),                      # Petersen
            (lambda: nx.mycielski_graph(4), 4),                    # Groetzsch (M_4)
            (lambda: nx.mycielski_graph(5), 5),                    # M_5 (N=23, triangle-free)
        ],
    )
    def test_canonical_graph_families_exact_chromatic_number(self, graph_factory, expected_chi):
        """Exact solver must find proven chromatic number on all canonical graph families."""
        g = graph_factory()
        res = color_exact_dsatur_bnb(g)
        assert res["color_count"] == expected_chi
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["validation"]["is_valid"] is True
        assert res["validation"]["color_count"] == expected_chi

    def test_discrepancy_case_exact_beats_both_heuristics(self):
        """On G(18, 0.4, seed=3), Welsh-Powell=5, DSatur=5, but Exact=4 proven optimal."""
        g = nx.erdos_renyi_graph(18, 0.4, seed=3)
        wp_res = color_welsh_powell(g)
        ds_res = color_dsatur(g)
        ex_res = color_exact_dsatur_bnb(g)

        assert wp_res["color_count"] == 5
        assert ds_res["color_count"] == 5
        assert ex_res["color_count"] == 4
        assert ex_res["proven_optimal"] is True
        assert ex_res["status"] == "exact_optimal"
        assert ex_res["color_count"] < ds_res["color_count"]

        # optimize_graph_frequencies must select exact_dsatur_bnb
        opt = optimize_graph_frequencies(g, run_exact=True)
        assert opt["best_algorithm"] == "exact_dsatur_bnb"
        assert opt["exact"]["color_count"] == 4

    def test_exact_solver_size_boundary_enforcement(self):
        """Exact solver executes at N=25 and cleanly skips at N=26."""
        # N = 25: must execute
        g25 = nx.path_graph(25)
        res25 = color_exact_dsatur_bnb(g25, max_nodes=25)
        assert res25["status"] == "exact_optimal"
        assert res25["proven_optimal"] is True

        # N = 26: must skip branch-and-bound
        g26 = nx.path_graph(26)
        res26 = color_exact_dsatur_bnb(g26, max_nodes=25)
        assert res26["status"] == "skipped_size_limit"
        assert res26["proven_optimal"] is False
        assert "exceeds exact solver limit" in res26["message"]
        assert res26["validation"]["is_valid"] is True

    def test_exact_solver_monotonic_clock_timeout(self):
        """Solver halts safely within deadline on microscopic timeout and returns valid coloring."""
        # Use a graph topology where Upper Bound > Lower Bound so branching is required
        g = nx.erdos_renyi_graph(18, 0.4, seed=3)
        t0 = time.perf_counter()
        res = color_exact_dsatur_bnb(g, max_nodes=25, timeout_sec=0.000001)
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.2  # Fast abort
        assert res["status"] == "timeout"
        assert res["proven_optimal"] is False
        assert res["validation"]["is_valid"] is True
        assert res["color_count"] >= 1


# ==============================================================================
# ITEM 6: Independent Coloring Validation Engine
# ==============================================================================
class TestPhase1Item6IndependentColoringValidation:
    """Verifies strict decoupled coloring validation checking completeness, conflicts, and types."""

    def test_validator_detects_adjacent_color_collision(self):
        """Adjacent vertices sharing the same color must fail validation with conflict logged."""
        g = nx.complete_graph(3)  # K_3 with nodes 0, 1, 2
        invalid_coloring = {0: 0, 1: 0, 2: 1}  # Edge (0, 1) has collision
        val = validate_coloring(g, invalid_coloring)
        assert val["is_valid"] is False
        assert val["conflict_count"] == 1
        assert val["conflicts"] == [(0, 1)]

    def test_validator_detects_missing_node(self):
        """Incomplete coloring dictionary missing a graph node must fail validation."""
        g = nx.path_graph(4)
        incomplete_coloring = {0: 0, 1: 1, 2: 0}  # Node 3 is missing
        val = validate_coloring(g, incomplete_coloring)
        assert val["is_valid"] is False
        assert val["missing_count"] == 1
        assert 3 in val["missing_nodes"]

    def test_validator_rejects_negative_or_boolean_colors(self):
        """Negative integers, booleans (True/False), and non-integers must fail validation."""
        g = nx.path_graph(2)
        # Negative color
        val_neg = validate_coloring(g, {0: -1, 1: 0})
        assert val_neg["is_valid"] is False

        # Boolean color (in Python, isinstance(True, int) is True, so validator must guard explicitly)
        val_bool = validate_coloring(g, {0: True, 1: 0})
        assert val_bool["is_valid"] is False

        # String color
        val_str = validate_coloring(g, {0: "0", 1: 1})
        assert val_str["is_valid"] is False

    def test_validator_passes_all_solvers_across_multiple_graphs(self):
        """All solver outputs on arbitrary topologies must independently pass validate_coloring."""
        for seed in range(5):
            g = nx.erdos_renyi_graph(16, 0.3, seed=seed)
            wp = color_welsh_powell(g)
            ds = color_dsatur(g)
            ex = color_exact_dsatur_bnb(g)

            assert validate_coloring(g, wp["coloring"])["is_valid"] is True
            assert validate_coloring(g, ds["coloring"])["is_valid"] is True
            assert validate_coloring(g, ex["coloring"])["is_valid"] is True


# ==============================================================================
# ITEM 7: End-to-End Integration through /api/optimize
# ==============================================================================
class TestPhase1Item7EndToEndIntegration:
    """Verifies FastAPI /api/optimize endpoint surfaces exact solver payload and selection."""

    def test_api_optimize_exposes_exact_solver_payload(self, client):
        """POST /api/optimize must include complete 'exact' dictionary in response JSON."""
        payload = {
            "center": {"latitude": 28.63, "longitude": 77.22},
            "radius_m": 1000.0,
            "cells": [
                {"tower_id": "T1", "latitude": 28.630, "longitude": 77.220, "range_m": 500.0, "radio": "LTE", "cell_id": 1},
                {"tower_id": "T2", "latitude": 28.633, "longitude": 77.220, "range_m": 500.0, "radio": "LTE", "cell_id": 2},
                {"tower_id": "T3", "latitude": 28.636, "longitude": 77.220, "range_m": 500.0, "radio": "LTE", "cell_id": 3},
            ],
        }
        response = client.post("/api/optimize", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "exact" in data
        exact = data["exact"]
        assert exact["algorithm"] == "exact_dsatur_bnb"
        assert exact["status"] == "exact_optimal"
        assert exact["proven_optimal"] is True
        assert exact["color_count"] == 3
        assert exact["validation"]["is_valid"] is True
        assert len(data["edges"]) == 3

    def test_api_optimize_selects_exact_when_heuristics_beaten(self, client, monkeypatch):
        """When Exact strictly beats heuristics, /api/optimize returns best_algorithm='exact_dsatur_bnb'."""
        g_disc = nx.erdos_renyi_graph(18, 0.4, seed=3)
        g_mock = nx.Graph()
        for n in g_disc.nodes():
            g_mock.add_node(f"node_{n}", latitude=28.6 + n * 0.001, longitude=77.2, range_m=500.0, tower_id=f"node_{n}")
        for u, v in g_disc.edges():
            g_mock.add_edge(f"node_{u}", f"node_{v}", distance_m=100.0, threshold_m=1000.0)

        monkeypatch.setattr(app_module, "build_interference_graph", lambda cells: g_mock)

        payload = {
            "center": {"latitude": 28.6, "longitude": 77.2},
            "radius_m": 2000.0,
            "cells": [{"tower_id": "dummy", "latitude": 28.6, "longitude": 77.2, "range_m": 500.0, "cell_id": 1}],
        }
        response = client.post("/api/optimize", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["best_algorithm"] == "exact_dsatur_bnb"
        assert data["exact"]["color_count"] == 4
        assert data["dsatur"]["color_count"] == 5
        assert data["welsh_powell"]["color_count"] == 5
        assert data["exact"]["proven_optimal"] is True

    def test_api_optimize_skips_exact_solver_above_25_nodes(self, client):
        """When node count > 25, /api/optimize surfaces status='skipped_size_limit'."""
        cells = [
            {
                "tower_id": f"Tower_{i}",
                "latitude": 28.6 + i * 0.0005,
                "longitude": 77.2,
                "range_m": 500.0,
                "radio": "LTE",
                "cell_id": i,
            }
            for i in range(26)
        ]
        payload = {
            "center": {"latitude": 28.6, "longitude": 77.2},
            "radius_m": 5000.0,
            "cells": cells,
        }
        response = client.post("/api/optimize", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["metrics"]["node_count"] == 26
        assert data["exact"]["status"] == "skipped_size_limit"
        assert data["exact"]["proven_optimal"] is False
        assert data["exact"]["color_count"] == data["dsatur"]["color_count"]
