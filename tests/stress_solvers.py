"""
tests/stress_solvers.py — Adversarial Stress Testing Harness for SpectraMap Solvers
Target: color_exact_dsatur_bnb, color_dsatur, color_welsh_powell, validate_coloring, optimize_graph_frequencies
"""

import sys
import os
import time
import json
import itertools
from typing import Any
import networkx as nx

# Add parent directory to path so we can import project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from graph_engine import (
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    validate_coloring,
    optimize_graph_frequencies,
    get_graph_metrics,
)


def run_random_graph_suite() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 1: 50+ RANDOM GRAPHS STRESS TEST (N in [5, 25], p in [0.1, 0.85])")
    print("=======================================================")

    sizes = [5, 8, 10, 12, 15, 18, 20, 22, 25]
    probabilities = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85]
    
    total_tests = 0
    passed_tests = 0
    failures = []
    
    exact_strictly_better = 0
    exact_equal_heuristic = 0
    
    start_suite_time = time.perf_counter()
    runtimes_exact = []
    
    test_cases = []
    seed_counter = 100
    for n in sizes:
        for p in probabilities:
            # 1 to 2 seeds per (n, p) pair
            for _ in range(2 if n <= 20 else 1):
                seed_counter += 1
                test_cases.append((n, p, seed_counter))

    print(f"Total random graph test cases planned: {len(test_cases)}")

    for idx, (n, p, seed) in enumerate(test_cases, 1):
        total_tests += 1
        G = nx.erdos_renyi_graph(n, p, seed=seed)
        
        # Calculate theoretical lower bound
        clique_nodes, omega = nx.algorithms.clique.max_weight_clique(G, weight=None)
        
        # Solve
        t0 = time.perf_counter()
        exact_res = color_exact_dsatur_bnb(G, max_nodes=25, timeout_sec=0.5)
        t_exact = time.perf_counter() - t0
        runtimes_exact.append(t_exact)
        
        dsatur_res = color_dsatur(G)
        wp_res = color_welsh_powell(G)
        
        chi = exact_res["color_count"]
        k_dsatur = dsatur_res["color_count"]
        k_wp = wp_res["color_count"]
        
        # Independent Validation
        v_exact = validate_coloring(G, exact_res["coloring"])
        v_dsatur = validate_coloring(G, dsatur_res["coloring"])
        v_wp = validate_coloring(G, wp_res["coloring"])
        
        errors = []
        if not v_exact["is_valid"]:
            errors.append(f"Exact coloring invalid! conflicts={v_exact['conflicts']}, missing={v_exact['missing_nodes']}")
        if not v_dsatur["is_valid"]:
            errors.append(f"DSatur coloring invalid! conflicts={v_dsatur['conflicts']}")
        if not v_wp["is_valid"]:
            errors.append(f"Welsh-Powell coloring invalid! conflicts={v_wp['conflicts']}")
            
        # Bound check: omega(G) <= chi(G)
        if chi < omega:
            errors.append(f"Violation: chi({chi}) < omega({omega})")
            
        # Bound check: chi(G) <= min(k_dsatur, k_wp) when exact is optimal
        if exact_res["status"] == "exact_optimal":
            if chi > k_dsatur:
                errors.append(f"Violation: chi({chi}) > k_dsatur({k_dsatur})")
            if chi > k_wp and chi > min(k_dsatur, k_wp):
                errors.append(f"Violation: chi({chi}) > min(k_dsatur, k_wp)")
                
        if chi < min(k_dsatur, k_wp):
            exact_strictly_better += 1
        else:
            exact_equal_heuristic += 1

        if errors:
            failures.append({
                "test": f"G(n={n}, p={p}, seed={seed})",
                "errors": errors
            })
            print(f"[{idx}/{len(test_cases)}] FAIL: G({n}, {p}, seed={seed}): {errors}")
        else:
            passed_tests += 1
            if idx % 10 == 0 or idx == len(test_cases):
                print(f"[{idx:2d}/{len(test_cases)}] PASS: G(N={n:2d}, p={p:.2f}, seed={seed}) -> chi={chi:2d}, omega={omega:2d}, DSatur={k_dsatur:2d}, WP={k_wp:2d}, time={t_exact*1000:.2f}ms")

    suite_duration = time.perf_counter() - start_suite_time
    max_time_ms = max(runtimes_exact) * 1000
    avg_time_ms = (sum(runtimes_exact) / len(runtimes_exact)) * 1000

    print(f"\nRandom Graph Suite Summary:")
    print(f"Total: {total_tests}, Passed: {passed_tests}, Failed: {len(failures)}")
    print(f"Exact strictly beat heuristics in {exact_strictly_better} instances")
    print(f"Exact matched heuristics in {exact_equal_heuristic} instances")
    print(f"Max Exact Runtime: {max_time_ms:.2f}ms, Avg Exact Runtime: {avg_time_ms:.2f}ms, Total Suite Time: {suite_duration:.2f}s")
    
    return {
        "total": total_tests,
        "passed": passed_tests,
        "failed": len(failures),
        "failures": failures,
        "exact_strictly_better": exact_strictly_better,
        "exact_equal_heuristic": exact_equal_heuristic,
        "max_time_ms": max_time_ms,
        "avg_time_ms": avg_time_ms,
    }


def run_discrepancy_proof_test() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 2: DISCREPANCY PROOF CASE (nx.erdos_renyi_graph(18, 0.4, seed=3))")
    print("=======================================================")

    G = nx.erdos_renyi_graph(18, 0.4, seed=3)
    clique_nodes, omega = nx.algorithms.clique.max_weight_clique(G, weight=None)
    
    dsatur = color_dsatur(G)
    wp = color_welsh_powell(G)
    exact = color_exact_dsatur_bnb(G, max_nodes=25, timeout_sec=0.5)
    opt = optimize_graph_frequencies(G, run_exact=True)

    print(f"Graph N: {G.number_of_nodes()}, E: {G.number_of_edges()}, omega(G): {omega}")
    print(f"Welsh-Powell: {wp['color_count']} colors ({wp['runtime_ms']}ms)")
    print(f"DSatur:       {dsatur['color_count']} colors ({dsatur['runtime_ms']}ms)")
    print(f"Exact DSatur: {exact['color_count']} colors ({exact['runtime_ms']}ms, status={exact['status']}, proven={exact['proven_optimal']})")
    print(f"Optimizer Best Algorithm: {opt['best_algorithm']}")

    passed = (
        wp["color_count"] == 5 and
        dsatur["color_count"] == 5 and
        exact["color_count"] == 4 and
        exact["status"] == "exact_optimal" and
        exact["proven_optimal"] is True and
        exact["validation"]["is_valid"] is True and
        opt["best_algorithm"] == "exact_dsatur_bnb"
    )

    print(f"Discrepancy Proof Case Result: {'PASS' if passed else 'FAIL'}")
    return {
        "passed": passed,
        "wp_colors": wp["color_count"],
        "dsatur_colors": dsatur["color_count"],
        "exact_colors": exact["color_count"],
        "exact_status": exact["status"],
        "proven_optimal": exact["proven_optimal"],
        "best_algorithm": opt["best_algorithm"],
    }


def run_canonical_graphs_suite() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 3: CANONICAL AND HARD GRAPH FAMILIES GROUND TRUTH")
    print("=======================================================")

    cases = [
        ("Empty Graph N=0", nx.Graph(), 0),
        ("Single Node N=1", nx.complete_graph(1), 1),
        ("Isolated Nodes N=10", nx.empty_graph(10), 1),
        ("K_5 Complete", nx.complete_graph(5), 5),
        ("K_10 Complete", nx.complete_graph(10), 10),
        ("K_15 Complete", nx.complete_graph(15), 15),
        ("K_25 Complete", nx.complete_graph(25), 25),
        ("C_5 Odd Cycle", nx.cycle_graph(5), 3),
        ("C_7 Odd Cycle", nx.cycle_graph(7), 3),
        ("C_6 Even Cycle", nx.cycle_graph(6), 2),
        ("C_10 Even Cycle", nx.cycle_graph(10), 2),
        ("Bipartite K_3,3", nx.complete_bipartite_graph(3, 3), 2),
        ("Bipartite K_5,5", nx.complete_bipartite_graph(5, 5), 2),
        ("Star Graph S_15", nx.star_graph(15), 2),
        ("Wheel Graph W_6", nx.wheel_graph(6), 4),
        ("Wheel Graph W_7", nx.wheel_graph(7), 3),
        ("Petersen Graph", nx.petersen_graph(), 3),
        ("Grötzsch Graph (M_4)", nx.mycielski_graph(4), 4),
        ("Mycielski 5 (N=23)", nx.mycielski_graph(5), 5),
        ("Chvátal Graph (N=12)", nx.chvatal_graph(), 4),
    ]

    total = len(cases)
    passed = 0
    failures = []

    for name, G, expected_chi in cases:
        res = color_exact_dsatur_bnb(G, max_nodes=25, timeout_sec=1.0)
        v = validate_coloring(G, res["coloring"])
        actual_chi = res["color_count"]
        
        ok = (actual_chi == expected_chi) and v["is_valid"] and (res["status"] == "exact_optimal")
        if ok:
            passed += 1
            print(f"PASS: {name:25s} -> Expected: {expected_chi:2d}, Actual: {actual_chi:2d}, Valid: {v['is_valid']}, Time: {res['runtime_ms']:.2f}ms")
        else:
            failures.append((name, expected_chi, actual_chi, v["is_valid"], res["status"]))
            print(f"FAIL: {name:25s} -> Expected: {expected_chi:2d}, Actual: {actual_chi:2d}, Status: {res['status']}, Valid: {v['is_valid']}")

    return {
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "failures": failures
    }


def run_bounded_limits_suite() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 4: BOUNDED SIZE LIMITS (N=25 vs N=26)")
    print("=======================================================")

    # Test N=25 (Complete graph K_25)
    g25 = nx.complete_graph(25)
    t0 = time.perf_counter()
    res25 = color_exact_dsatur_bnb(g25, max_nodes=25, timeout_sec=0.5)
    t25_ms = (time.perf_counter() - t0) * 1000
    
    # Test N=26 (Complete graph K_26)
    g26 = nx.complete_graph(26)
    t0 = time.perf_counter()
    res26 = color_exact_dsatur_bnb(g26, max_nodes=25, timeout_sec=0.5)
    t26_ms = (time.perf_counter() - t0) * 1000

    # Test N=100
    g100 = nx.erdos_renyi_graph(100, 0.2, seed=42)
    t0 = time.perf_counter()
    res100 = color_exact_dsatur_bnb(g100, max_nodes=25, timeout_sec=0.5)
    t100_ms = (time.perf_counter() - t0) * 1000

    pass_25 = res25["status"] == "exact_optimal" and res25["color_count"] == 25 and res25["validation"]["is_valid"]
    pass_26 = res26["status"] == "skipped_size_limit" and res26["proven_optimal"] is False and t26_ms < 5.0 and res26["validation"]["is_valid"]
    pass_100 = res100["status"] == "skipped_size_limit" and res100["proven_optimal"] is False and res100["validation"]["is_valid"]

    print(f"N=25: status={res25['status']}, proven={res25['proven_optimal']}, colors={res25['color_count']}, time={t25_ms:.2f}ms -> {'PASS' if pass_25 else 'FAIL'}")
    print(f"N=26: status={res26['status']}, proven={res26['proven_optimal']}, colors={res26['color_count']}, time={t26_ms:.2f}ms (<5ms) -> {'PASS' if pass_26 else 'FAIL'}")
    print(f"N=100: status={res100['status']}, proven={res100['proven_optimal']}, colors={res100['color_count']}, time={t100_ms:.2f}ms -> {'PASS' if pass_100 else 'FAIL'}")

    return {
        "pass_25": pass_25,
        "pass_26": pass_26,
        "pass_100": pass_100,
        "t26_ms": t26_ms,
        "t100_ms": t100_ms,
    }


def run_timeout_stress_suite() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 5: TIMEOUT STRESS TEST UNDER TIGHT DEADLINES")
    print("=======================================================")

    # Hard instance 1: Mycielski 5 (23 nodes, chi=5, omega=2, baseline runtime ~20ms)
    m5 = nx.mycielski_graph(5)
    
    # Hard instance 2: Dense ER graph N=25 (seed 203, omega=4, chi=5, baseline runtime ~49ms)
    hard_g25 = nx.erdos_renyi_graph(25, 0.32, seed=203)

    scenarios = [
        # (graph_name, graph, timeout_sec, expected_status)
        ("Mycielski_5 (N=23)", m5, 0.0001, "timeout"),     # 0.1ms microscopic timeout
        ("Mycielski_5 (N=23)", m5, 0.005,  "timeout"),     # 5ms tight timeout (runtime ~20ms)
        ("Mycielski_5 (N=23)", m5, 0.010,  "timeout"),     # 10ms tight timeout
        ("Mycielski_5 (N=23)", m5, 0.050,  "exact_optimal"),# 50ms generous (should finish)
        ("ER(25, 0.32) Hard", hard_g25, 0.005, "timeout"), # 5ms tight timeout (runtime ~49ms)
        ("ER(25, 0.32) Hard", hard_g25, 0.010, "timeout"), # 10ms tight timeout
        ("ER(25, 0.32) Hard", hard_g25, 0.025, "timeout"), # 25ms tight timeout
        ("ER(25, 0.32) Hard", hard_g25, 0.200, "exact_optimal"), # 200ms generous (should finish)
    ]

    results = []

    for g_name, G, timeout, expected_status in scenarios:
        t0 = time.perf_counter()
        res = color_exact_dsatur_bnb(G, max_nodes=25, timeout_sec=timeout)
        wall_time_sec = time.perf_counter() - t0
        
        # Independent validation
        v = validate_coloring(G, res["coloring"])
        
        status = res["status"]
        proven = res["proven_optimal"]
        is_valid_coloring = v["is_valid"]
        
        # Check that wall clock didn't hang indefinitely (grace of timeout + 20ms)
        tolerable_wall = wall_time_sec < (timeout + 0.030) if status == "timeout" else True
        correct_status = (status == expected_status)
        
        ok = is_valid_coloring and correct_status and tolerable_wall
        
        print(f"  {g_name:18s} (Timeout={timeout*1000:5.1f}ms): status={status:13s}, wall={wall_time_sec*1000:6.2f}ms, valid_coloring={is_valid_coloring} -> {'PASS' if ok else 'FAIL'}")
        
        results.append({
            "graph": g_name,
            "timeout_sec": timeout,
            "expected_status": expected_status,
            "actual_status": status,
            "proven": proven,
            "wall_time_ms": wall_time_sec * 1000,
            "valid": is_valid_coloring,
            "ok": ok
        })

    all_passed = all(r["ok"] for r in results)
    return {
        "all_passed": all_passed,
        "results": results,
    }


def run_invariance_and_determinism_suite() -> dict[str, Any]:
    print("\n=======================================================")
    print("SUITE 6: GRAPH INVARIANCE & DETERMINISM")
    print("=======================================================")

    G = nx.erdos_renyi_graph(20, 0.35, seed=777)
    # Add dummy attributes to test preservation
    for n in G.nodes():
        G.nodes[n]["tower_id"] = f"cell_{n}"
        G.nodes[n]["latitude"] = 51.5 + n * 0.01
        G.nodes[n]["longitude"] = -0.1 + n * 0.01
        G.nodes[n]["radio"] = "LTE"
        G.nodes[n]["range_m"] = 800.0
    for u, v in G.edges():
        G.edges[u, v]["distance_m"] = 120.5
        G.edges[u, v]["threshold_m"] = 1600.0

    nodes_before = list(G.nodes(data=True))
    edges_before = list(G.edges(data=True))

    # Execute all algorithms sequentially
    wp1 = color_welsh_powell(G)
    ds1 = color_dsatur(G)
    ex1 = color_exact_dsatur_bnb(G, max_nodes=25, timeout_sec=0.5)
    opt1 = optimize_graph_frequencies(G, run_exact=True)

    nodes_after = list(G.nodes(data=True))
    edges_after = list(G.edges(data=True))

    nodes_unchanged = (nodes_before == nodes_after)
    edges_unchanged = (edges_before == edges_after)
    print(f"Graph Invariance Check: Nodes unchanged={nodes_unchanged}, Edges unchanged={edges_unchanged}")

    # Determinism across 20 repetitions
    print("Testing determinism across 20 runs...")
    runs = 20
    exact_assignments = []
    dsatur_assignments = []
    wp_assignments = []

    for _ in range(runs):
        exact_assignments.append(color_exact_dsatur_bnb(G)["coloring"])
        dsatur_assignments.append(color_dsatur(G)["coloring"])
        wp_assignments.append(color_welsh_powell(G)["coloring"])

    exact_deterministic = all(a == exact_assignments[0] for a in exact_assignments)
    dsatur_deterministic = all(a == dsatur_assignments[0] for a in dsatur_assignments)
    wp_deterministic = all(a == wp_assignments[0] for a in wp_assignments)

    print(f"Welsh-Powell Deterministic: {wp_deterministic}")
    print(f"DSatur Deterministic:       {dsatur_deterministic}")
    print(f"Exact B&B Deterministic:    {exact_deterministic}")

    passed = nodes_unchanged and edges_unchanged and exact_deterministic and dsatur_deterministic and wp_deterministic
    return {
        "passed": passed,
        "nodes_unchanged": nodes_unchanged,
        "edges_unchanged": edges_unchanged,
        "exact_deterministic": exact_deterministic,
        "dsatur_deterministic": dsatur_deterministic,
        "wp_deterministic": wp_deterministic,
    }


def main():
    print("STARTING EMPIRICAL CHALLENGER 2 STRESS TESTING...")
    t_start = time.perf_counter()

    r1 = run_random_graph_suite()
    r2 = run_discrepancy_proof_test()
    r3 = run_canonical_graphs_suite()
    r4 = run_bounded_limits_suite()
    r5 = run_timeout_stress_suite()
    r6 = run_invariance_and_determinism_suite()

    total_time = time.perf_counter() - t_start

    print("\n=======================================================")
    print("FINAL SUMMARY OF EMPIRICAL ADVERSARIAL STRESS TESTING")
    print("=======================================================")
    print(f"1. Random Graphs (50+ graphs): {r1['passed']}/{r1['total']} PASSED (Avg time: {r1['avg_time_ms']:.2f}ms)")
    print(f"2. Discrepancy Proof Case:     {'PASSED' if r2['passed'] else 'FAILED'}")
    print(f"3. Canonical Graph GroundTruth:{r3['passed']}/{r3['total']} PASSED")
    print(f"4. Bounded Size Limits:        {'PASSED' if (r4['pass_25'] and r4['pass_26'] and r4['pass_100']) else 'FAILED'}")
    print(f"5. Timeout Stress Test:        {'PASSED' if r5['all_passed'] else 'FAILED'}")
    print(f"6. Invariance & Determinism:   {'PASSED' if r6['passed'] else 'FAILED'}")
    print(f"Total Execution Time:          {total_time:.2f}s")
    print("=======================================================")

    all_passed = (
        r1["failed"] == 0 and
        r2["passed"] and
        r3["failed"] == 0 and
        r4["pass_25"] and r4["pass_26"] and r4["pass_100"] and
        r5["all_passed"] and
        r6["passed"]
    )

    if all_passed:
        print("\n>>> OVERALL VERDICT: ALL ADVERSARIAL TESTS PASSED (APPROVE) <<<")
        sys.exit(0)
    else:
        print("\n>>> OVERALL VERDICT: ONE OR MORE TESTS FAILED (REQUEST_CHANGES) <<<")
        sys.exit(1)


if __name__ == "__main__":
    main()
