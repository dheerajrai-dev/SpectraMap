"""
tests/test_tier5_adversarial_hardening_1.py — Tier 5 Adversarial Coverage Hardening

White-box adversarial verification targeting internal branches, numerical edge cases,
polar singularities, FPS tie-breaking degeneracies, exact solver timeouts, disconnected
topologies, and schema invariant boundaries across:
- data_service.py
- graph_engine.py
- schemas.py
- app.py
"""

import json
import math
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import parse_radio_query
from data_service import (
    EARTH_RADIUS_METRES,
    aggregate_towers_within_distance,
    calculate_bounding_box,
    filter_records_by_radius,
    group_cells_into_sites,
    haversine_distance,
    load_cache,
    load_cache_fallback,
    normalize_cell_record,
    normalize_radio_type,
    save_cache,
    select_spatially_dispersed_records,
    split_bounding_box,
    validate_cell_record,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_exact_dsatur_bnb,
    color_welsh_powell,
    get_graph_metrics,
    optimize_graph_frequencies,
    validate_coloring,
)
from schemas import (
    AccountingMetadata,
    CellRecord,
    CenterCoordinates,
    SiteEntity,
)


# =====================================================================
# 1. Polar Coordinate & Bounding Box Singularities
# =====================================================================
class TestPolarAndCoordinateSingularities:
    """Adversarial stress-testing of spherical coordinates, poles, and bounding boxes."""

    def test_exact_north_and_south_poles_bounding_box(self):
        """Bounding box at +/-90 degrees latitude must trigger polar protection without crashing."""
        # North Pole
        latmin, lonmin, latmax, lonmax = calculate_bounding_box(90.0, 0.0, 5000.0)
        assert latmax == 90.0
        assert latmin < 90.0
        assert lonmin == -180.0
        assert lonmax == 180.0

        # South Pole
        latmin_s, lonmin_s, latmax_s, lonmax_s = calculate_bounding_box(-90.0, 0.0, 5000.0)
        assert latmin_s == -90.0
        assert latmax_s > -90.0
        assert lonmin_s == -180.0
        assert lonmax_s == 180.0

    def test_polar_singularity_threshold_clamping(self):
        """Near polar latitudes (|lat| >= 89.9) meridian convergence triggers full longitude [-180, 180]."""
        latmin, lonmin, latmax, lonmax = calculate_bounding_box(89.95, 45.0, 1000.0)
        assert lonmin == -180.0
        assert lonmax == 180.0
        assert latmax <= 90.0

        # Just below threshold (lat = 89.8): cos(lat) > 0, delta_lon calculated
        latmin2, lonmin2, latmax2, lonmax2 = calculate_bounding_box(89.8, 0.0, 1000.0)
        assert latmax2 <= 90.0
        # Longitude should still be bounded in [-180, 180]
        assert lonmin2 >= -180.0
        assert lonmax2 <= 180.0

    def test_split_bounding_box_at_polar_regions(self):
        """split_bounding_box with polar [-180, 180] bounds creates valid subdivision without zero division."""
        latmin, lonmin, latmax, lonmax = calculate_bounding_box(89.95, 0.0, 5000.0)
        tiles = split_bounding_box(latmin, lonmin, latmax, lonmax, max_tile_span_m=1900.0)
        assert len(tiles) >= 1
        for t_latmin, t_lonmin, t_latmax, t_lonmax in tiles:
            assert -90.0 <= t_latmin <= t_latmax <= 90.0
            assert -180.0 <= t_lonmin <= t_lonmax <= 180.0

    def test_haversine_antipodal_points_numerical_safety(self):
        """Haversine distance between exact antipodal points clamps `a` to 1.0."""
        # Equator antipodes: (0, 0) and (0, 180)
        dist = haversine_distance(0.0, 0.0, 0.0, 180.0)
        expected = math.pi * EARTH_RADIUS_METRES
        assert abs(dist - expected) < 1.0  # within 1m of half-circumference

        # Polar antipodes: (90, 0) and (-90, 0)
        dist_polar = haversine_distance(90.0, 0.0, -90.0, 0.0)
        assert abs(dist_polar - expected) < 1.0

    def test_haversine_co_located_and_zero_distance(self):
        """Identical coordinates must yield strictly 0.0 distance."""
        dist = haversine_distance(28.6139, 77.2090, 28.6139, 77.2090)
        assert dist == 0.0

    def test_haversine_antimeridian_crossing(self):
        """Haversine computes accurate short distance across 180th meridian."""
        # 179.999 deg E to -179.999 deg W at Equator: separation is 0.002 deg (~222 metres)
        dist = haversine_distance(0.0, 179.999, 0.0, -179.999)
        assert 200.0 < dist < 250.0


# =====================================================================
# 2. FPS Sampling Adversarial & Degenerate Scenarios
# =====================================================================
class TestFPSSamplingAdversarialAndDegeneracies:
    """Stress tests for deterministic Farthest Point Sampling under degenerate inputs."""

    def test_fps_all_records_co_located_tie_break(self):
        """When all candidate records are co-located at distance 0, FPS resolves ties by ascending tower_id."""
        records = [
            {"tower_id": f"4G_404_11_100_{i}", "latitude": 28.5, "longitude": 77.2, "range_m": 800.0, "radio": "4G"}
            for i in [50, 20, 80, 10, 90, 30, 40]
        ]
        # Request limit=4
        selected = select_spatially_dispersed_records(records, 28.5, 77.2, limit=4)
        assert len(selected) == 4
        # All points are at the center, so seed is 4G_404_11_100_10 (lowest tower_id).
        # Subsequent iterations see all min_dist == 0.0, so each step picks lowest unselected tower_id.
        expected_ids = [
            "4G_404_11_100_10",
            "4G_404_11_100_20",
            "4G_404_11_100_30",
            "4G_404_11_100_40",
        ]
        actual_ids = [r["tower_id"] for r in selected]
        assert actual_ids == expected_ids

    def test_fps_symmetric_geometry_tie_break(self):
        """When candidates are placed symmetrically at identical distances from center, ties break on tower_id."""
        # 4 points at north, south, east, west with equal radius
        d = 0.01
        records = [
            {"tower_id": "T_NORTH", "latitude": 28.0 + d, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T_SOUTH", "latitude": 28.0 - d, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T_EAST", "latitude": 28.0, "longitude": 77.0 + d, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T_WEST", "latitude": 28.0, "longitude": 77.0 - d, "range_m": 800.0, "radio": "4G"},
        ]
        # Request limit=2
        selected = select_spatially_dispersed_records(records, 28.0, 77.0, limit=2)
        assert len(selected) == 2
        # All 4 have identical distance to center. Seed must be lowest tower_id: 'T_EAST'
        assert selected[0]["tower_id"] == "T_EAST"

    def test_fps_candidate_count_leq_limit(self):
        """When candidates <= limit, sort deterministically by proximity to center, tie-break by tower_id."""
        records = [
            {"tower_id": "FAR", "latitude": 28.5, "longitude": 77.2, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "CLOSE_B", "latitude": 28.001, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "CLOSE_A", "latitude": 28.001, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
        ]
        selected = select_spatially_dispersed_records(records, 28.0, 77.0, limit=10)
        assert len(selected) == 3
        # CLOSE_A and CLOSE_B have identical distance to center, CLOSE_A < CLOSE_B alphabetically
        assert selected[0]["tower_id"] == "CLOSE_A"
        assert selected[1]["tower_id"] == "CLOSE_B"
        assert selected[2]["tower_id"] == "FAR"

    def test_fps_empty_and_zero_limit(self):
        """Empty records or non-positive limit cleanly returns empty list."""
        assert select_spatially_dispersed_records([], 28.0, 77.0, limit=50) == []
        recs = [{"tower_id": "A", "latitude": 28.0, "longitude": 77.0, "range_m": 800.0}]
        assert select_spatially_dispersed_records(recs, 28.0, 77.0, limit=0) == []
        assert select_spatially_dispersed_records(recs, 28.0, 77.0, limit=-5) == []

    def test_fps_performance_benchmark(self):
        """FPS with N=200, limit=50 must complete well under 25ms."""
        import random
        rng = random.Random(42)
        records = [
            {
                "tower_id": f"T_{i:03d}",
                "latitude": 28.0 + rng.uniform(-0.05, 0.05),
                "longitude": 77.0 + rng.uniform(-0.05, 0.05),
                "range_m": 800.0,
                "radio": "4G",
            }
            for i in range(200)
        ]
        t0 = time.perf_counter()
        selected = select_spatially_dispersed_records(records, 28.0, 77.0, limit=50)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert len(selected) == 50
        assert elapsed_ms < 25.0, f"FPS exceeded runtime target: {elapsed_ms:.2f}ms"


# =====================================================================
# 3. Cache Resilience & Corruption Handling
# =====================================================================
class TestCacheResilienceAndCorruption:
    """Verifies cache behavior under corrupted files, expired TTL, and partial queries."""

    def test_load_cache_corrupted_json(self, tmp_path):
        """Corrupted JSON in cache file does not crash; load_cache gracefully returns None."""
        cache_file = tmp_path / "cache_corrupt.json"
        cache_file.write_text("{ this is malformed json", encoding="utf-8")

        # Mock get_cache_filepath to return our corrupt file
        with patch("data_service.get_cache_filepath", return_value=cache_file):
            result = load_cache("corrupt_bbox", max_age_seconds=3600, cache_dir=tmp_path)
            assert result is None
            fallback_res = load_cache_fallback("corrupt_bbox", cache_dir=tmp_path)
            assert fallback_res is None

    def test_load_cache_expired_ttl_vs_fallback(self, tmp_path):
        """Expired cache returns None for load_cache, but load_cache_fallback retrieves it."""
        bbox_str = "10.0,20.0,10.1,20.1"
        data = [{"tower_id": "T1", "latitude": 10.05, "longitude": 20.05, "range_m": 800.0}]
        filepath = save_cache(bbox_str, data, is_partial=False, cache_dir=tmp_path)
        assert filepath is not None and filepath.exists()

        # Check with max_age_seconds = 0.0001 (already expired)
        time.sleep(0.01)
        fresh = load_cache(bbox_str, max_age_seconds=0.001, cache_dir=tmp_path)
        assert fresh is None

        # Fallback loads regardless of age
        fallback = load_cache_fallback(bbox_str, cache_dir=tmp_path)
        assert fallback is not None
        assert len(fallback["records"]) == 1
        assert fallback["records"][0]["tower_id"] == "T1"

    def test_save_and_load_partial_cache(self, tmp_path):
        """Partial area query cache stores and preserves the is_partial flag."""
        bbox_str = "12.0,77.0,12.1,77.1"
        data = [{"tower_id": "T_PARTIAL", "latitude": 12.05, "longitude": 77.05, "range_m": 800.0}]
        save_cache(bbox_str, data, is_partial=True, cache_dir=tmp_path)

        cached = load_cache(bbox_str, max_age_seconds=86400, cache_dir=tmp_path)
        assert cached is not None
        assert cached["is_partial"] is True
        assert cached["record_count"] == 1


# =====================================================================
# 4. Exact DSatur BnB Solver Edge Cases & Deep Branches
# =====================================================================
class TestExactDSaturBnBAdversarialBranches:
    """Stress-testing the bounded exact DSatur Branch-and-Bound algorithm."""

    def test_exact_solver_empty_graph(self):
        """Empty graph (0 nodes) produces chromatic number 0 with status 'exact_optimal'."""
        G = nx.Graph()
        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["color_count"] == 0
        assert res["chi_heuristic"] == 0
        assert res["validation"]["is_valid"] is True

    def test_exact_solver_exceeds_max_nodes(self):
        """Graph with N > max_nodes skips exact solver and returns DSatur heuristic with 'skipped_size_limit'."""
        G = nx.cycle_graph(26)
        res = color_exact_dsatur_bnb(G, max_nodes=25)
        assert res["status"] == "skipped_size_limit"
        assert res["proven_optimal"] is False
        assert res["color_count"] == 2  # even cycle has chromatic number 2
        assert res["validation"]["is_valid"] is True

    def test_exact_solver_ub_equals_lb_fast_path(self):
        """When initial DSatur UB equals clique lower bound LB, solver returns immediately without branching."""
        # Complete graph K_6: omega = 6, chi = 6
        G = nx.complete_graph(6)
        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["lower_bound"] == 6
        assert res["upper_bound"] == 6
        assert res["color_count"] == 6
        assert res["validation"]["is_valid"] is True

    def test_exact_solver_tight_timeout_triggers_timeout_status(self):
        """On a graph where chi > omega requiring branching, setting an infinitesimal timeout triggers 'timeout'."""
        # Grötzsch graph: 11 vertices, 20 edges, triangle-free (omega = 2), but chromatic number chi = 4.
        # This forces the BnB tree to branch because LB(omega)=2 < UB=4.
        # With timeout_sec=1e-6s, the deadline will expire during branch expansion.
        G = nx.mycielski_graph(4)  # Grötzsch graph (11 nodes, 20 edges, chi=4, omega=2)
        res = color_exact_dsatur_bnb(G, timeout_sec=0.000001)

        # It must either timeout or finish if exceedingly fast, but if it timed out:
        if res["status"] == "timeout":
            assert res["proven_optimal"] is False
            assert "exceeded timeout" in res["message"]
            assert res["validation"]["is_valid"] is True
            assert res["color_count"] >= 2
        else:
            # If it managed to solve in <1 microsecond, it must be optimal
            assert res["status"] == "exact_optimal"
            assert res["color_count"] == 4

    def test_exact_solver_pre_expired_deadline(self):
        """Setting timeout_sec = 0.0 or negative immediately hits the timeout branch before branching."""
        # Graph with LB < UB: Mycielskian of C_5 (Grötzsch graph)
        G = nx.mycielski_graph(4)
        res = color_exact_dsatur_bnb(G, timeout_sec=0.0)
        assert res["status"] == "timeout"
        assert res["proven_optimal"] is False
        assert res["validation"]["is_valid"] is True

    def test_exact_solver_non_integer_and_string_node_labels(self):
        """Graph with string node labels, tuple labels, and negative integers executes without error."""
        G = nx.Graph()
        nodes = ["mast_alpha", "mast_beta", "mast_gamma", ("site", 1), ("site", 2), -42]
        G.add_nodes_from(nodes)
        # Add edges in a cycle: mast_alpha - mast_beta - mast_gamma - (site, 1) - (site, 2) - -42 - mast_alpha
        for i in range(len(nodes)):
            G.add_edge(nodes[i], nodes[(i + 1) % len(nodes)], distance_m=500.0, threshold_m=1000.0)

        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["color_count"] == 2  # 6-cycle is bipartite -> chi = 2
        assert res["validation"]["is_valid"] is True
        # Verify all nodes received colors
        for n in nodes:
            assert n in res["coloring"]


# =====================================================================
# 5. Graph Topologies & Disconnected Components
# =====================================================================
class TestGraphTopologiesAndDisconnectedComponents:
    """Testing multi-component graphs, isolated nodes, and standard families."""

    def test_completely_disconnected_graph_isolated_vertices(self):
        """Graph with N isolated nodes (E=0) has density 0, chi=1, and all nodes colored with channel 0."""
        G = nx.Graph()
        for i in range(10):
            G.add_node(f"node_{i}", latitude=28.0 + i * 0.1, longitude=77.0, range_m=500.0, radio="4G")

        metrics = get_graph_metrics(G)
        assert metrics["edge_count"] == 0
        assert metrics["density"] == 0.0
        assert metrics["connected_components"] == 10
        assert metrics["clique_lower_bound"] == 1
        assert metrics["brooks_upper_bound"] == 1

        dsatur_res = color_dsatur(G)
        assert dsatur_res["color_count"] == 1
        assert dsatur_res["validation"]["is_valid"] is True

        wp_res = color_welsh_powell(G)
        assert wp_res["color_count"] == 1
        assert wp_res["validation"]["is_valid"] is True

    def test_multiple_disconnected_subgraphs_with_heterogeneous_densities(self):
        """Graph composed of K_3 (triangle), K_2 (edge), and K_1 (isolated node) colors correctly with chi=3."""
        G = nx.Graph()
        # Component 1: Triangle (nodes A, B, C)
        G.add_edge("A", "B", distance_m=100.0, threshold_m=200.0)
        G.add_edge("B", "C", distance_m=100.0, threshold_m=200.0)
        G.add_edge("A", "C", distance_m=100.0, threshold_m=200.0)

        # Component 2: Isolated edge (nodes D, E)
        G.add_edge("D", "E", distance_m=100.0, threshold_m=200.0)

        # Component 3: Isolated node F
        G.add_node("F")

        # Color with DSatur and Welsh-Powell
        dsatur_res = color_dsatur(G)
        wp_res = color_welsh_powell(G)

        assert dsatur_res["color_count"] == 3
        assert dsatur_res["validation"]["is_valid"] is True
        assert wp_res["color_count"] == 3
        assert wp_res["validation"]["is_valid"] is True

        # Validation must inspect all 4 edges
        assert dsatur_res["validation"]["edges_inspected"] == 4
        assert wp_res["validation"]["edges_inspected"] == 4

    def test_wheel_graphs_odd_and_even_cycles(self):
        """Wheel graph W_n: center hub connected to cycle C_{n-1}. Odd C has chi=4, Even C has chi=3."""
        # W_6: hub + 5-cycle (odd cycle) -> chi = 4
        W6 = nx.wheel_graph(6)
        # add dummy edge attributes
        for u, v in W6.edges():
            W6[u][v]["distance_m"] = 100.0
            W6[u][v]["threshold_m"] = 200.0

        res_w6 = color_dsatur(W6)
        assert res_w6["color_count"] == 4
        assert res_w6["validation"]["is_valid"] is True

        # W_7: hub + 6-cycle (even cycle) -> chi = 3
        W7 = nx.wheel_graph(7)
        for u, v in W7.edges():
            W7[u][v]["distance_m"] = 100.0
            W7[u][v]["threshold_m"] = 200.0

        res_w7 = color_dsatur(W7)
        assert res_w7["color_count"] == 3
        assert res_w7["validation"]["is_valid"] is True

    def test_optimize_graph_frequencies_best_algorithm_selection(self):
        """optimize_graph_frequencies runs DSatur, WP, and Exact BnB, selecting lowest color count."""
        # Create a graph where exact or DSatur beats or ties WP
        G = nx.cycle_graph(5)
        for u, v in G.edges():
            G[u][v]["distance_m"] = 100.0
            G[u][v]["threshold_m"] = 200.0
        for n in G.nodes():
            G.nodes[n]["latitude"] = 28.0
            G.nodes[n]["longitude"] = 77.0
            G.nodes[n]["range_m"] = 800.0

        opt = optimize_graph_frequencies(G, run_exact=True)
        assert opt["best_algorithm"] in ("DSatur", "Welsh-Powell", "exact_dsatur_bnb")
        assert opt["dsatur"]["validation"]["is_valid"] is True
        assert opt["welsh_powell"]["validation"]["is_valid"] is True
        assert opt["exact"]["validation"]["is_valid"] is True


# =====================================================================
# 6. Mast Consolidation & Aggregation Edge Cases
# =====================================================================
class TestMastAggregationEdgeCases:
    """Adversarial testing of <=2m co-located mast clustering in data_service."""

    def test_transitive_mast_clustering(self):
        """Transitive co-location: A is 1.5m from B, B is 1.5m from C, but A is 3.0m from C. All cluster into 1 site."""
        # Place on Equator: 1 degree lon ≈ 111,139m.
        # 1.5m ≈ 0.0000135 degrees
        d_deg = 1.5 / 111_139.0
        cells = [
            {"tower_id": "T_A", "latitude": 0.0, "longitude": 0.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T_B", "latitude": 0.0, "longitude": d_deg, "range_m": 1200.0, "radio": "4G"},
            {"tower_id": "T_C", "latitude": 0.0, "longitude": 2 * d_deg, "range_m": 600.0, "radio": "5G"},
        ]

        # Verify distance A to C is ~3m
        dist_ac = haversine_distance(0.0, 0.0, 0.0, 2 * d_deg)
        assert dist_ac > 2.0

        updated_cells, sites = group_cells_into_sites(cells, distance_threshold_m=2.0)
        assert len(sites) == 1
        assert sites[0]["sector_count"] == 3
        assert set(sites[0]["sectors"]) == {"T_A", "T_B", "T_C"}

        # Consolidated tower retains maximum range (1200m) and distinct radios
        aggregated = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(aggregated) == 1
        assert aggregated[0]["range_m"] == 1200.0
        assert set(aggregated[0]["radios"]) == {"4G", "5G"}
        assert aggregated[0]["radio"] == "5G"  # 5G prioritized in rep_radio

    def test_exact_distance_threshold_boundary_2m(self):
        """Distance <= 2.0m clusters; distance > 2.0m does not cluster."""
        # Place along latitude meridian where 1 degree is exactly 111,139m everywhere
        d_lat1 = 1.8 / 111_139.0  # 1.8m <= 2.0m
        d_lat2 = 2.2 / 111_139.0  # 2.2m > 2.0m

        cells = [
            {"tower_id": "T1", "latitude": 28.0, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T2", "latitude": 28.0 + d_lat1, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T3", "latitude": 29.0, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
            {"tower_id": "T4", "latitude": 29.0 + d_lat2, "longitude": 77.0, "range_m": 800.0, "radio": "4G"},
        ]

        _, sites = group_cells_into_sites(cells, distance_threshold_m=2.0)
        # T1 & T2 should cluster into 1 site (sector_count=2)
        # T3 & T4 should be 2 separate sites (each sector_count=1)
        assert len(sites) == 3
        counts = sorted([s["sector_count"] for s in sites])
        assert counts == [1, 1, 2]

    def test_aggregation_empty_input(self):
        """Empty input to group_cells_into_sites and aggregate_towers_within_distance returns empty structures."""
        c, s = group_cells_into_sites([])
        assert c == []
        assert s == []
        agg = aggregate_towers_within_distance([])
        assert agg == []


# =====================================================================
# 7. Independent Validator Adversarial Stress Checks
# =====================================================================
class TestIndependentValidatorAdversarialChecks:
    """Stress tests verifying that validate_coloring detects all types of injected errors."""

    def test_validator_detects_deliberate_boundary_violation(self):
        """An edge where distance_m > threshold_m + 1e-6 must be reported in boundary_violations."""
        G = nx.Graph()
        G.add_edge("u", "v", distance_m=2500.0, threshold_m=1600.0)
        coloring = {"u": 0, "v": 1}

        res = validate_coloring(G, coloring)
        assert res["is_valid"] is False
        assert res["boundary_violation_count"] == 1
        assert len(res["boundary_violations"]) == 1
        assert res["boundary_violations"][0]["source"] == "u"
        assert res["boundary_violations"][0]["distance_m"] == 2500.0

    def test_validator_detects_zero_distance_edges(self):
        """An edge with distance_m < 1e-6 must be recorded in zero_distance_edges."""
        G = nx.Graph()
        G.add_edge("u", "v", distance_m=0.0, threshold_m=1600.0)
        coloring = {"u": 0, "v": 1}

        res = validate_coloring(G, coloring)
        # Zero-distance edges are diagnostic flags; coloring itself is valid if colors differ and no boundary violation
        assert res["zero_distance_count"] == 1
        assert len(res["zero_distance_edges"]) == 1
        assert res["is_valid"] is True

    def test_validator_detects_boolean_colors_as_invalid(self):
        """Colors assigned as Python boolean True/False (which are ints in Python) must be rejected."""
        G = nx.Graph()
        G.add_edge("u", "v", distance_m=500.0, threshold_m=1600.0)
        # True is instance of int in Python, but validate_coloring explicitly guards: `isinstance(val, bool)`
        coloring = {"u": True, "v": False}

        res = validate_coloring(G, coloring)
        assert res["is_valid"] is False
        assert res["missing_count"] == 2
        assert set(res["missing_nodes"]) == {"u", "v"}

    def test_validator_detects_negative_and_none_colors(self):
        """Colors assigned as negative integers or None must be flagged as missing/invalid."""
        G = nx.Graph()
        G.add_edge("u", "v", distance_m=500.0, threshold_m=1600.0)
        coloring = {"u": -1, "v": None}

        res = validate_coloring(G, coloring)
        assert res["is_valid"] is False
        assert res["missing_count"] == 2


# =====================================================================
# 8. Schema Invariant Enforcement & Radio Query Parsing
# =====================================================================
class TestAppAndSchemasAdversarialValidation:
    """Stress testing Pydantic V2 schemas and FastAPI query parameter parsers."""

    def test_parse_radio_query_valid_variants(self):
        """parse_radio_query handles comma-separated, repeated, case-insensitive, and alias radio queries."""
        assert parse_radio_query(None) == ["4G", "5G"]
        assert parse_radio_query("4G") == ["4G"]
        assert parse_radio_query("5g") == ["5G"]
        assert parse_radio_query("lte,nr") == ["4G", "5G"]
        assert parse_radio_query(["4G", "5G"]) == ["4G", "5G"]
        assert parse_radio_query(["LTE", "EUTRAN"]) == ["4G"]

    def test_parse_radio_query_rejects_legacy_radios(self):
        """parse_radio_query raises HTTP 400 when 2G/3G/GSM/UMTS is requested."""
        with pytest.raises(HTTPException) as exc_info:
            parse_radio_query("2G")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info2:
            parse_radio_query("GSM,3G")
        assert exc_info2.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info3:
            parse_radio_query("")
        assert exc_info3.value.status_code == 400

    def test_accounting_metadata_invariant_enforcement(self):
        """AccountingMetadata raises ValidationError if mathematical invariants are violated."""
        # 1. available < eligible
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=10,
                eligible_count=15,
                selected_count=10,
                excluded_count=0,
                excluded_radio_count=-5,
                excluded_limit_count=5,
            )

        # 2. eligible < selected
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=20,
                eligible_count=10,
                selected_count=15,
                excluded_count=5,
                excluded_radio_count=10,
                excluded_limit_count=-5,
            )

        # 3. excluded_radio_count mismatch
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=30,
                eligible_count=20,
                selected_count=15,
                excluded_count=15,
                excluded_radio_count=5,  # should be 10!
                excluded_limit_count=5,
            )

        # 4. Valid accounting satisfies all invariants
        acc = AccountingMetadata(
            available_count=50,
            eligible_count=40,
            selected_count=25,
            excluded_count=25,
            excluded_radio_count=10,
            excluded_limit_count=15,
        )
        assert acc.excluded_count == acc.excluded_radio_count + acc.excluded_limit_count

    def test_site_entity_sector_count_validation(self):
        """SiteEntity raises ValidationError when sector_count does not equal len(sectors)."""
        with pytest.raises(ValidationError):
            SiteEntity(
                site_id="SITE_1",
                latitude=28.5,
                longitude=77.2,
                sector_count=3,
                sectors=["T1", "T2"],  # len is 2, mismatch!
                radios=["4G"],
            )

    def test_cell_record_rejects_legacy_radio(self):
        """CellRecord Pydantic validator strictly rejects 2G/3G/GSM/UMTS."""
        with pytest.raises(ValidationError):
            CellRecord(
                tower_id="GSM_1",
                cell_id=101,
                radio="2G",
                latitude=28.5,
                longitude=77.2,
            )

        with pytest.raises(ValidationError):
            CellRecord(
                tower_id="UMTS_1",
                cell_id=102,
                radio="3G",
                latitude=28.5,
                longitude=77.2,
            )

        # 4G and 5G must pass cleanly
        c4 = CellRecord(tower_id="T_4G", cell_id=1, radio="4G", latitude=28.5, longitude=77.2)
        assert c4.radio == "4G"
        c5 = CellRecord(tower_id="T_5G", cell_id=2, radio="5G NR", latitude=28.5, longitude=77.2)
        assert c5.radio == "5G"
