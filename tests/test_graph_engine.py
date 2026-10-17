# test_graph_engine.py — pytest tests for graph_engine.py
#
# Test plan (to be implemented in Phase 5):
# - Edge rule: d(i,j) <= r_i + r_j produces an edge; d(i,j) > r_i + r_j does not.
# - Missing/invalid range handling matches documented policy.
# - Welsh-Powell produces a valid coloring on paths, cycles, cliques, and
#   disconnected graphs.
# - DSatur produces a valid coloring on the same graphs.
# - The independent validator detects a deliberately invalid coloring.
# - Both algorithms produce deterministic (reproducible) results.
