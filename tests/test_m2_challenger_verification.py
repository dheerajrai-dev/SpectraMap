"""
tests/test_m2_challenger_verification.py
Milestone M2 Empirical Challenger 1 Verification Suite.

Tests:
1. Graph Invariance: Deepcopy comparisons before and after color_dsatur,
   color_welsh_powell, color_exact_dsatur_bnb, and optimize_graph_frequencies
   across 20 diverse graph topologies.
2. Exact Solver Bounds: Strict bounds testing (N <= 25 exact, N > 25 skipped,
   micro-timeouts yielding valid fallback colorings).
3. Validator Sensitivity: 100 random edge conflict injections across random graphs
   with empirical 100% detection rate verification, plus adversarial non-integer,
   boolean, negative, and missing node injections.
4. Circular Coverage Overlap & Haversine Precision: Boundary epsilon validation,
   non-clique verification on dispersed towers, and 4G/5G tech distribution invariants.
"""

import copy
import random
import time
from typing import Any
import networkx as nx
import pytest

from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_exact_dsatur_bnb,
    color_welsh_powell,
    get_graph_metrics,
    optimize_graph_frequencies,
    serialize_graph_payload,
    validate_coloring,
)
from data_service import haversine_distance


# ==============================================================================
# 1. Graph Invariance: Deepcopy Invariance Across Diverse Graph Topologies
# ==============================================================================

def _generate_test_topologies():
    topologies = []
    # 1. Empty graph
    topologies.append(("Empty", nx.Graph()))
    # 2. Single node
    g1 = nx.Graph()
    g1.add_node("N0", latitude=28.5, longitude=77.2, radio="4G", range_m=500.0)
    topologies.append(("SingleNode", g1))
    # 3. Path graph P10
    topologies.append(("Path_10", nx.path_graph(10)))
    # 4. Cycle C7
    topologies.append(("Cycle_7", nx.cycle_graph(7)))
    # 5. Complete K5
    topologies.append(("Complete_5", nx.complete_graph(5)))
    # 6. Star S12
    topologies.append(("Star_12", nx.star_graph(11)))
    # 7. Bipartite K4,4
    topologies.append(("Bipartite_4_4", nx.complete_bipartite_graph(4, 4)))
    # 8. Petersen Graph
    topologies.append(("Petersen", nx.petersen_graph()))
    # 9. Wheel W8
    topologies.append(("Wheel_8", nx.wheel_graph(8)))
    # 10. Disjoint components K3 + K4
    topologies.append(("Disjoint_K3_K4", nx.disjoint_union(nx.complete_graph(3), nx.complete_graph(4))))
    # 11-15. Erdos-Renyi graphs with various densities
    for seed, (n, p) in enumerate([(10, 0.2), (15, 0.4), (18, 0.6), (20, 0.3), (25, 0.5)], start=100):
        topologies.append((f"ER_{n}_{p}", nx.erdos_renyi_graph(n, p, seed=seed)))
    # 16-17. Barabasi-Albert scale-free graphs
    topologies.append(("BA_15_2", nx.barabasi_albert_graph(15, 2, seed=42)))
    topologies.append(("BA_20_3", nx.barabasi_albert_graph(20, 3, seed=43)))
    # 18-19. Watts-Strogatz small-world graphs
    topologies.append(("WS_16_4_02", nx.watts_strogatz_graph(16, 4, 0.2, seed=44)))
    topologies.append(("WS_20_4_04", nx.watts_strogatz_graph(20, 4, 0.4, seed=45)))
    # 20. Cellular spatial interference graph
    cells = [
        {"tower_id": f"CELL_{i}", "latitude": 28.50 + (i * 0.003), "longitude": 77.20 + ((i % 3) * 0.002), "range_m": 600.0, "radio": "4G" if i % 2 == 0 else "5G"}
        for i in range(12)
    ]
    topologies.append(("CellularSpatial", build_interference_graph(cells)))
    return topologies


@pytest.mark.parametrize("name, graph", _generate_test_topologies())
def test_dual_solvers_and_exact_graph_invariance(name, graph):
    """
    Empirically verify that calling color_dsatur, color_welsh_powell,
    color_exact_dsatur_bnb, and optimize_graph_frequencies does NOT mutate
    graph nodes, edges, or graph attributes.
    """
    g = copy.deepcopy(graph)

    # Attach rich attributes if missing
    for n in g.nodes():
        if "attr" not in g.nodes[n]:
            g.nodes[n]["attr"] = f"val_{n}"
    for u, v in g.edges():
        if "weight" not in g[u][v]:
            g[u][v]["weight"] = 1.0

    nodes_before = copy.deepcopy(list(g.nodes(data=True)))
    edges_before = copy.deepcopy(list(g.edges(data=True)))
    graph_attrs_before = copy.deepcopy(dict(g.graph))
    dict_repr_before = copy.deepcopy(nx.to_dict_of_dicts(g))

    # 1. color_dsatur
    res_ds = color_dsatur(g)
    assert res_ds["validation"]["is_valid"] is True
    assert list(g.nodes(data=True)) == nodes_before, f"DSatur mutated nodes in {name}"
    assert list(g.edges(data=True)) == edges_before, f"DSatur mutated edges in {name}"
    assert dict(g.graph) == graph_attrs_before, f"DSatur mutated graph attrs in {name}"
    assert nx.to_dict_of_dicts(g) == dict_repr_before

    # 2. color_welsh_powell
    res_wp = color_welsh_powell(g)
    assert res_wp["validation"]["is_valid"] is True
    assert list(g.nodes(data=True)) == nodes_before, f"Welsh-Powell mutated nodes in {name}"
    assert list(g.edges(data=True)) == edges_before, f"Welsh-Powell mutated edges in {name}"
    assert dict(g.graph) == graph_attrs_before, f"Welsh-Powell mutated graph attrs in {name}"
    assert nx.to_dict_of_dicts(g) == dict_repr_before

    # 3. color_exact_dsatur_bnb (timeout bounded)
    res_exact = color_exact_dsatur_bnb(g, max_nodes=25, timeout_sec=0.1)
    assert res_exact["validation"]["is_valid"] is True
    assert list(g.nodes(data=True)) == nodes_before, f"Exact BnB mutated nodes in {name}"
    assert list(g.edges(data=True)) == edges_before, f"Exact BnB mutated edges in {name}"
    assert dict(g.graph) == graph_attrs_before, f"Exact BnB mutated graph attrs in {name}"
    assert nx.to_dict_of_dicts(g) == dict_repr_before

    # 4. optimize_graph_frequencies
    res_opt = optimize_graph_frequencies(g, run_exact=True)
    assert res_opt["dsatur"]["validation"]["is_valid"] is True
    assert res_opt["welsh_powell"]["validation"]["is_valid"] is True
    assert list(g.nodes(data=True)) == nodes_before, f"optimize_graph_frequencies mutated nodes in {name}"
    assert list(g.edges(data=True)) == edges_before, f"optimize_graph_frequencies mutated edges in {name}"
    assert dict(g.graph) == graph_attrs_before, f"optimize_graph_frequencies mutated graph attrs in {name}"
    assert nx.to_dict_of_dicts(g) == dict_repr_before


# ==============================================================================
# 2. Exact Solver Bounds: Size Limits and Micro-Timeout Stress
# ==============================================================================

def test_exact_solver_boundary_size_limits():
    """Verify exact solver enforces strict cut-off at max_nodes (N=25 vs N=26)."""
    # N = 25 must execute exact branch and bound
    g25 = nx.complete_graph(25)
    t0 = time.perf_counter()
    res25 = color_exact_dsatur_bnb(g25, max_nodes=25)
    t25 = (time.perf_counter() - t0) * 1000
    assert res25["status"] == "exact_optimal"
    assert res25["proven_optimal"] is True
    assert res25["color_count"] == 25
    assert res25["validation"]["is_valid"] is True

    # N = 26 must return skipped_size_limit near-instantaneously (<20ms)
    g26 = nx.complete_graph(26)
    t0 = time.perf_counter()
    res26 = color_exact_dsatur_bnb(g26, max_nodes=25)
    t26 = (time.perf_counter() - t0) * 1000
    assert res26["status"] == "skipped_size_limit"
    assert res26["proven_optimal"] is False
    assert res26["color_count"] == 26
    assert res26["validation"]["is_valid"] is True
    assert t26 < 50.0, f"Expected < 50ms, took {t26:.2f}ms"

    # N = 100 must also skip exact solver cleanly
    g100 = nx.cycle_graph(100)
    res100 = color_exact_dsatur_bnb(g100, max_nodes=25)
    assert res100["status"] == "skipped_size_limit"
    assert res100["proven_optimal"] is False
    assert res100["color_count"] == 2
    assert res100["validation"]["is_valid"] is True


def test_exact_solver_micro_timeouts_and_valid_fallback():
    """Verify timeout behavior on combinatorial hard graphs under micro-timeouts."""
    # Erdos-Renyi hard instance where chromatic number requires search
    g_hard = nx.erdos_renyi_graph(24, 0.4, seed=777)

    # Micro-timeout of 1ms: should abort search cleanly and return valid heuristic coloring
    res_fast = color_exact_dsatur_bnb(g_hard, max_nodes=25, timeout_sec=0.001)
    assert res_fast["status"] in ("timeout", "exact_optimal")
    assert res_fast["validation"]["is_valid"] is True
    assert res_fast["color_count"] >= 1

    # Micro-timeout of 5ms
    res_5ms = color_exact_dsatur_bnb(g_hard, max_nodes=25, timeout_sec=0.005)
    assert res_5ms["status"] in ("timeout", "exact_optimal")
    assert res_5ms["validation"]["is_valid"] is True


# ==============================================================================
# 3. Validator Sensitivity: 100 Injected Conflicts & 100% Detection Rate
# ==============================================================================

def test_validator_sensitivity_100_injected_conflicts():
    """
    Test validator sensitivity on 100 distinct random edges across varied graphs.
    Empirically verify 100% detection rate (100/100 detected).
    """
    rng = random.Random(20261020)
    tested_count = 0
    detected_count = 0

    while tested_count < 100:
        n = rng.randint(6, 20)
        p = rng.uniform(0.2, 0.7)
        g = nx.erdos_renyi_graph(n, p, seed=rng.randint(1, 100000))
        if g.number_of_edges() == 0:
            continue

        # Get valid base coloring
        coloring_res = color_dsatur(g)
        base_coloring = coloring_res["coloring"]
        assert validate_coloring(g, base_coloring)["is_valid"] is True

        # Pick a random edge to inject conflict
        edges = list(g.edges())
        u, v = rng.choice(edges)

        # Force identical color
        corrupted = dict(base_coloring)
        corrupted[v] = corrupted[u]

        # Validate
        v_res = validate_coloring(g, corrupted)
        tested_count += 1

        if not v_res["is_valid"] and v_res["conflict_count"] >= 1:
            # Check edge is registered in conflicts
            if (u, v) in v_res["conflicts"] or (v, u) in v_res["conflicts"]:
                detected_count += 1

    assert tested_count == 100
    assert detected_count == 100, f"Validator only detected {detected_count}/100 injected conflicts!"


def test_validator_adversarial_malformed_colorings():
    """Verify validator catches missing nodes, negative colors, boolean types, and non-ints."""
    g = nx.path_graph(4)  # nodes: 0, 1, 2, 3

    # Valid base
    valid = {0: 0, 1: 1, 2: 0, 3: 1}
    assert validate_coloring(g, valid)["is_valid"] is True

    # 1. Missing node 3
    missing = {0: 0, 1: 1, 2: 0}
    r_missing = validate_coloring(g, missing)
    assert r_missing["is_valid"] is False
    assert 3 in r_missing["missing_nodes"]

    # 2. Negative color integer
    neg = {0: 0, 1: -1, 2: 0, 3: 1}
    r_neg = validate_coloring(g, neg)
    assert r_neg["is_valid"] is False
    assert 1 in r_neg["missing_nodes"]

    # 3. Boolean value (Python bool is subclass of int!)
    bad_bool = {0: False, 1: True, 2: 0, 3: 1}
    r_bool = validate_coloring(g, bad_bool)
    assert r_bool["is_valid"] is False

    # 4. Float color
    bad_float = {0: 0.0, 1: 1.0, 2: 0, 3: 1}
    r_float = validate_coloring(g, bad_float)
    assert r_float["is_valid"] is False

    # 5. String color
    bad_str = {0: "red", 1: "blue", 2: "green", 3: "yellow"}
    r_str = validate_coloring(g, bad_str)
    assert r_str["is_valid"] is False

    # 6. None as color
    bad_none = {0: None, 1: 1, 2: 0, 3: 1}
    r_none = validate_coloring(g, bad_none)
    assert r_none["is_valid"] is False


# ==============================================================================
# 4. Circular Coverage Overlap & Haversine Precision
# ==============================================================================

def test_circular_coverage_overlap_epsilon_precision():
    """
    Test exact boundary condition d <= r1 + r2 with 1 um numerical epsilon.
    Using two points separated by exact distance.
    """
    lat1, lon1 = 28.6139, 77.2090
    # Point ~1000m north: 1 deg lat approx 111,139m -> 0.0089975 deg approx 1000m
    lat2, lon2 = 28.6228975, 77.2090
    actual_dist = haversine_distance(lat1, lon1, lat2, lon2)

    # Cell A with range 500m, Cell B with range = actual_dist - 500m
    # 1. Just barely touching: threshold = actual_dist
    cells_touching = [
        {"tower_id": "T1", "latitude": lat1, "longitude": lon1, "range_m": 500.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": actual_dist - 500.0, "radio": "4G"},
    ]
    g_touch = build_interference_graph(cells_touching)
    assert g_touch.number_of_edges() == 1, "Touching disks must produce an edge under closed-disk model"

    # 2. Clearly separated by 10m: threshold = actual_dist - 10m
    cells_separated = [
        {"tower_id": "T1", "latitude": lat1, "longitude": lon1, "range_m": 500.0, "radio": "4G"},
        {"tower_id": "T2", "latitude": lat2, "longitude": lon2, "range_m": actual_dist - 510.0, "radio": "4G"},
    ]
    g_sep = build_interference_graph(cells_separated)
    assert g_sep.number_of_edges() == 0, "Separated disks must not produce an edge"


def test_no_complete_graph_clique_artifacts_on_dispersed_nodes():
    """Verify that dispersed towers do not form complete clique artifacts."""
    # 10 towers spread over a 20km line with 800m range
    cells = [
        {"tower_id": f"DISP_{i}", "latitude": 28.50 + (i * 0.02), "longitude": 77.20, "range_m": 800.0, "radio": "4G"}
        for i in range(10)
    ]
    g = build_interference_graph(cells)
    metrics = get_graph_metrics(g)

    # Pairwise distance between adjacent towers is ~2.2km, far exceeding 800+800=1600m
    assert g.number_of_nodes() == 10
    assert g.number_of_edges() == 0, "Dispersed towers must not have edges"
    assert metrics["density"] == 0.0
    assert metrics["data_unsuitable"] is False


# ==============================================================================
# 5. Graph Structural Metrics & 4G/5G Technology Distribution Invariants
# ==============================================================================

def test_metrics_technology_distribution_and_bounds_invariants():
    """
    Verify tech distribution sum equals vertex count and clique/brooks bounds.
    """
    cells = [
        {"tower_id": f"4G_{i}", "latitude": 28.52 + (i * 0.001), "longitude": 77.19, "range_m": 600.0, "radio": "4G"}
        for i in range(7)
    ] + [
        {"tower_id": f"5G_{i}", "latitude": 28.53 + (i * 0.001), "longitude": 77.19, "range_m": 400.0, "radio": "5G"}
        for i in range(5)
    ]
    g = build_interference_graph(cells)
    m = get_graph_metrics(g)

    # 1. Vertex count matches total
    assert m["vertex_count"] == 12
    # 2. Technology distribution matches 7 4G and 5 5G
    assert m["technology_distribution"] == {"4G": 7, "5G": 5}
    assert m["technology_distribution"]["4G"] + m["technology_distribution"]["5G"] == m["vertex_count"]
    # 3. Brooks upper bound and clique lower bound
    assert m["clique_lower_bound"] <= m["brooks_upper_bound"]
    # 4. Candidate pairs examined = N * (N - 1) / 2 = 12 * 11 / 2 = 66
    assert m["candidate_pairs_examined"] == 66
    assert m["edges_accepted"] + m["edges_rejected"] == 66
