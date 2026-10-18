import pytest
from graph_engine import (
    build_interference_graph,
    get_graph_metrics,
    get_interference_edges,
    validate_coloring,
    color_welsh_powell,
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

