# Project: SpectraMap Path B

## Architecture
SpectraMap Path B is an educational, interactive web application demonstrating graph-theoretic frequency allocation under cellular interference constraints.
Architecture is a lightweight modular monolith:
- **Backend**: Python 3.14 + FastAPI + NetworkX + pure Python spherical Haversine.
  - `data_service.py`: Ingestion, 4G/5G strict filtering, OpenCellID bounding box queries, 4-tier radius fallback hierarchy, 2m intra-site transceiver aggregation, deterministic Farthest Point Sampling (FPS), and data provenance accounting.
  - `graph_engine.py`: Closed-disc overlap conflict graph construction ($d(u,v) \le r_u + r_v$, spherical Haversine $R=6,371,000\text{m}$, $1\mu\text{m}$ tolerance), topological diagnostics, dual heuristic solvers (DSatur & Welsh-Powell) executed on identical graph, exact chromatic solver (B&B $N \le 25$), and independent 100% edge conflict & boundary validator.
  - `schemas.py`: Pydantic V2 models defining strict contract models for towers, graph requests, optimization, comparison, metrics, and diagnostics.
  - `app.py`: FastAPI application exposing RESTful endpoints (`/api/towers`, `/api/cells`, `/api/graph/build`, `/api/optimize`, `/api/compare`, `/api/health`).
- **Frontend**: Vanilla HTML5, CSS3 (`static/style.css`), vanilla JavaScript ES2022 (`static/app.js`), Leaflet 1.9.4.
  - Primary View: Graph Topology Explorer (interactive force-directed canvas simulation: Coulomb repulsion, Hooke springs, damping, node dragging, node size $\propto \Delta(v)$, node color $\propto f_i$, adaptive edge opacity).
  - Spatial Context View: Geographic Map (Leaflet map with tower markers and frequency-tinted coverage discs). Seamless switching without state loss.
  - Benchmark Dashboard: Side-by-side DSatur vs Welsh-Powell comparison card with runtimes, color counts, validation badges, and frequency channel reuse breakdown.
  - Vertex Inspector: Bidirectional selection inspector highlighting incident conflict edges and immediate neighbors.
  - Educational Disclaimer: Abstraction notice and mathematical boundaries.

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Spherical Haversine Distance ($1\mu\text{m}$) | Great-circle distance with $R=6,371,000\text{m}$, SI metres, $1\mu\text{m}$ numerical tolerance. | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Closed-Disc Conflict Graph Modeling | Undirected edge $(u,v) \in E \iff d(u,v) \le r_u + r_v$, avoiding synthetic complete cliques. | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Co-Located Mast Resolution ($\le 2\text{m}$) | Consolidate transceivers within $\le 2\text{m}$ into a single physical mast vertex, preserving max range provenance. Support native `aggregate_2m` parameter across all graph endpoints. | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Graph Topological Diagnostics | Full diagnostic metrics: $\|V\|$, $\|E\|$, density $D = \frac{2\|E\|}{\|V\|(\|V\|-1)}$, maximum degree $\Delta(G)$, average degree, candidate pairs examined, edges accepted/rejected, and `coordinate_diversity`. | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Modern Cellular Filtering (4G/5G only) | Exclusively admit 4G (LTE) and 5G (NR); strictly reject 2G (GSM) and 3G (UMTS) across all endpoints and schemas. Eliminate silent legacy mapping and legacy fallback radii. | M1 | ORIGINAL_REQUEST §R2 |
| 6 | Deterministic FPS Sampling & Ceilings | Farthest Point Sampling under configurable record ceilings (default 50, range 10-200), deterministic tie-breaking, executed post-aggregation so vertex ceiling is reached. | M1 | ORIGINAL_REQUEST §R2 |
| 7 | Data Provenance Accounting | Rigorous accounting: `available_count`, `eligible_count`, `selected_count`, `excluded_count`, with `excluded = excluded_radio + excluded_limit`. | M1 | ORIGINAL_REQUEST §R2 |
| 8 | Coverage Radii Fallback Hierarchy | Distinguish observed OpenCellID measurements from fallback defaults (4G: 800m, 5G: 500m) with 4-tier provenance metadata. | M1 | ORIGINAL_REQUEST §R2 |
| 9 | Dual Solvers on Identical Graph | Execute DSatur and Welsh-Powell on the exact same immutable graph representation. | M1 | ORIGINAL_REQUEST §R3 |
| 10 | Chromatic Metrics & Statistics | Report `chi_heuristic`, runtimes (ms), Welsh-Powell degree ordering statistics, DSatur dynamic saturation statistics. | M1 | ORIGINAL_REQUEST §R3 |
| 11 | Independent 100% Conflict & Boundary Validator | Inspect 100% of conflict edges $(u,v) \in E$ to verify $c(u) \neq c(v)$, zero-distance ($d < 1\mu\text{m}$), and boundary violations ($d > r_u + r_v + 1\mu\text{m}$). | M1 | ORIGINAL_REQUEST §R3 |
| 12 | Educational Boundaries Structured Object | Include structured disclaimer object in API responses clarifying heuristic abstraction and interference bounds. | M1 | ORIGINAL_REQUEST §R3 |
| 13 | Interactive Force-Directed Canvas Explorer | Clean HTML5 canvas physics simulation (Coulomb repulsion, Hooke springs on edges, velocity damping, node dragging), node size mapped to degree $\Delta(v)$, node color mapped to frequency channel, adaptive edge opacity. | M2 | ORIGINAL_REQUEST §R4 |
| 14 | Geographic Map View & Seamless Switching | Leaflet map with tower markers and frequency-tinted discs. Tab switching between Map and Graph without state loss, calling `updateMapVisualStyles()` and `map.invalidateSize()`. | M2 | ORIGINAL_REQUEST §R4 |
| 15 | Side-by-Side Benchmark Comparison Card | Embedded dashboard card displaying DSatur vs Welsh-Powell color counts, runtimes, validation badges, and frequency channel reuse breakdown. Pass `aggregate_2m` in direct comparison. | M2 | ORIGINAL_REQUEST §R4 |
| 16 | Bidirectional Vertex Inspector | Selecting a node in Map or Graph highlights incident conflict edges and adjacent neighbors, displaying channel allocation rationale and provenance. | M2 | ORIGINAL_REQUEST §R4 |
| 17 | Frontend Robustness & Safe DOM Access | Eliminate all unguarded `document.getElementById` property accesses and duplicate keys; zero unhandled JS errors. | M2 | ORIGINAL_REQUEST §R4 |
| 18 | Educational Disclaimer UI Presentation | Display clear educational notes on heuristic bounds and radio disc abstraction in the UI. | M2 | ORIGINAL_REQUEST §R4 |
| 19 | Lightweight Managed Stack Compliance | Python 3.14, FastAPI, NetworkX, HTML5, CSS3, vanilla JS, Leaflet. No React, databases, microservices, GIS engines, or AI wrappers. | M1 & M2 | ORIGINAL_REQUEST §R5 |
| 20 | 100% Pass of E2E Test Suite | Automated pytest suite passes with 0 failures covering all Tiers 1-4 requirements. | M3 | Acceptance Criteria |
| 21 | Adversarial Coverage Hardening | Tier 5 adversarial tests developed via Challenger loop verifying edge cases and boundary conditions. | M3 | Acceptance Criteria |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Suite Track | Design and implement opaque-box E2E test suite (Tiers 1-4) in `tests/e2e/`, publishing `TEST_READY.md`. | none | DONE |
| M1 | Backend Mathematical Core & Data Filtering | Features 1-12, 19: Haversine precision, mast consolidation $\le 2\text{m}$, diagnostics with coordinate diversity, strict 4G/5G filtering, FPS ordering, provenance accounting, dual solvers, full 100% edge/boundary validator, structured educational disclaimers. | none | DONE |
| M2 | Frontend Graph Explorer & Map Workspace | Features 13-19: Force-directed canvas simulation with dragging & degree-mapped radii, Leaflet view sync, benchmark comparison card with channel reuse breakdown, vertex inspector, safe DOM guards. | M1 interface contracts | DONE |
| M3 | Final Acceptance & Adversarial Hardening | Features 20-21: Phase 1 (100% E2E test suite pass), Phase 2 (Tier 5 adversarial hardening with Challenger-initiated loop). | M1, M2, E2E | DONE |

---

## Interface Contracts

### 1. `GET /api/towers` & `GET /api/cells`
- **Query Parameters**:
  - `lat`: float (required)
  - `lon`: float (required)
  - `radius_m`: float (default: 5000.0, min: 100.0, max: 20000.0)
  - `limit`: int (default: 50, min: 10, max: 200)
  - `radios`: string (default: `"4G,5G"`, allowed: `"4G"`, `"5G"`, `"4G,5G"`; rejects `"2G"`, `"3G"`, `"GSM"`, `"UMTS"` with HTTP 400)
  - `aggregate_2m`: bool (default: `True`)
- **Response Schema (`TowersResponse`)**:
  - `towers`: `list[CellRecord]`
  - `metadata`: `AccountingMetadata` (`available_records`, `eligible_records`, `selected_records`, `excluded_records`, `excluded_by_radio`, `excluded_by_limit`, `query_center`, `search_radius_m`, `radios_requested`, `sampling_method`)

### 2. `POST /api/graph/build`
- **Payload (`GraphBuildRequest`)**:
  - `cells`: `list[CellRecord] | None` (strictly validated against 4G/5G, rejects legacy radios)
  - `center`: `Coordinates | None`
  - `radius_m`: `float`
  - `limit`: `int` (10-200)
  - `aggregate_2m`: `bool` (default: `True`)
- **Response Schema (`GraphBuildResponse`)**:
  - `nodes`: `list[GraphNode]`
  - `edges`: `list[GraphEdge]`
  - `diagnostics`: `GraphDiagnostics` (includes `coordinate_diversity`: float in [0.0, 1.0], `density`, `max_degree`, `avg_degree`, `edges_accepted`, `edges_rejected`, `candidate_pairs_examined`)
  - `educational_disclaimer`: `EducationalDisclaimer`

### 3. `POST /api/optimize`
- **Payload (`OptimizeRequest`)**:
  - `cells`: `list[CellRecord] | None`
  - `center`: `Coordinates | None`
  - `algorithm`: `"dsatur" | "welsh_powell" | "exact"`
  - `aggregate_2m`: `bool` (default: `True`)
- **Response Schema (`OptimizeResponse`)**:
  - `assignments`: `dict[str, int]` (1-based frequency channel)
  - `colors_used`: `int`
  - `chi_heuristic`: `int` (matching `colors_used`)
  - `runtime_ms`: `float`
  - `solver_diagnostics`: `SolverDiagnostics` (Welsh-Powell degree ordering stats, DSatur saturation stats)
  - `validation`: `ValidationResult` (`is_valid`, `conflict_count`, `boundary_violations`, `zero_distance_edges`, `edges_inspected`, `details`)
  - `educational_disclaimer`: `EducationalDisclaimer`

### 4. `POST /api/compare`
- **Payload (`CompareRequest`)**:
  - `cells`: `list[CellRecord] | None`
  - `center`: `Coordinates | None`
  - `aggregate_2m`: `bool` (default: `True`)
- **Response Schema (`CompareResponse`)**:
  - `dsatur`: `SolverResult` (includes `chi_heuristic`, `runtime_ms`, `validation`, `channel_reuse_breakdown`: `dict[int, int]`)
  - `welsh_powell`: `SolverResult` (includes `chi_heuristic`, `runtime_ms`, `validation`, `channel_reuse_breakdown`: `dict[int, int]`)
  - `agreement`: `bool`
  - `educational_disclaimer`: `EducationalDisclaimer`

---

## Code Layout
- `app.py`: FastAPI endpoints and request routing.
- `data_service.py`: OpenCellID client, caching, radio filtering, 2m site clustering, FPS sampling, radius fallback logic.
- `graph_engine.py`: Haversine metric, graph builder, diagnostics, DSatur, Welsh-Powell, exact B&B solver, 100% edge & boundary validator.
- `schemas.py`: Pydantic V2 schemas for all requests, responses, models, and metadata.
- `static/index.html`: Web interface layout (Graph Explorer tab, Map tab, Side-by-Side card, Vertex Inspector, controls).
- `static/app.js`: Interactive application logic, force simulation, Leaflet map integration, event listeners, API client.
- `static/style.css`: Clean modern CSS stylesheet.
- `tests/`: Existing unit test suite (458 tests).
- `tests/e2e/`: Opaque-box E2E test suite covering Tiers 1-4.
