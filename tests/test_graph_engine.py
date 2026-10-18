import pytest
from graph_engine import (
    build_interference_graph,
    get_graph_metrics,
    get_interference_edges,
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
