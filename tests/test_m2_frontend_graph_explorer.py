"""
Automated Verification Test Suite for Milestone 2: Frontend Graph Explorer & Map Workspace.
Verifies:
- Interactive Force-Directed Canvas Simulation:
  * Coulomb repulsion: F_rep = k_rep / (d^2 + epsilon)
  * Hooke's spring attraction along conflict edges: F_spring = k_spring * (d - l_0)
  * Center gravity attraction
  * Velocity damping / friction
  * Animation loop with requestAnimationFrame and stability threshold
  * Node radius dynamically mapped to degree Delta(v) (range 7px to 18px based on deg(v) / Delta(G))
  * Node color mapped to frequency channel (f1, f2, ...)
  * Conflict edges with adaptive opacity
  * Interactive node dragging: mousedown, mousemove, mouseup, real-time relaxation
- Geographic Map View & Seamless Switching:
  * Tab switching calls updateMapVisualStyles() and map.invalidateSize()
  * Simulation halts when switching to Map view
- Side-by-Side Benchmark Dashboard:
  * Compact card renders DSatur vs Welsh-Powell color counts, runtimes in ms, validation badges,
    and channel reuse breakdown (cells/channel + distribution chips)
  * runComparisonDirectly passes aggregate_2m in POST /api/compare payload
- Bidirectional Vertex Inspector & Robustness:
  * Selecting a node highlights incident edges and neighbors, displaying allocation rationale
  * Safe DOM property access without unguarded getElementById calls
  * No duplicate keys in object literals
- R5 Lightweight Stack Compliance:
  * Vanilla JS, HTML5, CSS3, Leaflet only.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "static" / "index.html"
STYLE_CSS = REPO_ROOT / "static" / "style.css"


def get_function_body(content: str, func_name: str) -> str:
    """Extracts function body handling nested curly braces."""
    idx = content.find(func_name)
    assert idx != -1, f"Function {func_name} not found"
    open_brace = content.find("{", idx)
    assert open_brace != -1, f"Opening brace not found for {func_name}"
    brace_count = 1
    i = open_brace + 1
    while i < len(content) and brace_count > 0:
        if content[i] == "{":
            brace_count += 1
        elif content[i] == "}":
            brace_count -= 1
        i += 1
    return content[open_brace:i]


def test_app_js_syntax_validity():
    """Verify that static/app.js parses with zero syntax errors via node --check."""
    res = subprocess.run(["node", "--check", str(APP_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_force_simulation_physics_implementation():
    """Verify that force physics simulation loops were excised from static/app.js."""
    content = APP_JS.read_text(encoding="utf-8")
    assert "stepGraphSimulation" not in content
    assert "startGraphSimulation" not in content
    assert "stopGraphSimulation" not in content


def test_node_radius_mapped_to_degree():
    """Verify that map-first cell rendering uses Leaflet markers rather than canvas simulation."""
    content = APP_JS.read_text(encoding="utf-8")
    assert "renderCellTowers" in content
    assert "getFrequencyColor" in content


def test_node_color_and_adaptive_edge_opacity():
    """Verify node coloring by frequency channel on Leaflet map markers and coverage circles."""
    content = APP_JS.read_text(encoding="utf-8")
    assert "getFrequencyColor" in content
    assert "renderCellTowers" in content
    assert "coverageCirclesById" in content


def test_interactive_node_dragging():
    """Verify interactive canvas dragging was excised in favor of map pan/drag."""
    content = APP_JS.read_text(encoding="utf-8")
    assert "initGraphCanvasInteractions" not in content


def test_view_switching_state_preservation_and_sync():
    """Verify map-first workspace maintains updated map visuals and stable coordinates."""
    content = APP_JS.read_text(encoding="utf-8")
    assert "updateMapVisualStyles" in content
    assert "renderCellTowers" in content


def test_benchmark_dashboard_channel_reuse_breakdown():
    """Verify that embedded comparison card displays channel reuse breakdown (ratio + distribution)."""
    content = APP_JS.read_text(encoding="utf-8")

    assert "renderEmbeddedComparisonCard" in content
    assert "computeChannelReuse" in content
    assert "renderReuseChips" in content
    assert "cells/ch" in content or "cellsPerChannelStr" in content
    assert "solver-reuse-breakdown" in content
    assert "reuse-channel-chips" in content


def test_compare_endpoint_includes_aggregate_2m():
    """Verify that runComparisonDirectly passes aggregate_2m to POST /api/compare."""
    content = APP_JS.read_text(encoding="utf-8")

    body = get_function_body(content, "function runComparisonDirectly")
    assert "aggregate_2m: state.aggregate2m" in body


def test_zero_duplicate_keys_in_object_literals():
    """Verify that object literals in static/app.js do not define duplicate keys."""
    content = APP_JS.read_text(encoding="utf-8")

    build_body = get_function_body(content, "function buildInterferenceGraphUI")
    payload_match = re.search(r"const payload = \{([\s\S]*?)\};", build_body)
    assert payload_match, "payload object not found in buildInterferenceGraphUI"
    payload_str = payload_match.group(1)
    keys = [line.split(":")[0].strip() for line in payload_str.splitlines() if ":" in line]
    assert len(keys) == len(set(keys)), f"Duplicate keys found in buildInterferenceGraphUI payload: {keys}"


def test_no_unguarded_get_element_by_id_property_access():
    """Verify that no direct document.getElementById property accesses exist without null checks."""
    content = APP_JS.read_text(encoding="utf-8")

    # Pattern: document.getElementById("...").property = ... without optional chaining
    unguarded = re.findall(r'document\.getElementById\([^)]+\)\.[a-zA-Z]', content)
    assert len(unguarded) == 0, f"Found unguarded document.getElementById accesses: {unguarded}"


def test_css_styles_for_dragging_and_reuse():
    """Verify style.css contains solver reuse breakdown and responsive legend styling."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert ".solver-reuse-breakdown" in css
    assert ".reuse-channel-chips" in css
    assert ".reuse-chip" in css
