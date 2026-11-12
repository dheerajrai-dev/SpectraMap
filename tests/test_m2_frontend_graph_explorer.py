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
import pytest

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


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_force_simulation_physics_implementation():
    """Verify presence of Coulomb repulsion, Hooke springs, gravity, damping, and stability threshold."""
    content = APP_JS.read_text(encoding="utf-8")

    # 1. Coulomb repulsion
    assert "stepGraphSimulation" in content
    assert "kRep" in content or "k_rep" in content
    assert "epsilon" in content
    assert re.search(r"kRep\s*/\s*\(distSq\s*\+\s*epsilon\)", content) or re.search(r"/\s*\([^)]*distSq[^)]*\+[^)]*epsilon\)", content)

    # 2. Hooke's spring attraction along conflict edges
    assert "kSpring" in content or "k_spring" in content
    assert "restLength" in content or "l_0" in content
    assert "displacement" in content or re.search(r"dist\s*-\s*restLength", content)

    # 3. Center gravity attraction
    assert "kGrav" in content or "k_grav" in content
    assert "centerX - u.x" in content or "centerX - node.x" in content

    # 4. Velocity damping and max speed clamp
    assert "damping" in content
    assert re.search(r"damping\s*=\s*0\.\d+", content)
    assert "maxSpeed" in content

    # 5. Stability threshold and requestAnimationFrame
    assert "requestAnimationFrame" in content
    assert "startGraphSimulation" in content
    assert "stopGraphSimulation" in content
    assert re.search(r"maxV\s*<\s*0\.0\d+", content)


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_node_radius_mapped_to_degree():
    """Verify that node radius dynamically maps to vertex degree Delta(v) in range 7px to 18px."""
    content = APP_JS.read_text(encoding="utf-8")

    assert "initGraphPositionsIfNeeded" in content
    assert "degreeMap" in content
    assert "maxDeg" in content
    # Look for degree ratio calculation: 7 + (deg / maxDeg) * 11
    assert "7 + (deg / maxDeg) * 11" in content or re.search(r"7\s*\+\s*\(\s*deg\s*/\s*maxDeg\s*\)\s*\*\s*11", content)


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_node_color_and_adaptive_edge_opacity():
    """Verify node coloring by frequency channel and adaptive edge opacity."""
    content = APP_JS.read_text(encoding="utf-8")

    assert "getFrequencyColor" in content
    assert "getAdaptiveEdgeStyle" in content
    assert "drawGraphCanvas" in content
    assert "rgba(245, 158, 11" in content  # Amber incident glow


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_interactive_node_dragging():
    """Verify interactive mouse dragging and relaxation in initGraphCanvasInteractions."""
    content = APP_JS.read_text(encoding="utf-8")

    assert "initGraphCanvasInteractions" in content
    assert "mousedown" in content
    assert "mousemove" in content
    assert "mouseup" in content
    assert "isPinned" in content
    assert "draggedNodeId" in content
    assert "graph-canvas-dragging" in content


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_view_switching_state_preservation_and_sync():
    """Verify seamless view switching calls updateMapVisualStyles and map.invalidateSize."""
    content = APP_JS.read_text(encoding="utf-8")

    assert "switchVisualizationView" in content
    # Switching to map must stop simulation and call updateMapVisualStyles
    assert "stopGraphSimulation" in content
    assert "updateMapVisualStyles" in content
    assert "invalidateSize" in content


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


@pytest.mark.skip(reason="Excised separate Graph Topology visualization per Prompt 6")
def test_css_styles_for_dragging_and_reuse():
    """Verify style.css contains classes for grabbing cursor and solver reuse breakdown."""
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "#graph-canvas.graph-canvas-dragging" in css
    assert "cursor: grabbing" in css
    assert ".solver-reuse-breakdown" in css
    assert ".reuse-channel-chips" in css
    assert ".reuse-chip" in css
