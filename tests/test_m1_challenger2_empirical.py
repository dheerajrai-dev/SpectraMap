"""
tests/test_m1_challenger2_empirical.py

Empirical Challenge Test Suite for Milestone 1:
1. Strict 4G/5G filtering: attempt to inject 2G/3G/GSM/UMTS/CDMA via query params,
   JSON payloads, raw dicts, and verify they are rejected.
2. Deterministic FPS sampling: run FPS on shuffled orderings of the same tower pool
   and verify 100% identical selection sequence across permutations.
3. Accounting metadata invariants: verify available >= eligible >= selected >= 0
   and excluded == excluded_radio + excluded_limit across random configurations.
4. Dual solvers invariance: verify DSatur and Welsh-Powell produce valid colorings
   on the exact same graph representation without modifying the input graph.
"""

import copy
import math
import random
from typing import Any
import networkx as nx
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app import app, parse_radio_query, _process_tower_records
from data_service import (
    normalize_radio_type,
    filter_records_by_radio,
    select_spatially_dispersed_records,
    haversine_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    validate_coloring,
    optimize_graph_frequencies,
    get_graph_metrics,
)
from schemas import (
    CellRecord,
    AccountingMetadata,
    GraphBuildRequest,
    OptimizeRequest,
    CompareRequest,
)


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# CHALLENGE 1: Strict 4G/5G Filtering & Legacy Rejection
# ==============================================================================

FORBIDDEN_LEGACY_RADIOS = [
    "2G",
    "3G",
    "GSM",
    "gsm",
    "UMTS",
    "umts",
    "CDMA",
    "cdma",
    "GPRS",
    "gprs",
    "EDGE",
    "edge",
    "WCDMA",
    "wcdma",
    "HSDPA",
    "HSPA",
    "HSPA+",
    "EVDO",
    "1xRTT",
    "WIFI",
    "WiFi",
    "Wi-Fi",
    "satellite",
    "BLUETOOTH",
    "unknown",
    "FOOBAR",
]


class TestChallenge1StrictFiltering:
    """Empirical challenge tests for strict modern cellular filtering (4G/5G only)."""

    @pytest.mark.parametrize("legacy_radio", FORBIDDEN_LEGACY_RADIOS)
    def test_normalize_radio_type_strictly_rejects_legacy(self, legacy_radio):
        """normalize_radio_type must return None for all legacy or unrecognized technologies."""
        assert normalize_radio_type(legacy_radio) is None

    @pytest.mark.parametrize("radio_str", ["", "   ", None, 12345, [], {}])
    def test_normalize_radio_type_rejects_empty_and_non_strings(self, radio_str):
        """normalize_radio_type must return None for empty or malformed inputs."""
        assert normalize_radio_type(radio_str) is None

    @pytest.mark.parametrize(
        "valid_input,expected",
        [
            ("4G", "4G"),
            ("4g", "4G"),
            ("LTE", "4G"),
            ("lte", "4G"),
            ("4G LTE", "4G"),
            ("4G-LTE", "4G"),
            ("4GLTE", "4G"),
            ("EUTRAN", "4G"),
            ("E-UTRAN", "4G"),
            ("LTE-M", "4G"),
            ("5G", "5G"),
            ("5g", "5G"),
            ("NR", "5G"),
            ("nr", "5G"),
            ("5G NR", "5G"),
            ("5G-NR", "5G"),
            ("5GNR", "5G"),
        ],
    )
    def test_normalize_radio_type_accepts_valid_modern(self, valid_input, expected):
        """normalize_radio_type accepts valid 4G/5G tokens and synonyms."""
        assert normalize_radio_type(valid_input) == expected

    @pytest.mark.parametrize("legacy_radio", FORBIDDEN_LEGACY_RADIOS)
    def test_parse_radio_query_rejects_legacy(self, legacy_radio):
        """parse_radio_query must raise HTTP 400 for any forbidden radio."""
        with pytest.raises(Exception) as exc_info:
            parse_radio_query(legacy_radio)
        assert exc_info.value.status_code == 400
        assert "Invalid radio technology" in exc_info.value.detail or "Allowed values: 4G, 5G" in exc_info.value.detail

    @pytest.mark.parametrize(
        "mixed_query",
        [
            "4G,2G",
            "5G,GSM",
            "4G,3G,5G",
            "LTE,UMTS",
            "4G,CDMA",
            "2G,3G",
            "4G,WIFI",
        ],
    )
    def test_parse_radio_query_rejects_mixed_queries_containing_legacy(self, mixed_query):
        """parse_radio_query must reject queries if ANY token is legacy/invalid."""
        with pytest.raises(Exception) as exc_info:
            parse_radio_query(mixed_query)
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize("empty_query", ["", "   ", ",,,", " , , "])
    def test_parse_radio_query_rejects_empty(self, empty_query):
        """parse_radio_query must raise HTTP 400 when no valid radios are provided."""
        with pytest.raises(Exception) as exc_info:
            parse_radio_query(empty_query)
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize("legacy_radio", ["2G", "3G", "GSM", "UMTS", "CDMA", "WIFI"])
    def test_endpoints_query_params_reject_legacy_with_http_400(self, client, legacy_radio):
        """GET /api/towers and GET /api/cells must reject legacy radios with HTTP 400."""
        for endpoint in ["/api/towers", "/api/cells"]:
            resp = client.get(f"{endpoint}?lat=28.6&lon=77.2&radios={legacy_radio}")
            assert resp.status_code == 400, f"Expected 400 for {endpoint}?radios={legacy_radio}, got {resp.status_code}"
            data = resp.json()
            assert "Invalid radio technology" in data.get("detail", "")

    @pytest.mark.parametrize("legacy_radio", ["2G", "3G", "GSM", "UMTS", "CDMA", "WIFI"])
    def test_pydantic_cell_record_rejects_legacy_raw_dict(self, legacy_radio):
        """CellRecord Pydantic model must reject raw dicts containing legacy radio."""
        raw_dict = {
            "tower_id": f"TOWER_{legacy_radio}_1",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "range_m": 800.0,
            "radio": legacy_radio,
        }
        with pytest.raises(ValidationError) as exc_info:
            CellRecord.model_validate(raw_dict)
        assert "Invalid radio technology" in str(exc_info.value)

    @pytest.mark.parametrize("legacy_radio", ["2G", "3G", "GSM", "UMTS", "CDMA"])
    def test_post_endpoints_reject_legacy_in_json_payload(self, client, legacy_radio):
        """
        POST /api/graph/build, /api/optimize, and /api/compare must reject
        JSON payloads containing legacy radio records with HTTP 422 Unprocessable Entity.
        """
        payload_with_legacy = {
            "cells": [
                {
                    "tower_id": "4G_VALID_1",
                    "latitude": 28.6100,
                    "longitude": 77.2000,
                    "range_m": 800.0,
                    "radio": "4G",
                },
                {
                    "tower_id": f"LEGACY_{legacy_radio}_1",
                    "latitude": 28.6150,
                    "longitude": 77.2050,
                    "range_m": 800.0,
                    "radio": legacy_radio,
                },
            ]
        }

        for path in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            resp = client.post(path, json=payload_with_legacy)
            assert resp.status_code == 422, f"Expected 422 for {path} with {legacy_radio}, got {resp.status_code}"


# ==============================================================================
# CHALLENGE 2: Deterministic FPS Sampling Sequence Invariance
# ==============================================================================

class TestChallenge2DeterministicFPS:
    """
    Adversarial verification of Farthest Point Sampling:
    Shuffling the input list must produce 100% identical selection sequence.
    """

    @pytest.mark.parametrize("pool_size,limit", [(15, 5), (30, 10), (60, 25), (100, 50), (200, 50)])
    def test_fps_sequence_identical_across_shuffled_permutations(self, pool_size, limit):
        """
        Verify that under N distinct random permutations of the input tower pool,
        FPS produces the exact same ordered sequence of tower IDs.
        """
        rng = random.Random(1337)
        center_lat = 28.6139
        center_lon = 77.2090

        # Construct distinct spatial candidate towers
        pool: list[dict[str, Any]] = []
        for i in range(pool_size):
            # Deterministic distinct coordinates
            lat = center_lat + rng.uniform(-0.04, 0.04)
            lon = center_lon + rng.uniform(-0.04, 0.04)
            pool.append({
                "tower_id": f"SITE_{i:04d}",
                "latitude": lat,
                "longitude": lon,
                "lat": lat,
                "lon": lon,
                "range_m": 800.0,
                "radio": "4G" if i % 2 == 0 else "5G",
            })

        # Baseline run
        base_result = select_spatially_dispersed_records(pool, center_lat, center_lon, limit=limit)
        base_sequence = [r["tower_id"] for r in base_result]
        assert len(base_sequence) == min(pool_size, limit)

        # Run 25 random shuffles
        for shuffle_idx in range(25):
            shuffled = list(pool)
            rng.shuffle(shuffled)
            perm_result = select_spatially_dispersed_records(shuffled, center_lat, center_lon, limit=limit)
            perm_sequence = [r["tower_id"] for r in perm_result]

            assert perm_sequence == base_sequence, (
                f"FPS sequence mismatch on shuffle {shuffle_idx} for pool_size={pool_size}, limit={limit}!\n"
                f"Base: {base_sequence[:10]}...\n"
                f"Perm: {perm_sequence[:10]}..."
            )

    def test_fps_deterministic_tie_breaking_co_located(self):
        """
        Adversarial test: all candidates are exactly co-located at distance 0 from each other.
        FPS must break distance ties deterministically by ascending tower_id.
        """
        center_lat = 28.6000
        center_lon = 77.2000

        # 10 co-located candidates with unordered tower IDs
        ids = ["T_ZULU", "T_ALPHA", "T_MIKE", "T_BRAVO", "T_CHARLIE", "T_XRAY", "T_DELTA", "T_ECHO", "T_FOXTROT", "T_GOLF"]
        pool = [
            {
                "tower_id": tid,
                "latitude": center_lat,
                "longitude": center_lon,
                "range_m": 500.0,
                "radio": "5G",
            }
            for tid in ids
        ]

        expected_order = sorted(ids)[:5]

        # Test across 20 shuffles
        rng = random.Random(42)
        for _ in range(20):
            shuffled = list(pool)
            rng.shuffle(shuffled)
            result = select_spatially_dispersed_records(shuffled, center_lat, center_lon, limit=5)
            selected_ids = [r["tower_id"] for r in result]
            assert selected_ids == expected_order

    def test_fps_concentric_equidistant_tie_breaking(self):
        """
        Adversarial test: Candidates on a circle equidistant from center.
        Tie-breaking must strictly follow ascending tower_id.
        """
        center_lat = 0.0
        center_lon = 0.0
        # 8 points at identical distance R on a circle
        r_deg = 0.01
        pool = []
        for i in range(8):
            angle = i * (2 * math.pi / 8)
            lat = r_deg * math.cos(angle)
            lon = r_deg * math.sin(angle)
            pool.append({
                "tower_id": f"TOWER_{chr(65 + i)}",  # TOWER_A .. TOWER_H
                "latitude": lat,
                "longitude": lon,
                "range_m": 800.0,
                "radio": "4G",
            })

        base_res = select_spatially_dispersed_records(pool, center_lat, center_lon, limit=4)
        base_seq = [r["tower_id"] for r in base_res]

        rng = random.Random(999)
        for _ in range(15):
            shuffled = list(pool)
            rng.shuffle(shuffled)
            perm_res = select_spatially_dispersed_records(shuffled, center_lat, center_lon, limit=4)
            assert [r["tower_id"] for r in perm_res] == base_seq

    @pytest.mark.parametrize("limit", [0, -1, -50])
    def test_fps_zero_or_negative_limit(self, limit):
        """FPS with limit <= 0 returns empty list."""
        records = [{"tower_id": "T1", "latitude": 28.0, "longitude": 77.0, "range_m": 800.0, "radio": "4G"}]
        assert select_spatially_dispersed_records(records, 28.0, 77.0, limit=limit) == []

    def test_fps_empty_pool(self):
        """FPS on empty pool returns empty list."""
        assert select_spatially_dispersed_records([], 28.0, 77.0, limit=10) == []


# ==============================================================================
# CHALLENGE 3: Accounting Metadata Invariants
# ==============================================================================

class TestChallenge3AccountingInvariants:
    """
    Stress-test mathematical invariants:
      available_count >= eligible_count >= selected_count >= 0
      excluded_count == excluded_radio_count + excluded_limit_count
      excluded_radio_count == available_count - eligible_count
      excluded_limit_count == eligible_count - selected_count
      excluded_count == available_count - selected_count
    """

    def test_accounting_metadata_validator_rejects_violation(self):
        """AccountingMetadata must raise ValidationError if any invariant is violated."""
        # Violation: available < eligible
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=10,
                eligible_count=15,
                selected_count=10,
                excluded_count=0,
                excluded_radio_count=-5,
                excluded_limit_count=5,
            )

        # Violation: eligible < selected
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=20,
                eligible_count=10,
                selected_count=15,
                excluded_count=5,
                excluded_radio_count=10,
                excluded_limit_count=-5,
            )

        # Violation: excluded != excluded_radio + excluded_limit
        with pytest.raises(ValidationError):
            AccountingMetadata(
                available_count=50,
                eligible_count=40,
                selected_count=30,
                excluded_count=25,  # Should be 20
                excluded_radio_count=10,
                excluded_limit_count=10,
            )

    @pytest.mark.parametrize("trial", range(50))
    def test_monte_carlo_accounting_invariants(self, trial):
        """
        Generate 50 random synthetic datasets with arbitrary radio mixes and limits,
        and verify all accounting invariants hold strictly across the pipeline.
        """
        rng = random.Random(trial + 1000)
        n_records = rng.randint(0, 150)
        radios_choices = ["2G", "3G", "GSM", "UMTS", "4G", "LTE", "5G", "NR"]
        active_radios = ["4G", "5G"]
        limit = rng.randint(10, 100)

        center_lat = 28.6139
        center_lon = 77.2090

        cells: list[dict[str, Any]] = []
        for i in range(n_records):
            r = rng.choice(radios_choices)
            cells.append({
                "tower_id": f"T_{trial}_{i}",
                "latitude": center_lat + rng.uniform(-0.02, 0.02),
                "longitude": center_lon + rng.uniform(-0.02, 0.02),
                "range_m": 800.0 if "4G" in r or "LTE" in r else 500.0,
                "radio": r,
                "cell_id": i + 1,
            })

        # Process through tower processing logic
        result = _process_tower_records(
            cells=cells,
            center_lat=center_lat,
            center_lon=center_lon,
            query_radius=1500.0,
            active_radios=active_radios,
            limit=limit,
            warnings=[],
            is_cached=False,
            aggregate_2m=False,
        )

        acc = result["accounting"]
        avail = acc["available_count"]
        elig = acc["eligible_count"]
        sel = acc["selected_count"]
        excl = acc["excluded_count"]
        excl_radio = acc["excluded_radio_count"]
        excl_limit = acc["excluded_limit_count"]

        # Invariant 1: Hierarchy
        assert avail >= elig >= sel >= 0, f"Hierarchy failed: {avail} >= {elig} >= {sel} >= 0"

        # Invariant 2: Additive Exclusion
        assert excl == excl_radio + excl_limit, f"Exclusion partition failed: {excl} != {excl_radio} + {excl_limit}"

        # Invariant 3: Radio filter partition
        assert excl_radio == avail - elig, f"Radio partition failed: {excl_radio} != {avail} - {elig}"

        # Invariant 4: Limit partition
        assert excl_limit == elig - sel, f"Limit partition failed: {excl_limit} != {elig} - {sel}"

        # Invariant 5: Total exclusion
        assert excl == avail - sel, f"Total exclusion failed: {excl} != {avail} - {sel}"

        # Validate through AccountingMetadata schema
        AccountingMetadata.model_validate(acc)

    def test_accounting_corner_cases(self):
        """Corner cases: zero records, all legacy, all modern."""
        center_lat = 28.6
        center_lon = 77.2

        # 1. Zero records
        res_zero = _process_tower_records(
            cells=[],
            center_lat=center_lat,
            center_lon=center_lon,
            query_radius=1000.0,
            active_radios=["4G", "5G"],
            limit=50,
            warnings=[],
            is_cached=False,
        )
        assert res_zero["accounting"] == {
            "available_count": 0,
            "eligible_count": 0,
            "selected_count": 0,
            "excluded_count": 0,
            "excluded_radio_count": 0,
            "excluded_limit_count": 0,
        }

        # 2. All legacy (100% excluded by radio)
        legacy_cells = [
            {"tower_id": f"GSM_{i}", "latitude": 28.6, "longitude": 77.2, "radio": "GSM", "range_m": 800.0}
            for i in range(25)
        ]
        res_legacy = _process_tower_records(
            cells=legacy_cells,
            center_lat=center_lat,
            center_lon=center_lon,
            query_radius=1000.0,
            active_radios=["4G", "5G"],
            limit=50,
            warnings=[],
            is_cached=False,
        )
        assert res_legacy["accounting"] == {
            "available_count": 25,
            "eligible_count": 0,
            "selected_count": 0,
            "excluded_count": 25,
            "excluded_radio_count": 25,
            "excluded_limit_count": 0,
        }


# ==============================================================================
# CHALLENGE 4: Dual Solvers Invariance & Input Graph Immutability
# ==============================================================================

class TestChallenge4DualSolversInvariance:
    """
    Adversarial verification of DSatur and Welsh-Powell:
    1. Both solvers produce valid colorings on the exact same graph representation.
    2. Solvers DO NOT mutate nodes, edges, or graph attributes of the input graph.
    3. Independent validator confirms 100% of edges have non-equal neighbor colors.
    """

    def _snapshot_graph(self, G: nx.Graph) -> dict[str, Any]:
        """Capture deep immutable snapshot of graph structure and attributes."""
        return {
            "nodes": copy.deepcopy(dict(G.nodes(data=True))),
            "edges": copy.deepcopy(list(G.edges(data=True))),
            "graph_attr": copy.deepcopy(dict(G.graph)),
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
        }

    def _assert_graph_unmodified(self, G: nx.Graph, snapshot: dict[str, Any], context: str):
        """Assert that graph G has not been mutated in any way."""
        assert G.number_of_nodes() == snapshot["node_count"], f"{context}: Node count modified"
        assert G.number_of_edges() == snapshot["edge_count"], f"{context}: Edge count modified"
        assert dict(G.nodes(data=True)) == snapshot["nodes"], f"{context}: Node attributes mutated"
        assert list(G.edges(data=True)) == snapshot["edges"], f"{context}: Edges or edge attributes mutated"
        assert dict(G.graph) == snapshot["graph_attr"], f"{context}: G.graph attributes mutated"

    def test_dual_solvers_empty_graph(self):
        """Both solvers handle empty graph (N=0) cleanly without mutation."""
        G = nx.Graph()
        snap = self._snapshot_graph(G)

        ds_res = color_dsatur(G)
        self._assert_graph_unmodified(G, snap, "color_dsatur(empty)")
        assert ds_res["color_count"] == 0
        assert ds_res["validation"]["is_valid"] is True

        wp_res = color_welsh_powell(G)
        self._assert_graph_unmodified(G, snap, "color_welsh_powell(empty)")
        assert wp_res["color_count"] == 0
        assert wp_res["validation"]["is_valid"] is True

    def test_dual_solvers_single_node(self):
        """Single node graph (N=1) colored with 1 color."""
        G = nx.Graph()
        G.add_node("N1", latitude=28.6, longitude=77.2, range_m=800.0, radio="4G")
        snap = self._snapshot_graph(G)

        ds_res = color_dsatur(G)
        self._assert_graph_unmodified(G, snap, "color_dsatur(N=1)")
        assert ds_res["color_count"] == 1
        assert ds_res["coloring"] == {"N1": 0}
        assert ds_res["validation"]["is_valid"] is True

        wp_res = color_welsh_powell(G)
        self._assert_graph_unmodified(G, snap, "color_welsh_powell(N=1)")
        assert wp_res["color_count"] == 1
        assert wp_res["coloring"] == {"N1": 0}
        assert wp_res["validation"]["is_valid"] is True

    @pytest.mark.parametrize(
        "graph_type,param",
        [
            ("complete", 12),
            ("cycle", 15),
            ("star", 20),
            ("bipartite", (8, 8)),
            ("erdos_renyi", (25, 0.3)),
            ("disconnected", 30),
        ],
    )
    def test_solvers_on_various_topologies(self, graph_type, param):
        """
        Verify DSatur and Welsh-Powell on diverse graph topologies:
        - Output is valid coloring (zero conflicts, zero missing nodes).
        - Solvers do not mutate the input graph.
        """
        if graph_type == "complete":
            G = nx.complete_graph(param)
        elif graph_type == "cycle":
            G = nx.cycle_graph(param)
        elif graph_type == "star":
            G = nx.star_graph(param)
        elif graph_type == "bipartite":
            n1, n2 = param
            G = nx.complete_bipartite_graph(n1, n2)
        elif graph_type == "erdos_renyi":
            n, p = param
            G = nx.erdos_renyi_graph(n, p, seed=42)
        elif graph_type == "disconnected":
            # 3 disconnected components of 10 nodes each
            G = nx.disjoint_union(nx.cycle_graph(10), nx.complete_graph(10))
            G = nx.disjoint_union(G, nx.path_graph(10))

        # Attach standard node attributes
        for n in G.nodes():
            G.nodes[n]["latitude"] = 28.6
            G.nodes[n]["longitude"] = 77.2
            G.nodes[n]["range_m"] = 800.0
            G.nodes[n]["radio"] = "4G"

        snap = self._snapshot_graph(G)

        # 1. Run DSatur
        ds_res = color_dsatur(G)
        self._assert_graph_unmodified(G, snap, f"DSatur({graph_type})")
        val_ds = validate_coloring(G, ds_res["coloring"])
        assert val_ds["is_valid"] is True
        assert val_ds["conflict_count"] == 0
        assert val_ds["missing_count"] == 0

        # Check all edges independently
        for u, v in G.edges():
            assert ds_res["coloring"][u] != ds_res["coloring"][v], f"Conflict on edge ({u}, {v}) in DSatur"

        # 2. Run Welsh-Powell on the EXACT SAME GRAPH
        wp_res = color_welsh_powell(G)
        self._assert_graph_unmodified(G, snap, f"Welsh-Powell({graph_type})")
        val_wp = validate_coloring(G, wp_res["coloring"])
        assert val_wp["is_valid"] is True
        assert val_wp["conflict_count"] == 0
        assert val_wp["missing_count"] == 0

        # Check all edges independently
        for u, v in G.edges():
            assert wp_res["coloring"][u] != wp_res["coloring"][v], f"Conflict on edge ({u}, {v}) in Welsh-Powell"

    def test_solvers_cellular_disc_graph(self):
        """
        Construct realistic spatial interference graph with 40 towers and verify
        both solvers operate invariantly without mutating graph.
        """
        rng = random.Random(777)
        cells = []
        center_lat, center_lon = 28.6139, 77.2090
        for i in range(40):
            lat = center_lat + rng.uniform(-0.015, 0.015)
            lon = center_lon + rng.uniform(-0.015, 0.015)
            rng_m = 800.0 if i % 2 == 0 else 500.0
            cells.append({
                "tower_id": f"SITE_{i:03d}",
                "latitude": lat,
                "longitude": lon,
                "range_m": rng_m,
                "radio": "4G" if i % 2 == 0 else "5G",
            })

        G = build_interference_graph(cells)
        assert G.number_of_nodes() == 40
        assert G.number_of_edges() > 0

        snap = self._snapshot_graph(G)

        # Run DSatur
        ds_res = color_dsatur(G)
        self._assert_graph_unmodified(G, snap, "Cellular DSatur")
        assert ds_res["validation"]["is_valid"] is True

        # Run Welsh-Powell
        wp_res = color_welsh_powell(G)
        self._assert_graph_unmodified(G, snap, "Cellular Welsh-Powell")
        assert wp_res["validation"]["is_valid"] is True

        # Run optimize_graph_frequencies (which executes both)
        opt_res = optimize_graph_frequencies(G, run_exact=False)
        self._assert_graph_unmodified(G, snap, "Cellular optimize_graph_frequencies")
        assert opt_res["dsatur"]["validation"]["is_valid"] is True
        assert opt_res["welsh_powell"]["validation"]["is_valid"] is True
        assert opt_res["best_algorithm"] in ("DSatur", "Welsh-Powell")

    def test_solvers_deterministic_across_node_reordering(self):
        """
        Adversarial test: Construct two isomorphic graphs with inverted node order.
        Verify DSatur and Welsh-Powell produce identical chromatic number and valid coloring.
        """
        edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A"), ("A", "C")]

        G1 = nx.Graph()
        for n in ["A", "B", "C", "D"]:
            G1.add_node(n, latitude=28.6, longitude=77.2, range_m=800.0, radio="4G")
        G1.add_edges_from(edges)

        G2 = nx.Graph()
        for n in ["D", "C", "B", "A"]:
            G2.add_node(n, latitude=28.6, longitude=77.2, range_m=800.0, radio="4G")
        G2.add_edges_from(edges)

        ds1 = color_dsatur(G1)
        ds2 = color_dsatur(G2)
        assert ds1["color_count"] == ds2["color_count"]
        assert ds1["coloring"] == ds2["coloring"]

        wp1 = color_welsh_powell(G1)
        wp2 = color_welsh_powell(G2)
        assert wp1["color_count"] == wp2["color_count"]
        assert wp1["coloring"] == wp2["coloring"]
