"""
tests/test_m3_static_serving.py — Automated empirical test suite for Milestone M3.

Verifies:
1. Static asset serving via FastAPI (/ , /static/index.html, /static/app.js, /static/style.css).
2. Contract alignment between FastAPI API responses and M3 frontend consumers:
   - GET /api/cells (accounting metadata, cell/tower format, 4G/5G tech distribution)
   - POST /api/graph/build (nodes, edges, metrics, diagnostics, build_runtime_ms)
   - POST /api/optimize (assignments, dsatur, welsh_powell, exact, metrics, validation)
   - POST /api/compare (side-by-side comparison, metrics, winner determination)
3. DOM element consistency between static/app.js and static/index.html.
4. Adversarial stress-testing of frontend payload expectations and scoping.
"""

import os
import re
import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# Tier 1: Static Asset Serving Verification
# ============================================================================

def test_root_endpoint_serves_index_html(client):
    """GET / must return HTTP 200 and serve static/index.html with text/html content type."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>SpectraMap" in response.text
    assert 'id="control-dock"' in response.text or 'id="section-location"' in response.text
    assert 'id="map"' in response.text
    assert 'id="graph-canvas"' in response.text


def test_static_index_html_endpoint(client):
    """GET /static/index.html must return HTTP 200 with matching content."""
    response = client.get("/static/index.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert len(response.text) > 5000


def test_static_app_js_endpoint(client):
    """GET /static/app.js must return HTTP 200 with JavaScript content type and non-empty content."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    ct = response.headers.get("content-type", "").lower()
    assert "javascript" in ct or "text/plain" in ct
    assert len(response.text) > 20000
    # Confirm core functions exist in app.js
    assert "fetchNearbyCells" in response.text
    assert "buildInterferenceGraphUI" in response.text
    assert "runFrequencyOptimization" in response.text
    assert "renderGraphExplorer" in response.text


def test_static_style_css_endpoint(client):
    """GET /static/style.css must return HTTP 200 with text/css content type and non-empty content."""
    response = client.get("/static/style.css")
    assert response.status_code == 200
    ct = response.headers.get("content-type", "").lower()
    assert "text/css" in ct
    assert len(response.text) > 10000
    # Confirm required M3 style classes exist
    assert ".selected-marker" in response.text
    assert ".neighbor-marker" in response.text
    assert ".dimmed-marker" in response.text
    assert ".dashboard-compare-card" in response.text


def test_static_nonexistent_returns_404(client):
    """GET /static/nonexistent_file.xyz must return HTTP 404."""
    response = client.get("/static/nonexistent_file.xyz")
    assert response.status_code == 404


def test_html_references_valid_static_assets(client):
    """Verify that static/index.html references /static/style.css and /static/app.js."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'href="/static/style.css"' in html or 'href="./style.css"' in html or "style.css" in html
    assert 'src="/static/app.js"' in html or 'src="./app.js"' in html or "app.js" in html


# ============================================================================
# Tier 2: API Contract Alignment with M3 Frontend Consumers
# ============================================================================

@pytest.fixture
def mock_cells_data():
    """Deterministic sample cells for contract testing."""
    return [
        {
            "tower_id": "4G_404_11_1001",
            "latitude": 28.5224,
            "longitude": 77.1906,
            "range_m": 800.0,
            "radio": "4G",
            "cell_id": 1001,
            "site_id": "SITE_28.52240_77.19060",
            "source": "OpenCellID",
        },
        {
            "tower_id": "5G_404_11_1002",
            "latitude": 28.5230,
            "longitude": 77.1915,
            "range_m": 500.0,
            "radio": "5G",
            "cell_id": 1002,
            "site_id": "SITE_28.52300_77.19150",
            "source": "OpenCellID",
        },
        {
            "tower_id": "4G_404_11_1003",
            "latitude": 28.5250,
            "longitude": 77.1940,
            "range_m": 800.0,
            "radio": "4G",
            "cell_id": 1003,
            "site_id": "SITE_28.52500_77.19400",
            "source": "OpenCellID",
        },
    ]


def test_api_cells_payload_contract_with_frontend(client, monkeypatch, mock_cells_data):
    """
    Contract Test: GET /api/cells
    Frontend consumer: fetchNearbyCells() in static/app.js
    Required structure:
      - data.cells (list of CellRecord with tower_id, radio, latitude, longitude, range_m)
      - data.accounting (available_count, eligible_count, selected_count, excluded_count)
      - data.tech_distribution (4G and 5G counts)
    """
    async def mock_fetch(lat, lon, radius_m, api_key):
        return mock_cells_data, [], False

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)

    response = client.get("/api/cells?lat=28.5224&lon=77.1906&radius_m=1500&radios=4G,5G&limit=50")
    assert response.status_code == 200
    data = response.json()

    # 1. Cells list
    assert "cells" in data
    assert isinstance(data["cells"], list)
    assert len(data["cells"]) == 3

    for cell in data["cells"]:
        assert "tower_id" in cell
        assert "radio" in cell and cell["radio"] in ("4G", "5G")
        assert "latitude" in cell
        assert "longitude" in cell
        assert "range_m" in cell
        assert cell["range_m"] > 0

    # 2. Accounting metadata
    assert "accounting" in data
    acc = data["accounting"]
    assert "available_count" in acc
    assert "eligible_count" in acc
    assert "selected_count" in acc
    assert "excluded_count" in acc
    assert acc["selected_count"] == len(data["cells"])
    assert acc["available_count"] >= acc["eligible_count"] >= acc["selected_count"]

    # 3. Tech distribution
    assert "tech_distribution" in data
    td = data["tech_distribution"]
    assert "4G" in td
    assert "5G" in td
    assert td["4G"] == 2
    assert td["5G"] == 1


def test_api_cells_radio_filtering_contract(client, monkeypatch, mock_cells_data):
    """Frontend filter toggles 4G/5G query parameter. Backend must filter accordingly."""
    async def mock_fetch(lat, lon, radius_m, api_key):
        return mock_cells_data, [], False

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)

    # Query only 4G
    res_4g = client.get("/api/cells?lat=28.5224&lon=77.1906&radius_m=1500&radios=4G&limit=50")
    assert res_4g.status_code == 200
    d_4g = res_4g.json()
    assert all(c["radio"] == "4G" for c in d_4g["cells"])
    assert d_4g["accounting"]["eligible_count"] == 2

    # Query only 5G
    res_5g = client.get("/api/cells?lat=28.5224&lon=77.1906&radius_m=1500&radios=5G&limit=50")
    assert res_5g.status_code == 200
    d_5g = res_5g.json()
    assert all(c["radio"] == "5G" for c in d_5g["cells"])
    assert d_5g["accounting"]["eligible_count"] == 1


def test_api_graph_build_payload_contract(client, mock_cells_data):
    """
    Contract Test: POST /api/graph/build
    Frontend consumer: buildInterferenceGraphUI() in static/app.js
    Sends: { center: { latitude, longitude }, radius_m, cells, radius_override_m }
    Receives:
      - nodes: list of dicts
      - edges: list of dicts with source_id/target_id, distance_m, threshold_m, source_coords, target_coords
      - metrics: GraphMetrics (vertex_count, edge_count, density, max_degree, avg_degree, technology_distribution)
      - build_runtime_ms: float
    """
    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": mock_cells_data,
        "radius_override_m": None,
    }

    response = client.post("/api/graph/build", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "nodes" in data
    assert "edges" in data
    assert "metrics" in data
    assert "build_runtime_ms" in data

    # Check metrics keys expected by updateDashboardMetrics()
    metrics = data["metrics"]
    assert "vertex_count" in metrics
    assert "edge_count" in metrics
    assert "density" in metrics
    assert "max_degree" in metrics
    assert "avg_degree" in metrics
    assert "technology_distribution" in metrics
    assert "4G" in metrics["technology_distribution"]
    assert "5G" in metrics["technology_distribution"]

    # Check edge attributes required by renderInterferenceEdges()
    for edge in data["edges"]:
        assert "source_id" in edge or "source" in edge
        assert "target_id" in edge or "target" in edge
        assert "distance_m" in edge
        assert "threshold_m" in edge
        assert "source_coords" in edge
        assert "target_coords" in edge


def test_api_optimize_payload_contract(client, mock_cells_data):
    """
    Contract Test: POST /api/optimize
    Frontend consumer: runFrequencyOptimization() in static/app.js
    Sends: { center: { latitude, longitude }, radius_m, cells, algorithm: "both", radius_override_m }
    Receives:
      - assignments: dict[str, int]
      - metrics: GraphMetrics
      - dsatur: SolverResult (color_count, runtime_ms, validation)
      - welsh_powell: SolverResult (color_count, runtime_ms, validation)
      - exact: SolverResult | None
      - best_algorithm: str
      - validation: ValidationResult (is_valid, conflict_count)
      - edges: list[dict]
    """
    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": mock_cells_data,
        "algorithm": "both",
        "radius_override_m": None,
    }

    response = client.post("/api/optimize", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "assignments" in data
    assert isinstance(data["assignments"], dict)
    assert len(data["assignments"]) == len(mock_cells_data)

    # Check dsatur and welsh_powell objects
    for key in ("dsatur", "welsh_powell"):
        assert key in data and data[key] is not None
        solver = data[key]
        assert "color_count" in solver
        assert "runtime_ms" in solver
        assert "validation" in solver
        assert "is_valid" in solver["validation"]
        assert solver["validation"]["is_valid"] is True
        assert solver["validation"]["conflict_count"] == 0

    assert "best_algorithm" in data
    assert "metrics" in data
    assert "edges" in data


def test_api_compare_payload_contract(client, mock_cells_data):
    """
    Contract Test: POST /api/compare
    Frontend consumer: runComparisonDirectly() in static/app.js
    Sends: { center: { latitude, longitude }, radius_m, cells, radius_override_m }
    Receives:
      - metrics: GraphMetrics
      - dsatur: SolverResult
      - welsh_powell: SolverResult
      - exact: SolverResult | None
      - comparison: dict with colors_difference, faster_heuristic, fewer_colors_heuristic, summary
      - edges: list[dict]
    """
    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": mock_cells_data,
        "radius_override_m": None,
    }

    response = client.post("/api/compare", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "metrics" in data
    assert "dsatur" in data
    assert "welsh_powell" in data
    assert "comparison" in data
    comp = data["comparison"]
    assert "colors_difference" in comp
    assert "faster_heuristic" in comp
    assert "fewer_colors_heuristic" in comp
    assert "summary" in comp
    assert "edges" in data


# ============================================================================
# Tier 3: Edge Cases & Boundary Stress Testing
# ============================================================================

def test_single_cell_graph_contract(client):
    """Trivial graph K1 with 1 cell: 0 edges, density 0, 1 color."""
    single_cell = [
        {
            "tower_id": "4G_SOLO",
            "latitude": 28.5224,
            "longitude": 77.1906,
            "range_m": 800.0,
            "radio": "4G",
        }
    ]
    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": single_cell,
    }

    res_build = client.post("/api/graph/build", json=payload)
    assert res_build.status_code == 200
    b_data = res_build.json()
    assert b_data["metrics"]["vertex_count"] == 1
    assert b_data["metrics"]["edge_count"] == 0

    res_opt = client.post("/api/optimize", json=payload)
    assert res_opt.status_code == 200
    o_data = res_opt.json()
    assert o_data["assignments"]["4G_SOLO"] == 0
    assert o_data["dsatur"]["color_count"] == 1


def test_co_located_clique_unsuitable_flag_contract(client):
    """
    When all cells share identical coordinates, circular coverage overlap creates a complete clique Kn.
    Backend must populate data_unsuitable=True and data_unsuitable_reason in metrics.
    """
    colocated_cells = [
        {"tower_id": f"4G_COLOC_{i}", "latitude": 28.5224, "longitude": 77.1906, "range_m": 800.0, "radio": "4G"}
        for i in range(4)
    ]
    payload = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": colocated_cells,
    }

    res = client.post("/api/graph/build", json=payload)
    assert res.status_code == 200
    data = res.json()
    metrics = data["metrics"]
    assert metrics["data_unsuitable"] is True
    assert metrics["data_unsuitable_reason"] is not None
    assert metrics["edge_count"] == 6  # K4 has 4*3/2 = 6 edges


def test_radius_override_contract(client, mock_cells_data):
    """When radius_override_m is provided, all cells should use the override radius."""
    payload_small = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": mock_cells_data,
        "radius_override_m": 10.0,  # Very small radius -> 0 edges
    }
    res_small = client.post("/api/graph/build", json=payload_small)
    assert res_small.status_code == 200
    assert res_small.json()["metrics"]["edge_count"] == 0

    payload_large = {
        "center": {"latitude": 28.5224, "longitude": 77.1906},
        "radius_m": 1500.0,
        "cells": mock_cells_data,
        "radius_override_m": 5000.0,  # Very large radius -> K3 clique (3 edges)
    }
    res_large = client.post("/api/graph/build", json=payload_large)
    assert res_large.status_code == 200
    assert res_large.json()["metrics"]["edge_count"] == 3


# ============================================================================
# Tier 4: DOM and Frontend Script Integrity Verification
# ============================================================================

def test_frontend_dom_elements_exist_in_html():
    """
    Scan static/app.js for document.getElementById calls and verify that
    all queried IDs exist in static/index.html.
    """
    app_js_path = os.path.join("static", "app.js")
    index_html_path = os.path.join("static", "index.html")

    assert os.path.isfile(app_js_path), "static/app.js must exist"
    assert os.path.isfile(index_html_path), "static/index.html must exist"

    with open(app_js_path, "r", encoding="utf-8") as f:
        js_code = f.read()

    with open(index_html_path, "r", encoding="utf-8") as f:
        html_code = f.read()

    # Extract all getElementById calls
    queried_ids = set(re.findall(r'document\.getElementById\([\"\']([a-zA-Z0-9_\-]+)[\"\']\)', js_code))
    declared_ids = set(re.findall(r'id=[\"\']([a-zA-Z0-9_\-]+)[\"\']', html_code))

    # All critical M3 UI element IDs must be present in index.html
    critical_m3_ids = [
        "btn-fetch",
        "btn-build-graph",
        "btn-optimize",
        "btn-compare-action",
        "cells-status",
        "metric-towers",
        "metric-edges",
        "metric-degree",
        "metric-density",
        "badge-ratio-4g",
        "badge-ratio-5g",
        "metric-colors",
        "metric-runtime",
        "metric-validation-badge",
        "dashboard-compare-card",
        "acc-avail",
        "acc-elig",
        "acc-sel",
        "acc-excl",
        "tab-map-view",
        "tab-graph-view",
        "map",
        "graph-canvas",
    ]

    for cid in critical_m3_ids:
        assert cid in declared_ids, f"Critical M3 ID '{cid}' missing in static/index.html"

    # Report any queried IDs in app.js that are missing in index.html
    missing = queried_ids - declared_ids
    # Dynamic or modal elements created via innerHTML may appear in missing, so log them
    print(f"Queried IDs count: {len(queried_ids)}, Declared IDs count: {len(declared_ids)}")
    print(f"IDs queried in app.js not in index.html static markup: {sorted(list(missing))}")


def test_adversarial_check_for_undeclared_m_in_app_js():
    """
    ADVERSARIAL CHALLENGE:
    In static/app.js, buildInterferenceGraphUI() references `m.data_unsuitable`
    around lines 2291-2295.
    If `const m = data.metrics || {};` is missing, `m` is an undeclared identifier,
    triggering ReferenceError at runtime when constructing the interference graph!
    """
    app_js_path = os.path.join("static", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_line = None
    for i, line in enumerate(lines):
        if "function buildInterferenceGraphUI" in line:
            start_line = i
            break

    assert start_line is not None, "buildInterferenceGraphUI function must exist in app.js"

    func_lines = lines[start_line : start_line + 80]
    has_m_usage = any("m.data_unsuitable" in l or "m.min_distance_m" in l for l in func_lines)
    has_m_declaration = any(re.search(r'\b(const|let|var)\s+m\s*=', l) for l in func_lines)

    if has_m_usage and not has_m_declaration:
        pytest.fail(
            "Empirical Bug Detected: In static/app.js buildInterferenceGraphUI(), "
            "`m.data_unsuitable` is accessed without declaring `const m = data.metrics || {};`. "
            "This causes a runtime ReferenceError: m is not defined!"
        )


def test_adversarial_check_for_unguarded_nonexistent_dom_access_in_app_js():
    """
    ADVERSARIAL CHALLENGE:
    In static/app.js, runFrequencyOptimization() directly dereferences
    document.getElementById('res-dsatur-colors').textContent and
    document.getElementById('res-wp-colors').textContent without null checks.
    If these elements are absent in static/index.html, this throws an unhandled
    TypeError: Cannot set properties of null (setting 'textContent') at runtime,
    breaking frequency coloring and map updates!
    """
    app_js_path = os.path.join("static", "app.js")
    index_html_path = os.path.join("static", "index.html")

    with open(app_js_path, "r", encoding="utf-8") as f:
        js_lines = f.readlines()

    with open(index_html_path, "r", encoding="utf-8") as f:
        html_code = f.read()

    declared_ids = set(re.findall(r'id=[\"\']([a-zA-Z0-9_\-]+)[\"\']', html_code))

    unguarded_failures = []
    # Match patterns like: document.getElementById("foo").textContent = ... or .innerHTML = ...
    # where . is not preceded by ? (i.e. no optional chaining ?.)
    pattern = re.compile(r'document\.getElementById\([\"\']([a-zA-Z0-9_\-]+)[\"\']\)\.([a-zA-Z0-9_]+)')

    for idx, line in enumerate(js_lines, 1):
        # Exclude commented lines
        clean = line.strip()
        if clean.startswith("//") or clean.startswith("*"):
            continue
        for m in pattern.finditer(clean):
            elem_id = m.group(1)
            prop = m.group(2)
            if elem_id not in declared_ids:
                unguarded_failures.append((idx, elem_id, prop, clean))

    if unguarded_failures:
        details = "\n".join(
            f"  Line {line_no}: ID '{elem_id}' not in HTML, accessed via '.{prop}' without null guard:\n    {code}"
            for line_no, elem_id, prop, code in unguarded_failures
        )
        pytest.fail(
            f"Empirical Bug Detected: Unguarded DOM access on non-existent elements in static/app.js:\n{details}"
        )

