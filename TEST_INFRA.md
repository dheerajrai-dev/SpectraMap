# E2E Test Infra: SpectraMap Path B

## Test Philosophy
- Opaque-box, requirement-driven: Derived directly from `ORIGINAL_REQUEST.md` and `PROJECT.md`, without coupling to internal module implementations.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing across 4 distinct tiers.
- Independent verification: Verifies behavior via public HTTP REST API endpoints (`/api/towers`, `/api/cells`, `/api/graph/build`, `/api/optimize`, `/api/compare`, `/api/health`) and client-facing contract data structures.

---

## Feature Inventory & Test Mapping
| # | Feature | Requirement Source | Tier 1 (Coverage) | Tier 2 (Boundary) | Tier 3 (Pairwise) |
|---|---------|-------------------|:-----------------:|:-----------------:|:-----------------:|
| 1 | Spherical Haversine ($1\mu\text{m}$) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | Closed-Disc Overlap Model ($d \le r_u + r_v$) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 3 | Co-Located Mast Resolution ($\le 2\text{m}$) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 4 | Graph Topological Diagnostics | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 5 | Modern Cellular Filtering (4G/5G only) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 6 | Deterministic FPS Sampling & Ceilings | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 7 | Data Provenance Accounting Invariants | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 8 | Coverage Radii Fallback Hierarchy | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 9 | Dual Solvers on Identical Graph | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 10 | Chromatic Metrics & Statistics | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 11 | Independent 100% Conflict & Boundary Validator | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 12 | Educational Boundaries Structured Object | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 13 | Interactive Force-Directed Canvas Explorer | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 14 | Geographic Map View & Seamless Switching | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 15 | Side-by-Side Benchmark Comparison Dashboard | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 16 | Bidirectional Vertex Inspector | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 17 | Frontend Robustness & Safe DOM Access | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 18 | Educational Disclaimer Presentation | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 19 | Lightweight Managed Stack Compliance | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |
| 20 | 100% Automated Pytest Pass Rate | Acceptance Criteria | 5 | 5 | ✓ |
| 21 | Zero Unhandled JS Runtime Errors | Acceptance Criteria | 5 | 5 | ✓ |

---

## Test Architecture
- **Location**: `tests/e2e/`
  - `tests/e2e/test_tier1_feature_coverage.py`: Tier 1 happy-path feature verification (>= 105 tests).
  - `tests/e2e/test_tier2_boundaries_corners.py`: Tier 2 boundary and extreme value analysis (>= 105 tests).
  - `tests/e2e/test_tier3_cross_feature_combinations.py`: Tier 3 pairwise interactions (>= 21 tests).
  - `tests/e2e/test_tier4_real_world_scenarios.py`: Tier 4 realistic full-system cellular application scenarios (>= 10 tests).
- **Test Runner Invocation**:
  ```powershell
  & "C:\Users\Dheeraj rai\Desktop\SpectraMap\.venv\Scripts\pytest.exe" tests/e2e -v
  ```
- **Pass / Fail Semantics**:
  - Clean exit code 0.
  - Zero unhandled exceptions or test failures.
  - Strict mathematical assertions ($1\mu\text{m}$ precision, 100% edge validation, strict 4G/5G filtering, deterministic FPS ordering).

---

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity | Description |
|---|----------|--------------------|------------|-------------|
| 1 | Urban Dense Macro-Micro Cluster | F1, F2, F3, F4, F6, F9, F11 | High | 150 transceivers in high-density downtown with co-located sectors, severe overlaps, and DSatur/Welsh-Powell benchmark comparison. |
| 2 | Suburban Highway Corridor | F1, F2, F6, F8, F9, F10 | Medium | Linear chain of dispersed 4G/5G towers along a transportation artery testing 2-3 frequency channel reuse. |
| 3 | Heterogeneous Multi-Carrier Site | F3, F4, F5, F7, F8, F11 | High | Mast hosting 18 distinct LTE and NR carriers with shared physical coordinates and differential power/range tiers. |
| 4 | Greenfield Rural Area (Sparse Graph) | F1, F2, F4, F6, F8, F9 | Low | Widely spaced towers with isolated components testing minimal chromatic number ($\chi = 1$) and boundary tolerance. |
| 5 | Legacy Ingestion Attack / Contaminated Feed | F5, F7, F11, F17, F19 | High | Ingestion containing mixed 2G/3G/4G/5G records verifying strict rejection, invariant enforcement, and zero crash. |
| 6 | High-Density $K_{49}$ Sector Stress | F2, F3, F4, F9, F10, F11 | High | 49 co-located transceivers verifying complete clique suppression and single physical mast vertex consolidation. |
| 7 | Full Geodesic Polar & Date-Line Extremes | F1, F2, F4, F8, F11 | Medium | Sites located near anti-meridian ($\pm 180^\circ$) and high latitudes testing spherical math stability. |
| 8 | Rapid View-Switching & Drag Lifecycle | F13, F14, F16, F17, F21 | Medium | Full state lifecycle testing Map and Graph tab toggling, node selection synchronization, and DOM null safety. |
| 9 | Direct Solver Comparison & Efficiency Delta | F9, F10, F11, F12, F15 | Medium | Direct `/api/compare` benchmarking evaluating chromatic number agreement, runtime speedup, and channel reuse. |
| 10 | Complete End-to-End User Pipeline | F1-F21 | High | Fetch -> Filter -> Aggregate -> Build Graph -> Optimize DSatur -> Optimize Welsh-Powell -> Inspect Vertex -> Compare. |

---

## Coverage Thresholds
- **Tier 1**: $\ge 5$ test cases per feature ($21 \times 5 = 105$ tests).
- **Tier 2**: $\ge 5$ test cases per feature with boundary conditions ($21 \times 5 = 105$ tests).
- **Tier 3**: $\ge 21$ test cases covering major pairwise interactions.
- **Tier 4**: $\ge 10$ realistic application scenarios.
- **Total Minimum Target**: $\ge 241$ E2E tests.
