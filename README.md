# SpectraMap

**Production-Grade Geospatial Graph Coloring & Cellular Frequency Allocation Platform**

SpectraMap is a high-performance, interactive geospatial web application that formulates cellular channel assignment as an undirected graph vertex coloring problem. It ingests real-world base station transceiver records from OpenCellID (or offline demo grids), builds an interference graph based on spatial circular coverage overlap ($d(u,v) \le r_u + r_v$), and executes **DSatur**, **Welsh–Powell**, and an **Exact Branch-and-Bound** solver to compute zero-collision frequency channel allocations.

---

## 1. Application Overview

Radio frequency (RF) spectrum is a scarce, high-value public resource auctioned to telecommunications operators. Because available frequency channels are strictly finite, transmitters operating in the same geographic region must reuse channels without causing co-channel interference. If two nearby base stations transmit on the identical frequency channel and their electromagnetic coverage envelopes collide, severe interference occurs—resulting in dropped calls and signal degradation.

SpectraMap transforms this geospatial coordination problem into an exact graph-theoretic formulation:
- **Vertices ($V$):** Physical cellular transceivers with latitude $\phi_i$, longitude $\lambda_i$, and coverage radius $r_i$.
- **Edges ($E$):** Undirected interference links between transceiver pairs whose coverage disks overlap:
  $$d(u, v) \le r_u + r_v$$
  where $d(u, v)$ is the great-circle geodesic distance calculated using the spherical Haversine formula ($R = 6,371,000\text{ m}$).
- **Colors ($k$):** Discrete non-interfering frequency channel assignments $f_1, f_2, \dots, f_k$.
- **Validity Invariant:** For every edge $(u, v) \in E$, $c(u) \ne c(v)$.
- **Independent Validation:** Post-allocation audit independently traverses every edge in $E$ to mathematically verify zero adjacent channel collisions.

---

## 2. Main Features

- **Map-First Visualization Workspace:** Fullscreen Leaflet map with vivid OpenStreetMap cartography, customized DivIcon tower markers, translucent coverage discs, and high-visibility conflict vectors.
- **Selective Dynamic Conflict Graph:** Luminous rose-crimson conflict lines connect only transceivers within verified overlap range ($d(u,v) \le r_u + r_v$). Distant non-interfering towers have zero edges.
- **Focused Sub-Graph Inspection:** Clicking any tower highlights its localized conflict sub-graph in electric blue, highlights conflicting neighbors in warning amber, and dims non-incident nodes and edges.
- **Dual Heuristic & Exact Solver Engine:**
  - **DSatur (Brélaz, 1979):** Dynamically prioritizes vertices with maximum saturation degree $\text{sat}(v)$, achieving near-optimal chromatic numbers.
  - **Welsh–Powell (1967):** Greedy maximal independent set coloring sorted by descending static degree $\Delta(v)$.
  - **Exact DSatur Branch-and-Bound ($N \le 25$):** Pre-colors maximum cliques $\omega(G)$ to break $k!$ permutation symmetry and proves the exact chromatic number $\chi(G)$ with a strict 500 ms deadline clock.
- **Theoretical Bounds Verification:** Formally tests Brooks' Theorem ($\chi(G) \le \Delta(G) + 1$) and the Clique Lower Bound ($\chi(G) \ge \omega(G)$).
- **8-Card Live Analytics Dashboard:** Real-time metrics for Towers $|V|$, Conflicts $|E|$, Max Degree $\Delta(G)$, Graph Density $\rho$, 4G/5G Ratio, Channels Used $k$, Solver Latency (ms), and Independent Validation Status.
- **Side-by-Side Algorithm Benchmark Card:** Direct comparison of DSatur vs Welsh-Powell channel counts, runtime speedup, and channel savings.
- **Contextual Slide-Over Vertex Inspector:** Drawer displaying geographic coordinates, reported range, technology, MCC/MNC, LAC, degree $\deg(v)$, adjacent conflict neighbors, and blocked frequency channels.
- **Dock Minimization & Responsive Controls:** Left Analysis Control sidebar collapses with `◀` / `☰ Controls` toggle; bottom Analytics Dock minimizes with `✕` / `📊 Show Results` button to unobstructed map views.
- **Offline Demo Grid Fallback:** Built-in simulated 6-cell cellular cluster for instant offline demonstration without requiring external API keys.

---

## 3. Technology Stack

- **Backend Framework:** FastAPI 0.143+ (Python 3.11 / 3.12 / 3.14 compatible)
- **ASGI Production Server:** Uvicorn (standard with uvloop and httptools)
- **Graph Algorithms & Modeling:** NetworkX 3.7
- **Schema Validation & Parsing:** Pydantic
- **HTTP Client:** HTTPX 0.28+ (asynchronous OpenCellID ingestion)
- **Environment Management:** python-dotenv
- **Frontend Architecture:** Vanilla JavaScript (ES6+), Leaflet 1.9.4, Modern CSS3 Glassmorphism
- **Automated Test Suite:** Pytest 9.1+ with AnyIO and FastAPI TestClient

---

## 4. Project Directory Structure

```text
SpectraMap/
├── app.py                     # FastAPI application, CORS, security headers & REST routes
├── data_service.py            # OpenCellID ingestion, Haversine geodesic math, local cache
├── graph_engine.py            # NetworkX graph builder, DSatur, Welsh-Powell, Exact B&B, Validator
├── schemas.py                 # Pydantic request & response validation schemas
├── requirements.txt           # Production dependencies with version bounds
├── .env.example               # Safe environment variable configuration template
├── .gitignore                 # Comprehensive repository exclusions
├── Dockerfile                 # Multi-stage, non-root production container
├── docker-compose.yml         # Container orchestration specification
├── pytest.ini                 # Pytest test discovery & runner configuration
├── README.md                  # System architecture, deployment & operational manual
├── LICENSE                    # MIT open-source license specification
├── data/                      # App-managed local JSON cache (gitignored)
├── docs/                      # Architectural specifications & PRDs
│   ├── SpectraMap_Final_PRD.md
│   └── SpectraMap_Final_System_Architecture.md
├── static/
│   ├── index.html             # Accessible, responsive single-page application
│   ├── style.css              # Custom dark glassmorphic styling & responsive layouts
│   └── app.js                 # Leaflet controller, graph rendering, state machine
└── tests/                     # 190+ automated empirical unit & integration tests
    ├── test_app.py
    ├── test_graph_engine.py
    ├── test_data_service.py
    ├── test_m3_frontend_structure.py
    ├── test_m3_static_serving.py
    └── stress_solvers.py
```

---

## 5. Prerequisites

- **Python:** Version 3.11, 3.12, or 3.14.
- **Package Manager:** `pip` (Python package installer).
- **Git:** 2.30+ installed.
- **Docker & Docker Compose (Optional):** For containerized deployment.
- **OpenCellID API Key (Optional):** Required only for fetching live external cell towers. Offline Demo Grid runs with zero external credentials.

---

## 6. Installation & Local Development Setup

### Step 1: Clone Repository
```bash
git clone https://github.com/dheerajrai-dev/SpectraMap.git
cd SpectraMap
```

### Step 2: Create & Activate Virtual Environment
```bash
# On Windows (PowerShell):
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy the template to create a local `.env` file:
```bash
# On Windows (PowerShell):
Copy-Item .env.example .env

# On Linux / macOS:
cp .env.example .env
```
Open `.env` in your editor and configure your settings:
```ini
OPENCELLID_API_KEY=your_opencellid_api_key_here
ENVIRONMENT=development
LOG_LEVEL=INFO
PORT=8000
CORS_ORIGINS=*
```
*(If you do not have an OpenCellID API key, you can still use the built-in "⚡ Demo Grid" immediately without any key).*

### Step 5: Start Development Server
```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```
Open your browser and navigate to: **`http://localhost:8000`**

---

## 7. Data Storage & Cache Architecture

SpectraMap employs a local, file-based caching layer under the `data/` directory (gitignored):
- **Cache File Format:** `data/cache_{latmin}_{lonmin}_{latmax}_{lonmax}.json`
- **Path Traversal Protection:** All bounding box coordinates are sanitized to alphanumeric characters, and target paths are verified to remain within the `data/` directory root.
- **Time-to-Live (TTL):** Cached query tiles have an automatic 24-hour expiration window with graceful offline fallback if the upstream API is unavailable.
- **Zero Database Requirement:** The application is stateless and lightweight, requiring no external relational or NoSQL database servers.

---

## 8. REST API Documentation

### System Endpoints
- `GET /` — Serves the frontend single-page application (`static/index.html`).
- `GET /api/health` — Production healthcheck probe returning application operational status and readiness.
- `GET /api/status` — Backward-compatible application readiness check.

### Transceiver Data Endpoints
- `GET /api/towers` — Ingests and returns cell transceivers within a geographic radius or bounding box.
  - Parameters: `lat`, `lon`, `radius_m` (default 1500m, max 5000m), `radios` (`4G`, `5G`), `limit` (10–200), `aggregate_2m` (bool).
- `GET /api/cells` — Backward-compatible alias for tower query.

### Graph Optimization Endpoints
- `POST /api/graph/build` — Constructs the NetworkX interference graph from transceivers and computes topological metrics ($|V|$, $|E|$, $\Delta(G)$, $\rho$).
- `POST /api/optimize` — Runs frequency allocation heuristics (DSatur, Welsh-Powell, or Both) and returns conflict-free channel assignments with validation.
- `POST /api/compare` — Executes both DSatur and Welsh–Powell simultaneously on the identical graph topology and returns a comparative performance breakdown.

---

## 9. Automated Testing & Verification

Run the comprehensive automated test suite with `pytest`:

```bash
# Run all unit, integration, and mathematical boundary tests
python -m pytest -v

# Run frontend DOM and structural verification tests
python -m pytest tests/test_m3_frontend_structure.py -v

# Run graph coloring algorithm & theoretical bounds tests
python -m pytest tests/test_graph_engine.py -v
```

All unit and integration tests run completely offline and finish in under 3 seconds.

---

## 10. Production Deployment

### Option A: Docker Deployment (Recommended)

1. Build and launch with Docker Compose:
```bash
docker compose up -d --build
```
2. Verify container status and health:
```bash
docker compose ps
curl http://localhost:8000/api/health
```
3. View production container logs:
```bash
docker compose logs -f
```

### Option B: Linux Systemd + Gunicorn / Uvicorn Service

1. Create a system user and deploy files to `/opt/spectramap`.
2. Install production dependencies into a clean virtual environment:
   ```bash
   /opt/spectramap/.venv/bin/pip install -r /opt/spectramap/requirements.txt
   ```
3. Create `/etc/systemd/system/spectramap.service`:
   ```ini
   [Unit]
   Description=SpectraMap Cellular Frequency Optimization Service
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/opt/spectramap
   EnvironmentFile=/opt/spectramap/.env
   ExecStart=/opt/spectramap/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 4
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
4. Enable and start service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now spectramap
   ```

### Option C: Nginx Reverse Proxy Configuration

```nginx
server {
    listen 80;
    server_name spectramap.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 11. Security Architecture & Considerations

- **Zero Hardcoded Credentials:** Real API keys and secrets are strictly excluded from version control and loaded exclusively via environment variables.
- **Git Protection:** `.gitignore` excludes `.env`, `data/`, `*.log`, `.venv/`, and temporary build artifacts.
- **Path Traversal Mitigation:** Cache file resolution uses strict character whitelisting and validates absolute canonical paths against the target data directory.
- **Defensive Security Headers:** Automatically injected on all HTTP responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `X-XSS-Protection: 1; mode=block`
- **Cross-Site Scripting (XSS) Prevention:** Frontend renders dynamic data attributes using DOM `textContent` and an `escapeHtml` utility for any interpolated HTML template strings.
- **Non-Root Container Execution:** Docker image runs under an unprivileged `appuser` (UID 1000).
- **Query Parameter Boundary Validation:** Pydantic and FastAPI `Query` schemas strictly enforce ranges on all inputs (`lat`: [-90, 90], `lon`: [-180, 180], `radius_m`: [50, 5000], `limit`: [10, 200]).

---

## 12. Troubleshooting

| Issue | Root Cause | Solution |
|---|---|---|
| **HTTP 503 "OpenCellID API key is not configured"** | Missing `OPENCELLID_API_KEY` in `.env` | Set key in `.env`, or click **"⚡ Demo Grid"** in the top bar for instant offline testing. |
| **"Zero valid tower records available"** | Requested search coordinates have no cellular masts | Choose preset *"South Delhi"* or expand the search radius slider to 2500m. |
| **Port 8000 already in use** | Another instance or process is occupying port 8000 | Run on a different port: `uvicorn app:app --port 8080`, or kill the occupying process. |
| **Missing Module Errors** | Virtual environment not activated or dependencies not installed | Activate `.venv` and run `pip install -r requirements.txt`. |

---

## 13. License & Attribution

- **Application License:** MIT License.
- **Cellular Data Attribution:** Crowd-sourced cellular base station data provided by [OpenCellID](https://opencellid.org), licensed under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
- **Map Tiles Attribution:** Base cartography &copy; [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
