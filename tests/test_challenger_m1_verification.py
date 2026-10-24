"""
Adversarial Verification Suite for Milestone 1:
Frontend Workspace Simplification & Visual Realization.

Empirically verifies:
1. Complete absence of excised canvas and simulation elements/functions.
2. Presence and integrity of 5-item dock.
3. Presence of #assignment-panel and #assignment-table with expected headers.
4. Absence of fake/decorative badges and presence of #status-badge.
5. Verification of node --check static/app.js.
6. Pipeline states and state invalidation triggers.
7. Adversarial tests detecting DOM ID mismatches and assignment panel defects.
"""

import os
import re
import subprocess
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML_PATH = os.path.join(ROOT_DIR, "static", "index.html")
APP_JS_PATH = os.path.join(ROOT_DIR, "static", "app.js")
STYLE_CSS_PATH = os.path.join(ROOT_DIR, "static", "style.css")


@pytest.fixture(scope="module")
def index_html():
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def app_js():
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def style_css():
    with open(STYLE_CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ==============================================================================
# 1. Verification of Excised Canvas & Force Simulation Artifacts
# ==============================================================================
def test_canvas_and_view_switcher_excised_from_html(index_html):
    """Ensure excised canvas elements and view switcher do not exist in HTML."""
    forbidden_ids = [
        "graph-canvas-container",
        "graph-canvas",
        "graph-tooltip",
        "tab-map-view",
        "tab-graph-view",
        "toggle-edges",
    ]
    for fid in forbidden_ids:
        assert f'id="{fid}"' not in index_html, f"Found forbidden id='{fid}' in index.html"

    forbidden_classes = [
        "view-switcher",
        "graph-watermark",
    ]
    for fcls in forbidden_classes:
        assert fcls not in index_html, f"Found forbidden class '{fcls}' in index.html"


def test_simulation_functions_and_canvas_state_excised_from_app_js(app_js):
    """Ensure simulation functions and canvas state loops do not exist in app.js."""
    forbidden_terms = [
        "updateForceSimulation",
        "stepGraphSimulation",
        "drawGraphCanvas",
        "startGraphSimulation",
        "stopGraphSimulation",
        "initGraphCanvasInteractions",
        "initGraphPositionsIfNeeded",
        "isDraggingGraphNode",
        "graphSimulation",
        "graphNodePositions",
    ]
    for term in forbidden_terms:
        assert term not in app_js, f"Found forbidden simulation term '{term}' in static/app.js"


def test_canvas_and_view_switcher_excised_from_css(style_css):
    """Ensure CSS has no canvas or view-switcher styling remnants."""
    forbidden_selectors = [
        "#graph-canvas-container",
        "#graph-canvas",
        "#graph-tooltip",
        ".view-switcher",
        ".view-tab",
        ".graph-watermark",
    ]
    for sel in forbidden_selectors:
        assert sel not in style_css, f"Found forbidden selector '{sel}' in static/style.css"


# ==============================================================================
# 2. Presence & Integrity of 5-Item Control Dock
# ==============================================================================
def test_five_item_dock_presence(index_html):
    """Ensure dock contains exactly 5 numbered main sections with required IDs."""
    dock_ids = [
        "dock-sec-location",
        "dock-sec-radius",
        "dock-sec-radio",
        "dock-sec-limit",
        "dock-sec-actions",
    ]
    for sec_id in dock_ids:
        assert f'id="{sec_id}"' in index_html, f"Missing dock section '{sec_id}' in index.html"

    # Verify section numbers 1 through 5
    for num in range(1, 6):
        assert f'<span class="section-num">{num}</span>' in index_html, f"Missing section-num '{num}' in index.html"


def test_dock_section_elements(index_html):
    """Verify essential controls exist inside the 5 dock sections."""
    # Item 1: Location
    assert 'id="preset-select"' in index_html
    assert 'id="input-lat"' in index_html
    assert 'id="input-lon"' in index_html

    # Item 2: Search Radius
    assert 'id="radius-slider"' in index_html
    assert 'id="radius-label"' in index_html

    # Item 3: Radio Tech
    assert 'id="check-tech-4g"' in index_html
    assert 'id="check-tech-5g"' in index_html
    assert 'id="check-aggregate-2m"' in index_html

    # Item 4: Record Limit & Accounting
    assert 'id="limit-slider"' in index_html
    assert 'id="limit-label"' in index_html
    assert 'id="acc-avail"' in index_html
    assert 'id="acc-elig"' in index_html
    assert 'id="acc-sel"' in index_html
    assert 'id="acc-excl"' in index_html

    # Item 5: Action Controls
    assert 'id="btn-fetch"' in index_html
    assert 'id="btn-optimize"' in index_html
    assert 'id="algo-select"' in index_html
    assert 'id="cells-status"' in index_html
    assert 'id="btn-build-graph"' in index_html
    assert 'id="btn-compare-action"' in index_html


# ==============================================================================
# 3. Cell Assignment Table & Headers
# ==============================================================================
def test_assignment_table_structure(index_html):
    """Verify presence of #assignment-panel and #assignment-table with headers."""
    assert 'id="assignment-panel"' in index_html
    assert 'id="assignment-table"' in index_html
    assert 'id="assignment-count-badge"' in index_html
    assert 'id="assignment-table-body"' in index_html

    # Expected column header classes
    header_classes = [
        "th-cell",
        "th-id",
        "th-tech",
        "th-channel",
        "th-radius",
        "th-conflicts",
    ]
    for hcls in header_classes:
        assert hcls in index_html, f"Missing table header class '{hcls}' in index.html"


# ==============================================================================
# 4. Status Badge and Fake Badge Absence
# ==============================================================================
def test_status_badge_and_fake_badges(index_html):
    """Ensure #status-badge is present and fake badges like #location-badge are absent."""
    assert 'id="status-badge"' in index_html
    assert 'id="location-badge"' not in index_html
    assert "Live Telemetry" not in index_html


# ==============================================================================
# 5. JS Syntax Verification
# ==============================================================================
def test_node_check_app_js():
    """Verify node --check static/app.js passes with code 0."""
    res = subprocess.run(
        ["node", "--check", "static/app.js"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed: {res.stderr}"


# ==============================================================================
# 6. Pipeline States and State Invalidation
# ==============================================================================
def test_seven_pipeline_states_in_app_js(app_js):
    """Verify the 7 discrete states are present in setPipelineState."""
    expected_states = [
        "Connecting",
        "Fetching",
        "Building Graph",
        "Optimizing",
        "Validating",
        "Completed",
        "Failed",
    ]
    for state in expected_states:
        pattern = rf'case\s+["\']{re.escape(state)}["\']:'
        assert re.search(pattern, app_js), f"Missing pipeline state '{state}' in static/app.js"


def test_state_invalidation_function(app_js):
    """Verify invalidateOptimizationState is defined and handles key state resets."""
    assert "function invalidateOptimizationState" in app_js
    assert "state.optimizationResults = null;" in app_js
    assert "state.currentAssignments = null;" in app_js


# ==============================================================================
# 7. Adversarial Challenge Tests: Assignment Table Defect Identification
# ==============================================================================
def test_adversarial_challenge_assignment_search_input_id_mismatch(index_html, app_js):
    """
    Empirical Challenge 1:
    Verify that the search input ID queried by initAssignmentTableEvents in app.js
    matches the ID in index.html.
    """
    html_has_search_input = 'id="assignment-search-input"' in index_html
    js_queries_search_id = 'document.getElementById("assignment-search")' in app_js
    js_queries_input_id = 'document.getElementById("assignment-search-input")' in app_js

    # If HTML has "assignment-search-input" but JS queries "assignment-search",
    # the search event listener is completely disconnected.
    if html_has_search_input and js_queries_search_id and not js_queries_input_id:
        pytest.fail(
            "CRITICAL BUG: Assignment search input is disconnected! "
            "index.html defines id='assignment-search-input' but app.js queries document.getElementById('assignment-search'). "
            "Event listener is never bound and real-time filtering is broken."
        )


def test_adversarial_challenge_assignment_clear_button_id_mismatch(index_html, app_js):
    """
    Empirical Challenge 2:
    Verify that the search clear button ID in index.html matches app.js.
    """
    html_has_clear_btn = 'id="btn-clear-assignment-search"' in index_html
    js_queries_clear_btn = 'document.getElementById("btn-assignment-search-clear")' in app_js
    js_queries_html_btn = 'document.getElementById("btn-clear-assignment-search")' in app_js

    if html_has_clear_btn and js_queries_clear_btn and not js_queries_html_btn:
        pytest.fail(
            "CRITICAL BUG: Assignment clear button is disconnected! "
            "index.html defines id='btn-clear-assignment-search' but app.js queries document.getElementById('btn-assignment-search-clear'). "
            "Clear click listener is never bound and toggle display is broken."
        )


def test_adversarial_challenge_assignment_panel_visibility(index_html, app_js):
    """
    Empirical Challenge 3:
    Verify that #assignment-panel is not permanently hidden with display: none.
    """
    panel_initially_hidden = 'id="assignment-panel" class="assignment-panel" style="display: none;"' in index_html
    panel_unhidden_in_js = re.search(r'assignment-panel.*style\.display\s*=', app_js) is not None or \
                           'getElementById("assignment-panel")' in app_js

    if panel_initially_hidden and not panel_unhidden_in_js:
        pytest.fail(
            "CRITICAL BUG: Assignment panel is permanently hidden! "
            "index.html has style='display: none;' on #assignment-panel, but app.js never references #assignment-panel "
            "to unhide it (e.g. style.display = 'block' or ''). The user will never see the table."
        )


def test_adversarial_challenge_column_header_data_mismatch(index_html, app_js):
    """
    Empirical Challenge 4:
    Verify semantic agreement between column 5 header and generated cell data.
    """
    header_is_radius = '<th scope="col" class="th-radius">Radius</th>' in index_html
    # In app.js renderAssignmentTable:
    # <td>${degree}</td>
    body_renders_degree = '<td class="font-mono text-xs">${degree}</td>' in app_js

    if header_is_radius and body_renders_degree:
        pytest.fail(
            "SEMANTIC MISMATCH: Table column 5 header is labeled 'Radius' (<th scope='col' class='th-radius'>Radius</th>), "
            "but renderAssignmentTable renders vertex conflict degree (<td class='font-mono text-xs'>${degree}</td>). "
            "Worker documented column as 'Degree'."
        )
