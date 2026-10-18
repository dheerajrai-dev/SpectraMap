import pytest
from graph_engine import (
    build_interference_graph,
    get_graph_metrics,
    get_interference_edges,
    validate_coloring,
    color_welsh_powell,
    color_dsatur,
    color_exact_dsatur_bnb,
    optimize_graph_frequencies,
)


def test_build_empty_graph():
    graph = build_interference_graph([])
    assert graph.number_of_nodes() == 0
    assert graph.number_of_edges() == 0


def test_build_graph_invalid_cell_raises():
    # Missing tower_id
    with pytest.raises(ValueError, match="missing tower_id"):
        build_interference_graph([{"latitude": 28.0, "longitude": 77.0, "range_m": 500}])

    # Invalid range_m <= 0
    with pytest.raises(ValueError, match="invalid or missing range_m"):
        build_interference_graph([{"tower_id": "T1", "latitude": 28.0, "longitude": 77.0, "range_m": 0}])


def test_build_graph_overlapping_pair():
    # Two cells ~333 metres apart, each with range 300m (sum of ranges = 600m > 333m)
    cell_a = {"tower_id": "T_A", "latitude": 28.6139, "longitude": 77.2090, "range_m": 300.0}
    cell_b = {"tower_id": "T_B", "latitude": 28.6169, "longitude": 77.2090, "range_m": 300.0}

    graph = build_interference_graph([cell_a, cell_b])
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert graph.has_edge("T_A", "T_B")


def test_build_graph_non_overlapping_pair():
    # Two cells ~1110 metres apart (0.01 deg lat), each with range 200m (sum of ranges = 400m < 1110m)
    cell_a = {"tower_id": "T_A", "latitude": 28.6139, "longitude": 77.2090, "range_m": 200.0}
    cell_b = {"tower_id": "T_B", "latitude": 28.6239, "longitude": 77.2090, "range_m": 200.0}

    graph = build_interference_graph([cell_a, cell_b])
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 0
    assert not graph.has_edge("T_A", "T_B")


def test_build_graph_path_topology():
    # A is at 28.610, B is at 28.613, C is at 28.616 (~333m apart each)
    # Range is 250m each (sum = 500m): A overlaps B, B overlaps C, but A and C are ~667m apart (> 500m)
    cell_a = {"tower_id": "A", "latitude": 28.6100, "longitude": 77.2090, "range_m": 250.0}
    cell_b = {"tower_id": "B", "latitude": 28.6130, "longitude": 77.2090, "range_m": 250.0}
    cell_c = {"tower_id": "C", "latitude": 28.6160, "longitude": 77.2090, "range_m": 250.0}

    graph = build_interference_graph([cell_a, cell_b, cell_c])
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2
    assert graph.has_edge("A", "B")
    assert graph.has_edge("B", "C")
    assert not graph.has_edge("A", "C")


def test_get_graph_metrics():
    # Create triangle (clique of 3)
    cells = [
        {"tower_id": "A", "latitude": 28.6100, "longitude": 77.2090, "range_m": 1000.0},
        {"tower_id": "B", "latitude": 28.6110, "longitude": 77.2090, "range_m": 1000.0},
        {"tower_id": "C", "latitude": 28.6105, "longitude": 77.2100, "range_m": 1000.0},
    ]
    graph = build_interference_graph(cells)
    metrics = get_graph_metrics(graph)

    assert metrics["node_count"] == 3
    assert metrics["edge_count"] == 3
    assert metrics["density"] == 1.0
    assert metrics["connected_components"] == 1
    assert metrics["max_degree"] == 2
    assert metrics["avg_degree"] == 2.0


def test_get_interference_edges():
    cells = [
        {"tower_id": "A", "latitude": 28.6100, "longitude": 77.2090, "range_m": 500.0},
        {"tower_id": "B", "latitude": 28.6120, "longitude": 77.2090, "range_m": 500.0},
    ]
    graph = build_interference_graph(cells)
    edges = get_interference_edges(graph)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["source_id"] in ["A", "B"]
    assert edge["target_id"] in ["A", "B"]
    assert edge["source_coords"] == [28.6100, 77.2090] or edge["source_coords"] == [28.6120, 77.2090]
    assert edge["distance_m"] > 0


def test_validator_detects_deliberate_conflict():
    import networkx as nx
    G = nx.Graph()
    G.add_edge("A", "B")

    # Deliberate conflict: adjacent nodes both assigned color 0
    bad_coloring = {"A": 0, "B": 0}
    val = validate_coloring(G, bad_coloring)
    assert val["is_valid"] is False
    assert val["conflict_count"] == 1
    assert ("A", "B") in val["conflicts"] or ("B", "A") in val["conflicts"]


def test_validator_detects_missing_node():
    import networkx as nx
    G = nx.Graph()
    G.add_edge("A", "B")

    # Missing node B
    incomplete_coloring = {"A": 0}
    val = validate_coloring(G, incomplete_coloring)
    assert val["is_valid"] is False
    assert val["missing_count"] == 1
    assert "B" in val["missing_nodes"]


def test_welsh_powell_path_graph():
    # Path P3: A–B–C requires 2 colors (A:0, B:1, C:0)
    import networkx as nx
    G = nx.Graph()
    G.add_edges_from([("A", "B"), ("B", "C")])

    res = color_welsh_powell(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 2
    assert res["coloring"]["A"] != res["coloring"]["B"]
    assert res["coloring"]["B"] != res["coloring"]["C"]
    assert res["coloring"]["A"] == res["coloring"]["C"]  # Same color reused!


def test_welsh_powell_clique():
    # Complete graph K4 requires exactly 4 colors
    import networkx as nx
    G = nx.complete_graph(4)

    res = color_welsh_powell(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 4


def test_welsh_powell_odd_cycle():
    # Odd cycle C5 requires 3 colors
    import networkx as nx
    G = nx.cycle_graph(5)

    res = color_welsh_powell(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 3


def test_welsh_powell_deterministic():
    # Ensure 10 runs produce identical assignments
    import networkx as nx
    G = nx.erdos_renyi_graph(20, 0.3, seed=42)

    first_run = color_welsh_powell(G)["coloring"]
    for _ in range(10):
        subsequent_run = color_welsh_powell(G)["coloring"]
        assert first_run == subsequent_run


def test_dsatur_path_graph():
    # Path P3: A–B–C requires 2 colors
    import networkx as nx
    G = nx.Graph()
    G.add_edges_from([("A", "B"), ("B", "C")])

    res = color_dsatur(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 2
    assert res["coloring"]["A"] != res["coloring"]["B"]
    assert res["coloring"]["B"] != res["coloring"]["C"]
    assert res["coloring"]["A"] == res["coloring"]["C"]


def test_dsatur_clique():
    # Complete graph K4 requires 4 colors
    import networkx as nx
    G = nx.complete_graph(4)

    res = color_dsatur(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 4


def test_dsatur_odd_cycle():
    # Odd cycle C5 requires 3 colors
    import networkx as nx
    G = nx.cycle_graph(5)

    res = color_dsatur(G)
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] == 3


def test_dsatur_deterministic():
    # Ensure 10 runs produce identical assignments
    import networkx as nx
    G = nx.erdos_renyi_graph(20, 0.3, seed=42)

    first_run = color_dsatur(G)["coloring"]
    for _ in range(10):
        subsequent_run = color_dsatur(G)["coloring"]
        assert first_run == subsequent_run


def test_optimize_graph_frequencies():
    # Test full comparison runner on a 5-node graph
    import networkx as nx
    G = nx.cycle_graph(5)

    opt = optimize_graph_frequencies(G)
    assert "metrics" in opt
    assert opt["metrics"]["node_count"] == 5
    assert opt["metrics"]["edge_count"] == 5
    assert opt["best_algorithm"] in ["DSatur", "Welsh-Powell"]
    assert opt["dsatur"]["validation"]["is_valid"] is True
    assert opt["welsh_powell"]["validation"]["is_valid"] is True
    assert opt["dsatur"]["color_count"] == 3
    assert opt["welsh_powell"]["color_count"] == 3
    assert "exact" in opt
    assert opt["exact"] is not None
    assert opt["exact"]["validation"]["is_valid"] is True
    assert opt["exact"]["color_count"] == 3
    assert opt["exact"]["status"] == "exact_optimal"
    assert opt["exact"]["proven_optimal"] is True
    assert opt["optimization_runtime_ms"] >= 0


def test_optimize_graph_frequencies_run_exact_false():
    import networkx as nx
    G = nx.cycle_graph(5)
    opt = optimize_graph_frequencies(G, run_exact=False)
    assert opt["exact"] is None
    assert opt["best_algorithm"] in ["DSatur", "Welsh-Powell"]


def test_exact_solver_empty_graph():
    import networkx as nx
    G = nx.Graph()
    res = color_exact_dsatur_bnb(G)
    assert res["algorithm"] == "exact_dsatur_bnb"
    assert res["color_count"] == 0
    assert res["coloring"] == {}
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["lower_bound"] == 0
    assert res["upper_bound"] == 0
    assert res["validation"]["is_valid"] is True


def test_exact_solver_isolated_nodes():
    import networkx as nx
    G = nx.Graph()
    G.add_nodes_from(["n1", "n2", "n3", "n4", "n5"])
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 1
    assert res["validation"]["is_valid"] is True
    assert all(c == 0 for c in res["coloring"].values())


def test_exact_solver_complete_graphs():
    import networkx as nx
    for n in [3, 4, 5]:
        G = nx.complete_graph(n)
        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["color_count"] == n
        assert res["validation"]["is_valid"] is True


def test_exact_solver_odd_cycles():
    import networkx as nx
    for n in [5, 7]:
        G = nx.cycle_graph(n)
        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["color_count"] == 3
        assert res["validation"]["is_valid"] is True


def test_exact_solver_even_cycles():
    import networkx as nx
    for n in [4, 6]:
        G = nx.cycle_graph(n)
        res = color_exact_dsatur_bnb(G)
        assert res["status"] == "exact_optimal"
        assert res["proven_optimal"] is True
        assert res["color_count"] == 2
        assert res["validation"]["is_valid"] is True


def test_exact_solver_bipartite_graph():
    import networkx as nx
    G = nx.complete_bipartite_graph(3, 3)
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 2
    assert res["validation"]["is_valid"] is True


def test_exact_solver_groetzsch_graph():
    # Mycielski graph of C5 has N=11, omega=2, chi=4
    import networkx as nx
    G = nx.mycielski_graph(4)
    assert G.number_of_nodes() == 11
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 4
    assert res["validation"]["is_valid"] is True


def test_exact_solver_petersen_graph():
    import networkx as nx
    G = nx.petersen_graph()
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 3
    assert res["validation"]["is_valid"] is True


def test_exact_solver_tree_star():
    import networkx as nx
    G = nx.star_graph(15)
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 2
    assert res["validation"]["is_valid"] is True


def test_exact_solver_wheel_graphs():
    import networkx as nx
    # W5 = wheel with 5 nodes (hub + C4) -> chi=3
    # W6 = wheel with 6 nodes (hub + C5) -> chi=4
    W5 = nx.wheel_graph(5)
    res5 = color_exact_dsatur_bnb(W5)
    assert res5["color_count"] == 3
    assert res5["proven_optimal"] is True

    W6 = nx.wheel_graph(6)
    res6 = color_exact_dsatur_bnb(W6)
    assert res6["color_count"] == 4
    assert res6["proven_optimal"] is True


def test_exact_solver_beats_heuristics_er_seed_3():
    # Discrepancy proof case: G(18, 0.4, seed=3)
    # Welsh-Powell and DSatur both consume 5 colors, exact solver proves chi(G) = 4
    import networkx as nx
    G = nx.erdos_renyi_graph(18, 0.4, seed=3)

    wp = color_welsh_powell(G)
    ds = color_dsatur(G)
    exact = color_exact_dsatur_bnb(G)

    assert wp["color_count"] == 5
    assert ds["color_count"] == 5
    assert exact["color_count"] == 4
    assert exact["proven_optimal"] is True
    assert exact["status"] == "exact_optimal"
    assert exact["validation"]["is_valid"] is True

    # When integrated into optimize_graph_frequencies, exact solver is selected as best
    opt = optimize_graph_frequencies(G)
    assert opt["best_algorithm"] == "exact_dsatur_bnb"
    assert opt["exact"]["color_count"] == 4


def test_exact_solver_size_limit_skipped():
    import networkx as nx
    # N=26 exceeds limit of 25
    G26 = nx.path_graph(26)
    res26 = color_exact_dsatur_bnb(G26, max_nodes=25)
    assert res26["status"] == "skipped_size_limit"
    assert res26["proven_optimal"] is False
    assert res26["validation"]["is_valid"] is True
    assert res26["color_count"] == color_dsatur(G26)["color_count"]

    # Boundary N=25 within limit
    G25 = nx.path_graph(25)
    res25 = color_exact_dsatur_bnb(G25, max_nodes=25)
    assert res25["status"] == "exact_optimal"
    assert res25["proven_optimal"] is True
    assert res25["color_count"] == 2


def test_exact_solver_timeout_handling():
    import networkx as nx
    # Graph requiring branching with microscopic timeout of 0.0001s halts within deadline
    G = nx.erdos_renyi_graph(25, 0.35, seed=2)
    res = color_exact_dsatur_bnb(G, timeout_sec=0.0001)
    assert res["status"] == "timeout"
    assert res["proven_optimal"] is False
    assert res["validation"]["is_valid"] is True
    assert res["color_count"] >= 1


def test_solvers_graph_invariance():
    import networkx as nx
    import copy
    G = nx.Graph()
    G.add_node("T1", latitude=28.61, longitude=77.20, range_m=500.0)
    G.add_node("T2", latitude=28.62, longitude=77.20, range_m=500.0)
    G.add_node("T3", latitude=28.63, longitude=77.20, range_m=500.0)
    G.add_edge("T1", "T2", distance_m=300.0, threshold_m=1000.0)
    G.add_edge("T2", "T3", distance_m=300.0, threshold_m=1000.0)

    nodes_before = copy.deepcopy(list(G.nodes(data=True)))
    edges_before = copy.deepcopy(list(G.edges(data=True)))

    color_welsh_powell(G)
    assert list(G.nodes(data=True)) == nodes_before
    assert list(G.edges(data=True)) == edges_before

    color_dsatur(G)
    assert list(G.nodes(data=True)) == nodes_before
    assert list(G.edges(data=True)) == edges_before

    color_exact_dsatur_bnb(G)
    assert list(G.nodes(data=True)) == nodes_before
    assert list(G.edges(data=True)) == edges_before

    optimize_graph_frequencies(G)
    assert list(G.nodes(data=True)) == nodes_before
    assert list(G.edges(data=True)) == edges_before


def test_exact_solver_determinism():
    import networkx as nx
    G = nx.erdos_renyi_graph(15, 0.35, seed=99)
    first_run = color_exact_dsatur_bnb(G)
    for _ in range(10):
        subsequent_run = color_exact_dsatur_bnb(G)
        assert first_run["coloring"] == subsequent_run["coloring"]
        assert first_run["color_count"] == subsequent_run["color_count"]
        assert first_run["status"] == subsequent_run["status"]


def test_validator_invalid_color_types_and_values():
    import networkx as nx
    G = nx.path_graph(3)

    # Negative color
    bad1 = {0: -1, 1: 0, 2: 1}
    assert validate_coloring(G, bad1)["is_valid"] is False

    # Boolean as color (bool is subclass of int in Python)
    bad2 = {0: True, 1: 0, 2: 1}
    assert validate_coloring(G, bad2)["is_valid"] is False

    # String as color
    bad3 = {0: "color0", 1: 0, 2: 1}
    assert validate_coloring(G, bad3)["is_valid"] is False


def test_validator_disjoint_components():
    import networkx as nx
    # Two disconnected triangles: K3 + K3
    G = nx.disjoint_union(nx.complete_graph(3), nx.complete_graph(3))
    res = color_exact_dsatur_bnb(G)
    assert res["status"] == "exact_optimal"
    assert res["proven_optimal"] is True
    assert res["color_count"] == 3
    assert res["validation"]["is_valid"] is True


def test_cellular_spatial_topologies():
    # 1. Complete overlap cluster: 3 towers at exact same coordinates with 500m range -> K3
    cells_overlap = [
        {"tower_id": "C1", "latitude": 28.6000, "longitude": 77.2000, "range_m": 500.0},
        {"tower_id": "C2", "latitude": 28.6000, "longitude": 77.2000, "range_m": 500.0},
        {"tower_id": "C3", "latitude": 28.6000, "longitude": 77.2000, "range_m": 500.0},
    ]
    g_overlap = build_interference_graph(cells_overlap)
    assert g_overlap.number_of_nodes() == 3
    assert g_overlap.number_of_edges() == 3
    exact_overlap = color_exact_dsatur_bnb(g_overlap)
    assert exact_overlap["color_count"] == 3

    # 2. Disjoint array: 3 towers 5km apart with 200m range -> 0 edges
    cells_disjoint = [
        {"tower_id": "D1", "latitude": 28.6000, "longitude": 77.2000, "range_m": 200.0},
        {"tower_id": "D2", "latitude": 28.6500, "longitude": 77.2000, "range_m": 200.0},
        {"tower_id": "D3", "latitude": 28.7000, "longitude": 77.2000, "range_m": 200.0},
    ]
    g_disjoint = build_interference_graph(cells_disjoint)
    assert g_disjoint.number_of_nodes() == 3
    assert g_disjoint.number_of_edges() == 0
    exact_disjoint = color_exact_dsatur_bnb(g_disjoint)
    assert exact_disjoint["color_count"] == 1


