"""
graph_engine.py — Interference graph construction and coloring algorithms
"""

import itertools
import time
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


def validate_coloring(graph: nx.Graph, coloring: dict[str, int]) -> dict[str, Any]:
    """
    Independently verify that a graph coloring has zero conflicts and no missing assignments.
    """
    conflicts: list[tuple[str, str]] = []
    missing_nodes: list[str] = []

    # 1. Assert all graph vertices have an assigned color
    for node in graph.nodes():
        if node not in coloring or coloring[node] is None:
            missing_nodes.append(node)

    # 2. Iterate through every edge and assert adjacent vertices have distinct colors
    for u, v in graph.edges():
        color_u = coloring.get(u)
        color_v = coloring.get(v)
        if color_u is not None and color_v is not None and color_u == color_v:
            conflicts.append((u, v))

    is_valid = len(conflicts) == 0 and len(missing_nodes) == 0
    unique_colors = len(set(coloring.values())) if coloring else 0

    return {
        "is_valid": is_valid,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "missing_count": len(missing_nodes),
        "missing_nodes": missing_nodes,
        "color_count": unique_colors,
    }


def color_welsh_powell(graph: nx.Graph) -> dict[str, Any]:
    """
    Color a graph using the Welsh–Powell algorithm with deterministic tie-breaking.
    1. Sort vertices by descending degree (tie-break alphabetically by node ID).
    2. Sequentially assign the lowest possible color to maximal independent sets.
    """
    start_time = time.perf_counter()

    if graph.number_of_nodes() == 0:
        return {
            "algorithm": "Welsh-Powell",
            "coloring": {},
            "color_count": 0,
            "runtime_ms": 0.0,
            "validation": {
                "is_valid": True,
                "conflict_count": 0,
                "conflicts": [],
                "missing_count": 0,
                "missing_nodes": [],
                "color_count": 0,
            },
        }

    # Sort vertices by descending degree; tie-break deterministically by node string
    sorted_nodes = sorted(graph.nodes(), key=lambda n: (-graph.degree(n), str(n)))

    coloring: dict[str, int] = {}
    current_color = 0
    uncolored = list(sorted_nodes)

    while uncolored:
        colored_in_this_pass: list[str] = []

        # Find all uncolored vertices that can receive current_color in this pass
        for node in uncolored:
            # Check if any neighbor of this node already has current_color
            has_color_conflict = any(
                neighbor in coloring and coloring[neighbor] == current_color
                for neighbor in graph.neighbors(node)
            )

            if not has_color_conflict:
                coloring[node] = current_color
                colored_in_this_pass.append(node)

        # Remove the vertices colored in this pass and advance to the next color
        uncolored = [n for n in uncolored if n not in colored_in_this_pass]
        current_color += 1

    runtime_ms = round((time.perf_counter() - start_time) * 1000, 3)
    validation = validate_coloring(graph, coloring)

    return {
        "algorithm": "Welsh-Powell",
        "coloring": coloring,
        "color_count": validation["color_count"],
        "runtime_ms": runtime_ms,
        "validation": validation,
    }

