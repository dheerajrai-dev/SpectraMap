"""
graph_engine.py — Interference graph construction and coloring algorithms
"""

import itertools
from typing import Any
import networkx as nx
from data_service import haversine_distance


def build_interference_graph(cells: list[dict[str, Any]]) -> nx.Graph:
    """
    Construct an undirected NetworkX graph from a list of normalized cell records.
    - Vertex V: Each cell record (identified by tower_id).
    - Edge E: Added between cells (u, v) if haversine_distance(u, v) <= range_u + range_v.
    """
    G = nx.Graph()

    # 1. Add all cell records as vertices with their metadata attached
    for cell in cells:
        tower_id = cell.get("tower_id")
        if not tower_id:
            raise ValueError(f"Cell record missing tower_id: {cell}")
        if "range_m" not in cell or cell["range_m"] <= 0:
            raise ValueError(f"Cell {tower_id} has invalid or missing range_m: {cell.get('range_m')}")

        G.add_node(tower_id, **cell)

    # 2. Check all unique pairs for coverage circle overlap
    cell_nodes = list(G.nodes(data=True))
    for (id_a, data_a), (id_b, data_b) in itertools.combinations(cell_nodes, 2):
        dist = haversine_distance(
            data_a["latitude"], data_a["longitude"],
            data_b["latitude"], data_b["longitude"],
        )
        threshold = data_a["range_m"] + data_b["range_m"]

        # Overlapping coverage circles indicate potential radio interference
        if dist <= threshold:
            G.add_edge(id_a, id_b, distance_m=round(dist, 1), threshold_m=round(threshold, 1))

    return G


def get_graph_metrics(graph: nx.Graph) -> dict[str, Any]:
    """
    Compute basic structural metrics for the interference graph.
    """
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "density": round(nx.density(graph), 4) if node_count > 1 else 0.0,
        "connected_components": nx.number_connected_components(graph) if node_count > 0 else 0,
        "max_degree": max((deg for _, deg in graph.degree()), default=0),
        "avg_degree": round(sum(deg for _, deg in graph.degree()) / node_count, 2) if node_count > 0 else 0.0,
    }


def get_interference_edges(graph: nx.Graph) -> list[dict[str, Any]]:
    """
    Extract edge endpoints with GPS coordinates for map rendering.
    """
    edges: list[dict[str, Any]] = []
    for u, v, data in graph.edges(data=True):
        node_u = graph.nodes[u]
        node_v = graph.nodes[v]
        edges.append({
            "source_id": u,
            "target_id": v,
            "source_coords": [node_u["latitude"], node_u["longitude"]],
            "target_coords": [node_v["latitude"], node_v["longitude"]],
            "distance_m": data.get("distance_m", 0.0),
        })
    return edges
