# SpectraMap v2.0

**Spatial Graph Coloring for Cellular Frequency Optimization**

SpectraMap is an educational, interactive web application that demonstrates how graph theory models simplified cellular frequency allocation. It ingests geographic cell-tower records, constructs a selective interference graph based on circular coverage overlap ($d(u,v) \le r_u + r_v$), and runs both **DSatur** and **Welsh–Powell** vertex-coloring heuristics to allocate non-conflicting frequency groups, accompanied by independent conflict validation.

---

## 1. Problem Statement & Mathematical Formulation

Wireless carriers purchase expensive radio spectrum at national auctions. Because spectrum is strictly finite, frequency channels must be reused geographically. However, if two nearby transmitters operate on the identical frequency channel and their coverage areas overlap, severe co-channel interference occurs.

SpectraMap maps this spatial problem into an undirected conflict graph $G = (V, E)$:

1. **Vertices ($V$):** Each localized base station transceiver ($v \in V$) with coordinates $(\phi_i, \lambda_i)$ and coverage radius $r_i$.
2. **Edges ($E$):** An undirected interference edge $(u, v) \in E$ exists if and only if the spherical Haversine geodesic distance satisfies:
   $$d(u, v) \le r_u + r_v$$
   (closed disk overlap model).
3. **Colors ($c(v)$):** Discrete frequency groups $f_1, f_2, \dots, f_k$. Valid coloring requires:
   $$\forall (u, v) \in E, \quad c(u) \ne c(v)$$
4. **Independent Validation:** Every edge is verified separately after optimization. Any edge with $c(u) == c(v)$ is reported as a collision.

> **Educational Model Disclaimer:** SpectraMap is a discrete mathematical model designed for academic and demonstrative purposes. It does not replace carrier-grade RF planning, does not simulate 3-sector 120° directional antennas, SINR thresholds, or terrain shadow fading, and cannot guarantee the elimination of physical radio interference.

---

## 2. Solvers & Theoretical Bounds

SpectraMap implements and compares three complementary coloring algorithms on the identical graph:

- **DSatur (Brélaz, 1979):** Dynamically tracks the saturation degree $\text{sat}(v)$ (number of distinct colors assigned to neighbors). Selects uncolored vertices with highest saturation first, breaking ties by uncolored degree.
- **Welsh–Powell (1967):** Sorts vertices statically by descending degree $\Delta(v)$ and colors maximal independent sets in sequential greedy passes ($O(V \log V + E)$).
- **Exact DSatur Branch-and-Bound (Bounded to $N \le 25$):** Finds the exact chromatic number $\chi(G)$ by pre-coloring a maximum clique $\omega(G)$ at the root to break color permutation symmetry ($k!$ reduction), running with a 500 ms monotonic deadline clock.
- **Theoretical Bounds:**
  - **Clique Lower Bound:** $\chi(G) \ge \omega(G)$.
  - **Brooks' Theorem Upper Bound:** $\chi(G) \le \Delta(G) + 1$.

---

## 3. Technology Stack

- **Backend:** Python 3.14 + FastAPI
- **Graph Engine:** NetworkX 3.7
- **Distance Metric:** Great-circle geodesic distance via spherical Haversine formula (Earth radius $R = 6,371,000$ m)
- **Frontend:** Vanilla HTML5, CSS3 (Glassmorphism & analytical typography), JavaScript (ES6+), Leaflet 1.9.4
- **Topology View:** HTML5 Canvas force-directed graph renderer with HiDPI Retina support
- **Data Source:** OpenCellID (ODbL / CC BY-SA 4.0) with local file caching and simulated grid fallback
- **Test Framework:** Pytest 9.1.1 (191 automated unit and integration tests)

---

## 4. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health and readiness check (`{"status": "ok", "app": "SpectraMap", "version": "2.0"}`) |
| `GET` | `/api/status` | Backward-compatible status check |
| `GET` | `/api/towers` | Query towers by `(lat, lon, radius_m)` or bounding box `(west, south, east, north)` |
| `GET` | `/api/cells` | Backward-compatible tower query |
| `POST` | `/api/graph/build` | Construct NetworkX interference graph from tower records ($d \le r_1 + r_2$) |
| `POST` | `/api/optimize` | Run DSatur, Welsh-Powell, or dual optimization with independent conflict validation |
| `POST` | `/api/compare` | Run side-by-side benchmark comparison on identical graph topology |

---

## 5. Project Structure

```text
SpectraMap/
├── app.py                     # FastAPI application & REST routing
├── data_service.py            # OpenCellID ingestion, Haversine geodesic math, local cache
├── graph_engine.py            # NetworkX graph builder, DSatur, Welsh–Powell, Exact B&B, Validator
├── schemas.py                 # Pydantic request & response validation schemas
├── requirements.txt           # Pinned dependencies
├── pytest.ini                 # Pytest configuration
├── README.md                  # System architecture, formulation & viva guide
├── data/                      # App-managed local cache (real tower clusters)
├── static/
│   ├── index.html             # Responsive map-first workspace
│   ├── style.css              # Glassmorphism dark UI, responsive layout
│   └── app.js                 # Leaflet controller, Canvas graph explorer, vertex inspector
├── docs/
│   ├── SpectraMap_PRD_v2.md
│   ├── SpectraMap_System_Architecture_v2.md
│   └── SpectraMap_Frontend_Specification_v2.md
└── tests/
    ├── test_app.py            # API endpoint integration tests
    ├── test_data_service.py   # Coordinate handling, Haversine, tiling tests
    ├── test_graph_engine.py   # Graph algorithms, heuristic invariants, exact solver tests
    ├── test_phase1_validation.py # Deep mathematical boundary and coordinate tests
    └── test_v2_spec.py        # v2 specification and endpoint verification tests
```

---

## 6. Setup & Execution

### 1. Environment Setup
```bash
# Activate your virtual environment
.venv\Scripts\activate          # Windows PowerShell / CMD
# source .venv/bin/activate     # Linux / macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create `.env` from `.env.example`:
```ini
OPENCELLID_API_KEY=your_opencellid_api_key_here
```
*(Note: SpectraMap includes local cached datasets for South Delhi, Connaught Place, and Mumbai, as well as an offline demo grid generator).*

### 3. Start the Server
```bash
uvicorn app:app --reload --port 8000
```
Open your browser at: **`http://localhost:8000`**

### 4. Run Automated Test Suite
```bash
pytest -v
```
All 191 tests run offline in under 3 seconds.

---

## 7. Interactive Viva Demonstration Script

1. **Geographic Selection:** Choose preset *"South Delhi (100+ Live Towers)"* or click *"⚡ Demo Grid"*.
2. **Tower Ingestion:** Click *"📡 Fetch Towers"*. Towers appear with stable alphabetic labels (`A`, `B`, `C`...).
3. **Graph Construction:** The interference graph is built using $d(u,v) \le r_u + r_v$. Notice that the graph is selective—distant towers have no edge lines connecting them.
4. **Topology Exploration:** Switch to the *"🕸️ Graph Topology"* tab to inspect the force-directed canvas. Node size reflects graph degree $\Delta(v)$.
5. **Sensitivity Analysis:** Adjust the *"Coverage Radius Override"* slider from 0 to 1200m and watch the edge count and graph density increase as coverage disks expand.
6. **Heuristic Execution:** Click *"⚡ Optimize Frequencies"* with Dual Comparison. Both DSatur and Welsh-Powell color the graph with zero conflicts.
7. **Solver Benchmark:** Click *"⚖️ Compare Solvers"* to view the side-by-side performance matrix, runtime in milliseconds, direct channel agreement percentage, and theoretical bounds guarantees ($\chi(G) \ge \omega(G)$).
8. **Contextual Inspector:** Click any tower on the map or graph. The slide-over drawer shows its coordinates, degree, assigned channel, blocked neighbor channels, and step-by-step allocation rationale.