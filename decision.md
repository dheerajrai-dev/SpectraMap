# SpectraMap — Engineering & Product Decision Log

This log documents major architectural, mathematical, data-modeling, and UI/UX decisions made throughout the lifecycle of the SpectraMap project.

---

## Decision 1: Visualize Frequency Reuse via Colored Coverage Regions and Omit Edge Lines from the Main Geographic Map
* **Date:** 2026-10-18
* **Status:** Accepted (Phase 0/1 Architecture)
* **Context & Problem:** 
  A standard graph visualization draws edges as lines between adjacent vertices. However, when overlaid on a geographic map with 50–100+ dense cellular base stations, drawing pairwise interference edges creates an unreadable red "spiderweb" mesh (over 5,000 overlapping polylines in dense clusters). This obscures OpenStreetMap streets, landmarks, and antenna positions.
* **Alternatives Considered:**
  1. *Draw all graph edges as polylines on the geographic map (superseded).* Caused extreme visual clutter and map illegibility.
  2. *Color individual map marker dots only.* Lost spatial intuition for why two distant towers can reuse a channel while two overlapping towers cannot.
  3. *Color estimated coverage circles with semi-transparent fills and crisp outlines, omitting edge lines from the main map.*
* **Reason for Selected Option:** 
  In real cellular radio networks, frequency reuse is understood geographically through coverage areas, not physical links between towers. By filling each cell's estimated coverage circle ($r_i$) with its assigned frequency group color ($f_k$) at calibrated opacity (~0.18) with a distinct border, users immediately see which coverage zones overlap and why adjacent overlapping cells must receive different colors. Graph edges remain available for inspection via the contextual Vertex Inspector and the dedicated Graph Topology Canvas view.
* **Consequences & Trade-offs:** 
  Multiple large overlapping circles can create optical color blending if opacity is too high; opacity must be strictly kept between 0.12 and 0.22 with zero default fill stacking, and selective highlighting on click/hover.
* **Affected Files:** `static/app.js`, `static/style.css`, `static/index.html`.
* **Verification:** Visual inspection in browser; verified distinct coverage boundaries with no edge polylines on the geographic view.

---

## Decision 2: Stable, Visible Cell Labeling Strategy (A, B, C... Scheme)
* **Date:** 2026-10-18
* **Status:** Accepted
* **Context & Problem:** 
  OpenCellID identifiers (e.g., `UMTS_404_10_33013_7554805`) are too long and technical to display legibly on a map marker. Unlabeled markers forced the user to click each marker individually to identify which cell belonged to which frequency group or inspector row.
* **Alternatives Considered:**
  1. *Raw Cell ID numbers (e.g. #7554805).* Cluttered the map with 7-digit numbers at normal zoom.
  2. *Only showing labels in popups upon click.* Made cross-referencing between the map, comparison scoreboard, and neighbor list frustrating.
  3. *Stable compact alphabetic / short alphanumeric labels (A, B, C... Z, AA, AB... or A1, A2).*
* **Reason for Selected Option:** 
  Assigning stable, compact sequence labels ($A, B, C \dots$) sorted deterministically by latitude/longitude allows users to cross-reference any cell instantly between the map, the scoreboard, and the inspector drawer without clicking. The full technical Cell ID, MCC, MNC, and LAC remain available in the detail panel.
* **Consequences & Trade-offs:** 
  When the search radius or center changes, labels must be regenerated deterministically so they remain stable throughout an optimization run.
* **Affected Files:** `static/app.js`, `static/style.css`, `schemas.py`.
* **Verification:** Label rendering verified on map markers; inspected contrast against tile backgrounds.

---

## Decision 3: Minimum-Color Objective & Bounded Exact Solver Feasibility
* **Date:** 2026-10-18
* **Status:** Accepted
* **Context & Problem:** 
  The primary mathematical objective of cellular frequency planning is to minimize spectrum usage by finding the chromatic number $\chi(G)$ of the interference graph. Heuristics like Welsh–Powell and DSatur are greedy algorithms that run in polynomial time ($O(V^2)$), but neither guarantees a proven minimum on every graph. A zero-conflict coloring is not necessarily minimal.
* **Alternatives Considered:**
  1. *Heuristics only (Welsh–Powell and DSatur).* Fast and scalable, but cannot prove mathematical optimality or teach users the difference between heuristic approximation and exact chromatic number.
  2. *Full unconstrained Exact Solver (Integer Linear Programming or Backtracking).* General graph coloring is NP-hard. Running an exact solver on 100+ dense vertices could freeze the Python process or timeout.
  3. *Dual heuristic comparison + Bounded Exact Solver with strict limits.* Implement an exact Branch-and-Bound / DSatur exact solver bounded to $N \le 25$ vertices with a 500 ms timeout.
* **Reason for Selected Option:** 
  For small or medium graphs ($N \le 25$), the exact solver computes and proves the true chromatic number $\chi(G)$, providing immense educational value by showing whether DSatur achieved the exact minimum. For larger graphs ($N > 25$), the application clearly reports `Minimum not proven (Heuristic result)` and presents the best heuristic among Welsh–Powell and DSatur. This prevents any dishonest claims of optimality.
* **Consequences & Trade-offs:** 
  Requires building a clean branch-and-bound exact coloring function in `graph_engine.py` with unit tests for known graph families ($K_n, C_{2k+1}$, bipartite graphs).
* **Affected Files:** `graph_engine.py`, `schemas.py`, `app.py`, `static/app.js`.
* **Verification:** Unit tests in `tests/test_graph_engine.py` verifying exact chromatic numbers on cycles, cliques, and bipartite topologies.

---

## Decision 4: Frontend Technology Stack — Retaining Vanilla JS with Modular Architecture vs React
* **Date:** 2026-10-18
* **Status:** Accepted (Evidence-Based Decision)
* **Context & Problem:** 
  The project requires a polished, map-first, responsive geospatial analytics workspace with Leaflet, dynamic SVG/Canvas layers, slide-over inspector, and side-by-side metric tables. We evaluated whether migrating to React + Vite + TypeScript was justified.
* **Alternatives Considered:**
  1. *Full React + Vite + TypeScript migration.* Requires adding `package.json`, Node.js runtime, build pipelines, React-Leaflet wrappers, and complex prop/state wiring. Introduces build friction, increases deployment complexity, and creates impedance mismatch with Leaflet's imperative DOM manipulation.
  2. *Refactored Modern Vanilla JavaScript (ES6+), Pure CSS Custom Properties, and Native Leaflet.* Zero build steps, instant browser refresh, single FastAPI server deployment, direct imperative control over Leaflet and HTML5 Canvas, lightweight (~40 KB total assets).
* **Reason for Selected Option:** 
  The current Vanilla JS architecture with modular separation of state (`state` store, layer groups, event buses) easily supports the required reactive UI patterns without the overhead, fragility, and build complexity of an npm/Vite toolchain. In accordance with the project's simplicity guidelines, Vanilla JS provides superior performance and easier inspection.
* **Consequences & Trade-offs:** 
  State updates must be kept strictly coordinated via dedicated render functions rather than automatic React declarative re-renders.
* **Affected Files:** `static/index.html`, `static/style.css`, `static/app.js`.
* **Verification:** 60fps interaction in Chrome DevTools MCP with zero console warnings and instant load times.

---

## Decision 5: Geolocation Accuracy, Explicit State Display & Manual Fallback
* **Date:** 2026-10-18
* **Status:** Accepted
* **Context & Problem:** 
  Previously, the application defaulted silently to South Delhi (`28.5224, 77.1906`) without requesting browser GPS permission on page load. Users outside South Delhi saw "no towers near me" or assumed the app was broken.
* **Alternatives Considered:**
  1. *Auto-IP geolocation.* Inaccurate (often offset by 20–50 km in cellular/ISP gateways) and requires external third-party API dependencies.
  2. *Passive map centering without prompt.* Left users wondering why the map opened in New Delhi.
  3. *Polite startup GPS prompt + Explicit Location Status Pill + Seamless Manual Fallback.*
* **Reason for Selected Option:** 
  On startup, an informative banner requests browser GPS. If granted, the map smoothly flies to the user's true coordinates. The top bar prominently displays an indicator pill: `GPS Active`, `Manual Center`, or `Preset Location`. If denied or unavailable, the user can freely drag the center pin, click anywhere on the map, or select a high-density demo preset.
* **Consequences & Trade-offs:** 
  Requires handling browser permission states (`prompt`, `granted`, `denied`) gracefully without blocking the UI.
* **Affected Files:** `static/app.js`, `static/index.html`, `static/style.css`.
* **Verification:** Tested in browser under both GPS permission granted and permission denied states.

---

## Decision 6: Coverage-Overlap Mathematical Graph Model & Range Policy
* **Date:** 2026-10-18
* **Status:** Accepted
* **Context & Problem:** 
  Physical wireless interference is a continuous electromagnetic phenomenon depending on carrier frequency, power, antenna azimuth, beam tilt, and terrain. In this discrete educational project, a simplified proxy model is required.
* **Policy Implemented:** 
  An undirected graph edge $(u, v) \in E$ is formed if and only if $d(u, v) \le r_u + r_v$, where $d(u, v)$ is geodesic distance computed via the Haversine formula on a spherical Earth ($R = 6,371,000$ m).
  - If a cell record lacks a reported range or has $r_i \le 0$, a documented default estimate ($r = 800$ m for LTE, $1000$ m for GSM, $500$ m for 5G NR) is assigned with a clear "Estimated / Default" metadata flag in the inspector.
  - The UI explicitly explains that geometric circle overlap is a mathematical modeling convention, not certified physical interference.
* **Consequences & Trade-offs:** 
  Models worst-case omnidirectional overlap. Directional sector azimuths are noted as a limitation.
* **Affected Files:** `data_service.py`, `graph_engine.py`, `docs/SpectraMap_Final_PRD.md`.
* **Verification:** Unit tests verifying known pairwise overlaps and distance calculations in `tests/test_graph_engine.py`.

---

## Decision 7: Operator Identification via MCC/MNC & Disclaimer on Frequency Groups
* **Date:** 2026-10-18
* **Status:** Accepted
* **Context & Problem:** 
  OpenCellID records provide raw MCC (Mobile Country Code) and MNC (Mobile Network Code) integers (e.g., MCC 404/405 for India) without carrier brand names. Additionally, first-time users frequently confuse abstract graph colors (e.g. Group 1, Group 2) with real physical carrier frequencies in MHz (e.g. 1800 MHz, 2100 MHz).
* **Policy Implemented:** 
  - Standardized MCC/MNC lookup dictionary for major operators (Airtel, Reliance Jio, Vodafone Idea / Vi, BSNL/MTNL in India; and major international codes).
  - Explicit disclaimer in both the legend and the inspector drawer: *"Colors represent abstract frequency reuse groups (f1, f2, ...) derived from graph color theory, not physical carrier spectrum in MHz."*
* **Affected Files:** `data_service.py`, `schemas.py`, `static/app.js`.
* **Verification:** Tested with live OpenCellID records in Delhi (MCC 404, MNC 10/11/45/86).
