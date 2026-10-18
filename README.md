# SpectraMap

**Graph Coloring for Cellular Frequency Optimization**

SpectraMap is an educational web application that demonstrates how graph-coloring
algorithms can model cellular frequency allocation. It fetches available cell records
near your location via the OpenCellID API, builds an interference graph, and runs
DSatur and Welsh–Powell to assign abstract frequency groups with zero conflicts.

## What it does

1. Requests your browser location and centers a Leaflet map on it.
2. Fetches nearby cell records automatically from OpenCellID (no file import needed).
3. Lets you choose a search radius (500 m – 5 km).
4. On **Optimize Frequencies**, builds an interference graph and runs both algorithms.
5. Displays color-coded results, algorithm comparison, conflict metrics, and optional
   interference edges.

> **Note:** Results are a simplified educational model, not a certified RF plan.
> Cell records are community-contributed observations, not a complete tower inventory.
> Assigned colors are abstract frequency groups, not real licensed frequencies.

## Technology stack

| Part | Technology |
|---|---|
| Backend / API | Python + FastAPI |
| Graph algorithms | NetworkX |
| Data normalization | Pandas |
| Frontend | HTML + CSS + Vanilla JavaScript |
| Map | Leaflet |
| Cell data | OpenCellID area API |
| Cache | Local files |
| Tests | pytest |

## Project structure

```
SpectraMap/
├── app.py              # FastAPI app: static serving + API routes
├── schemas.py          # Pydantic request models
├── data_service.py     # OpenCellID fetching, geodesic math, cache
├── graph_engine.py     # Graph construction, DSatur, Welsh–Powell, validator
├── requirements.txt
├── data/               # App-managed cache (gitignored)
├── static/
│   ├── index.html      # Responsive dashboard layout & controls
│   ├── style.css       # Dark theme, glassmorphism, responsive styles
│   └── app.js          # Leaflet map, API integration, graph visualization
├── tests/
│   ├── test_app.py           # API endpoint integration tests
│   ├── test_data_service.py  # Data validation, haversine, cache tests
│   └── test_graph_engine.py  # Graph modeling, coloring, validation tests
├── docs/
├── .env.example
└── .gitignore
```

## Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd SpectraMap

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
# Edit .env and set OPENCELLID_API_KEY=<your key>

# 5. Run the server
uvicorn app:app --reload

# 6. Open http://localhost:8000 in your browser
```

Obtain a free OpenCellID API key at https://opencellid.org.

## Running Tests

Run the complete test suite (50 automated unit and integration tests):

```bash
pytest -v
```

## Attribution

Cell tower data from [OpenCellID](https://opencellid.org), licensed under
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) / [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

## Project status

**Phase 1–7 Complete & Verified:**
- FastAPI backend with input validation and local caching.
- NetworkX interference graph generation and mathematical distance modeling.
- Welsh-Powell and DSATUR graph coloring algorithms with independent collision validation.
- Interactive Leaflet frontend with dark glassmorphism styling, live tower marker popups, interference lines, and comparison scoreboard.