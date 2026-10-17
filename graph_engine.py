"""
graph_engine.py — Interference graph construction and coloring algorithms

Responsibilities:
- Builds a NetworkX graph: one vertex per accepted cell record.
- Adds an undirected edge between records i and j when d(i, j) <= r_i + r_j,
  where d is geodesic distance in metres and r is the reported range in metres.
- Never treats raw latitude/longitude degree differences as metres.
- Handles missing or invalid ranges according to a documented explicit policy.
- Runs DSatur (highest saturation degree first, then highest degree, then stable id).
- Runs Welsh–Powell (sort by descending degree, greedy independent-set assignment).
- Both algorithms use deterministic tie-breaking for reproducibility.
- Independently validates every coloring: every edge endpoint must have a color
  and adjacent endpoints must have different colors.
- Returns assignments, color counts, runtimes, conflict counts, and edge list.

Implementation: Phase 4 (graph fundamentals) and Phase 5 (coloring algorithms).
"""
