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


def validate_coloring(graph: nx.Graph, coloring: dict[Any, int]) -> dict[str, Any]:
    """
    Independently verify that a graph coloring has zero conflicts and no missing assignments.
    """
    conflicts: list[tuple[Any, Any]] = []
    missing_nodes: list[Any] = []

    # 1. Assert all graph vertices have an assigned non-negative integer color
    for node in graph.nodes():
        if not coloring or node not in coloring:
            missing_nodes.append(node)
        else:
            val = coloring[node]
            if val is None or not isinstance(val, int) or isinstance(val, bool) or val < 0:
                missing_nodes.append(node)

    # 2. Iterate through every edge and assert adjacent vertices have distinct colors
    for u, v in graph.edges():
        color_u = coloring.get(u) if coloring else None
        color_v = coloring.get(v) if coloring else None
        if color_u is not None and color_v is not None and color_u == color_v:
            conflicts.append((u, v))

    is_valid = len(conflicts) == 0 and len(missing_nodes) == 0
    unique_colors = len({c for c in coloring.values() if isinstance(c, int) and not isinstance(c, bool) and c >= 0}) if coloring else 0

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


def color_dsatur(graph: nx.Graph) -> dict[str, Any]:
    """
    Color a graph using the DSatur (Degree of Saturation) algorithm.
    1. Saturation degree: number of distinct colors assigned to a vertex's neighbors.
    2. Dynamic selection: pick uncolored vertex with highest saturation degree.
    3. Tie-breaking: highest total graph degree, then alphabetical node ID.
    4. Color assignment: lowest available non-negative integer color.
    """
    start_time = time.perf_counter()

    if graph.number_of_nodes() == 0:
        return {
            "algorithm": "DSatur",
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

    coloring: dict[str, int] = {}
    uncolored = set(graph.nodes())

    while uncolored:
        # Select the uncolored vertex with highest saturation degree
        # Tie-breaker: highest graph degree, then alphabetical string ID
        def dsatur_priority(node: str) -> tuple[int, int, str]:
            neighbor_colors = {
                coloring[nbr] for nbr in graph.neighbors(node) if nbr in coloring
            }
            sat_degree = len(neighbor_colors)
            graph_degree = graph.degree(node)
            return (-sat_degree, -graph_degree, str(node))

        chosen_node = min(uncolored, key=dsatur_priority)

        # Find the lowest available color not used by any colored neighbor
        used_colors = {
            coloring[nbr] for nbr in graph.neighbors(chosen_node) if nbr in coloring
        }
        color = 0
        while color in used_colors:
            color += 1

        coloring[chosen_node] = color
        uncolored.remove(chosen_node)

    runtime_ms = round((time.perf_counter() - start_time) * 1000, 3)
    validation = validate_coloring(graph, coloring)

    return {
        "algorithm": "DSatur",
        "coloring": coloring,
        "color_count": validation["color_count"],
        "runtime_ms": runtime_ms,
        "validation": validation,
    }


def color_exact_dsatur_bnb(
    graph: nx.Graph,
    max_nodes: int = 25,
    timeout_sec: float = 0.5,
) -> dict[str, Any]:
    """
    Find the exact chromatic number chi(G) and an optimal vertex coloring using
    a DSatur-guided Branch-and-Bound algorithm with maximum clique symmetry breaking.

    Strictly bounded to max_nodes (default 25) and timeout_sec (default 0.5s).
    Returns a result dictionary with status:
      - 'exact_optimal': proved chi(G) within limits.
      - 'skipped_size_limit': graph size > max_nodes, returns heuristic fallback.
      - 'timeout': search exceeded timeout_sec, returns best valid coloring found.
    """
    start_time = time.perf_counter()
    num_nodes = graph.number_of_nodes()

    # 1. Size bounds check
    if num_nodes > max_nodes:
        dsatur_fallback = color_dsatur(graph)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "algorithm": "exact_dsatur_bnb",
            "coloring": dsatur_fallback["coloring"],
            "color_count": dsatur_fallback["color_count"],
            "runtime_ms": elapsed_ms,
            "status": "skipped_size_limit",
            "proven_optimal": False,
            "lower_bound": None,
            "upper_bound": dsatur_fallback["color_count"],
            "message": f"Graph size ({num_nodes} nodes) exceeds exact solver limit (max {max_nodes} nodes). Returned best heuristic coloring.",
            "validation": dsatur_fallback["validation"],
        }

    # 2. Empty graph base case
    if num_nodes == 0:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "algorithm": "exact_dsatur_bnb",
            "coloring": {},
            "color_count": 0,
            "runtime_ms": elapsed_ms,
            "status": "exact_optimal",
            "proven_optimal": True,
            "lower_bound": 0,
            "upper_bound": 0,
            "message": "Empty graph has chromatic number 0.",
            "validation": validate_coloring(graph, {}),
        }

    # 3. Initial Upper Bound (UB) from DSatur heuristic
    dsatur_init = color_dsatur(graph)
    ub = dsatur_init["color_count"]
    best_coloring = dict(dsatur_init["coloring"])

    # 4. Initial Lower Bound (LB) from Maximum Clique
    clique_nodes, lb = nx.algorithms.clique.max_weight_clique(graph, weight=None)

    # If UB == LB, heuristic is proven optimal immediately (no branching needed)
    if ub == lb:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "algorithm": "exact_dsatur_bnb",
            "coloring": best_coloring,
            "color_count": ub,
            "runtime_ms": elapsed_ms,
            "status": "exact_optimal",
            "proven_optimal": True,
            "lower_bound": lb,
            "upper_bound": ub,
            "message": "Proven optimal chromatic number computed via DSatur branch-and-bound.",
            "validation": dsatur_init["validation"],
        }

    # 5. Root Pre-Coloring on Maximum Clique for symmetry breaking
    # Sort clique deterministically by descending degree, then str(node)
    sorted_clique = sorted(clique_nodes, key=lambda n: (-graph.degree(n), str(n)))
    root_coloring: dict[Any, int] = {node: idx for idx, node in enumerate(sorted_clique)}
    max_color_used = lb - 1

    # 6. Branch and Bound with dynamic DSatur vertex selection & deadline check
    deadline = start_time + timeout_sec
    if time.perf_counter() > deadline:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "algorithm": "exact_dsatur_bnb",
            "coloring": best_coloring,
            "color_count": ub,
            "runtime_ms": elapsed_ms,
            "status": "timeout",
            "proven_optimal": False,
            "lower_bound": lb,
            "upper_bound": ub,
            "message": f"Exact solver exceeded timeout ({timeout_sec * 1000:.0f}ms). Returned best valid coloring found.",
            "validation": dsatur_init["validation"],
        }

    timed_out = False

    def branch(current_coloring: dict[Any, int], current_max_c: int) -> None:
        nonlocal ub, best_coloring, timed_out

        # Monotonic clock check at every branch expansion
        if time.perf_counter() > deadline:
            timed_out = True
            return

        uncolored = [n for n in graph.nodes() if n not in current_coloring]
        if not uncolored:
            # Complete valid coloring found
            k = current_max_c + 1
            if k < ub:
                ub = k
                best_coloring = dict(current_coloring)
            return

        # Dynamic DSatur selection: maximum saturation degree, tie-broken by degree & str(node)
        def priority(node: Any) -> tuple[int, int, str]:
            nbr_colors = {
                current_coloring[nbr]
                for nbr in graph.neighbors(node)
                if nbr in current_coloring
            }
            return (-len(nbr_colors), -graph.degree(node), str(node))

        chosen_node = min(uncolored, key=priority)
        forbidden_colors = {
            current_coloring[nbr]
            for nbr in graph.neighbors(chosen_node)
            if nbr in current_coloring
        }

        # Try existing valid colors in {0, ..., current_max_c}
        for c in range(current_max_c + 1):
            if c not in forbidden_colors:
                current_coloring[chosen_node] = c
                branch(current_coloring, current_max_c)
                del current_coloring[chosen_node]
                if ub == lb or timed_out:
                    return

        # Try at most ONE new color, provided new_c + 1 < ub
        new_c = current_max_c + 1
        if new_c + 1 < ub:
            current_coloring[chosen_node] = new_c
            branch(current_coloring, new_c)
            del current_coloring[chosen_node]
            if ub == lb or timed_out:
                return

    branch(root_coloring, max_color_used)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    validation = validate_coloring(graph, best_coloring)

    if timed_out:
        status = "timeout"
        proven_optimal = False
        message = f"Exact solver exceeded timeout ({timeout_sec * 1000:.0f}ms). Returned best valid coloring found."
    else:
        status = "exact_optimal"
        proven_optimal = True
        message = "Proven optimal chromatic number computed via DSatur branch-and-bound."

    return {
        "algorithm": "exact_dsatur_bnb",
        "coloring": best_coloring,
        "color_count": ub,
        "runtime_ms": elapsed_ms,
        "status": status,
        "proven_optimal": proven_optimal,
        "lower_bound": lb,
        "upper_bound": ub,
        "message": message,
        "validation": validation,
    }


def optimize_graph_frequencies(
    graph: nx.Graph,
    run_exact: bool = True,
) -> dict[str, Any]:
    """
    Run DSatur, Welsh–Powell, and bounded Exact DSatur Branch-and-Bound on the same graph.
    Validate all colorings and select the best valid algorithm (minimum colors; tie-break: DSatur).
    """
    start_time = time.perf_counter()

    dsatur_result = color_dsatur(graph)
    wp_result = color_welsh_powell(graph)

    exact_result = None
    if run_exact:
        exact_result = color_exact_dsatur_bnb(graph)

    # Determine best algorithm among valid solutions
    candidates: list[tuple[str, int]] = []
    if dsatur_result["validation"]["is_valid"]:
        candidates.append(("DSatur", dsatur_result["color_count"]))
    if wp_result["validation"]["is_valid"]:
        candidates.append(("Welsh-Powell", wp_result["color_count"]))
    if exact_result and exact_result["validation"]["is_valid"]:
        candidates.append((exact_result["algorithm"], exact_result["color_count"]))

    if not candidates:
        best_algorithm = "None (all invalid)"
    else:
        min_colors = min(c[1] for c in candidates)
        min_candidates = [name for name, c in candidates if c == min_colors]
        # Prefer DSatur on ties, then Welsh-Powell, then exact
        if "DSatur" in min_candidates:
            best_algorithm = "DSatur"
        elif "Welsh-Powell" in min_candidates:
            best_algorithm = "Welsh-Powell"
        else:
            best_algorithm = min_candidates[0]

    total_runtime_ms = round((time.perf_counter() - start_time) * 1000, 3)
    metrics = get_graph_metrics(graph)

    return {
        "metrics": metrics,
        "best_algorithm": best_algorithm,
        "dsatur": dsatur_result,
        "welsh_powell": wp_result,
        "exact": exact_result,
        "optimization_runtime_ms": total_runtime_ms,
    }


