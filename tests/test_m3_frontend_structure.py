"""
Automated Empirical Verification Test Suite for Milestone M3 Frontend Structure.
Tests DOM completeness across all 5 sections, visualization switcher,
8 dashboard KPIs, embedded comparison card, frequency legend, JS syntax,
JS-to-DOM element binding integrity, and responsive CSS rules.
"""

import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "static" / "index.html"
APP_JS = REPO_ROOT / "static" / "app.js"
STYLE_CSS = REPO_ROOT / "static" / "style.css"


class DOMParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements_by_id = {}
        self.tags = []
        self.all_classes = set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        self.tags.append((tag, attr_dict))
        if "id" in attr_dict:
            self.elements_by_id[attr_dict["id"]] = {
                "tag": tag,
                "attrs": attr_dict,
            }
        if "class" in attr_dict:
            for cls in attr_dict["class"].split():
                self.all_classes.add(cls)


def parse_index_html():
    assert INDEX_HTML.exists(), f"Missing {INDEX_HTML}"
    content = INDEX_HTML.read_text(encoding="utf-8")
    parser = DOMParser()
    parser.feed(content)
    return parser, content


def test_html_file_exists_and_loads():
    """Verify that static/index.html exists and is populated."""
    assert INDEX_HTML.exists()
    assert INDEX_HTML.stat().st_size > 1000


def test_section_1_location_controls():
    """
    Section 1: Location & Search Center
    Must include preset location selector, lat/lon inputs, and search radius slider.
    """
    dom, _ = parse_index_html()

    # Section wrapper
    assert "dock-sec-location" in dom.elements_by_id

    # Preset selector
    assert "preset-select" in dom.elements_by_id
    preset = dom.elements_by_id["preset-select"]
    assert preset["tag"] == "select"

    # Coordinates
    assert "input-lat" in dom.elements_by_id
    assert dom.elements_by_id["input-lat"]["attrs"].get("type") == "number"

    assert "input-lon" in dom.elements_by_id
    assert dom.elements_by_id["input-lon"]["attrs"].get("type") == "number"

    # Radius slider & label
    assert "radius-slider" in dom.elements_by_id
    slider = dom.elements_by_id["radius-slider"]
    assert slider["attrs"].get("type") == "range"
    assert int(slider["attrs"].get("min", 0)) == 500
    assert int(slider["attrs"].get("max", 0)) == 3000
    assert "radius-label" in dom.elements_by_id


def test_section_2_radio_technologies_filter():
    """
    Section 2: Radio Technologies (4G LTE & 5G NR Only)
    Must include 4G and 5G checkbox filters and technology warning banner.
    """
    dom, _ = parse_index_html()

    # Section wrapper
    assert "dock-sec-radio" in dom.elements_by_id

    # 4G Checkbox
    assert "check-tech-4g" in dom.elements_by_id
    chk_4g = dom.elements_by_id["check-tech-4g"]
    assert chk_4g["attrs"].get("type") == "checkbox"
    assert "checked" in chk_4g["attrs"]

    # 5G Checkbox
    assert "check-tech-5g" in dom.elements_by_id
    chk_5g = dom.elements_by_id["check-tech-5g"]
    assert chk_5g["attrs"].get("type") == "checkbox"
    assert "checked" in chk_5g["attrs"]

    # Technology Warning alert
    assert "tech-warning" in dom.elements_by_id
    warning = dom.elements_by_id["tech-warning"]
    assert warning["attrs"].get("role") == "alert"


def test_section_3_dataset_size_and_accounting():
    """
    Section 3: Dataset Size & Record Limit
    Must include record limit slider (10-200, step 5, default 50) and 4 live accounting pills.
    """
    dom, _ = parse_index_html()

    # Section wrapper
    assert "dock-sec-limit" in dom.elements_by_id

    # Record limit slider & label
    assert "limit-slider" in dom.elements_by_id
    slider = dom.elements_by_id["limit-slider"]
    assert slider["attrs"].get("type") == "range"
    assert int(slider["attrs"].get("min", 0)) == 10
    assert int(slider["attrs"].get("max", 0)) == 200
    assert int(slider["attrs"].get("step", 0)) == 5
    assert int(slider["attrs"].get("value", 0)) == 50
    assert "limit-label" in dom.elements_by_id

    # 4 Live Accounting Pills
    assert "acc-avail" in dom.elements_by_id
    assert "acc-elig" in dom.elements_by_id
    assert "acc-sel" in dom.elements_by_id
    assert "acc-excl" in dom.elements_by_id


def test_section_4_coverage_model():
    """
    Section 4: Coverage Model & Sensitivity Override
    Must include observed range summary statistics and uniform radius override slider.
    """
    dom, _ = parse_index_html()

    # Section wrapper
    assert "dock-sec-coverage" in dom.elements_by_id

    # Observed range summary cards
    assert "range-summary" in dom.elements_by_id
    assert "range-min" in dom.elements_by_id
    assert "range-med" in dom.elements_by_id
    assert "range-max" in dom.elements_by_id

    # Uniform radius override slider & label
    assert "override-slider" in dom.elements_by_id
    slider = dom.elements_by_id["override-slider"]
    assert slider["attrs"].get("type") == "range"
    assert int(slider["attrs"].get("min", -1)) == 0
    assert int(slider["attrs"].get("max", 0)) == 2000
    assert int(slider["attrs"].get("step", 0)) == 50
    assert "override-label" in dom.elements_by_id


def test_section_5_pipeline_actions():
    """
    Section 5: Consolidated Pipeline Actions
    Must include 4 pipeline buttons (fetch, build, optimize, compare) and status callout.
    """
    dom, _ = parse_index_html()

    # Section wrapper
    assert "dock-sec-actions" in dom.elements_by_id

    # Pipeline action buttons
    assert "btn-fetch" in dom.elements_by_id
    assert dom.elements_by_id["btn-fetch"]["tag"] == "button"

    assert "btn-build-graph" in dom.elements_by_id
    assert dom.elements_by_id["btn-build-graph"]["tag"] == "button"
    assert "disabled" in dom.elements_by_id["btn-build-graph"]["attrs"]

    assert "btn-optimize" in dom.elements_by_id
    assert dom.elements_by_id["btn-optimize"]["tag"] == "button"
    assert "disabled" in dom.elements_by_id["btn-optimize"]["attrs"]

    assert "btn-compare-action" in dom.elements_by_id
    assert dom.elements_by_id["btn-compare-action"]["tag"] == "button"
    assert "disabled" in dom.elements_by_id["btn-compare-action"]["attrs"]

    # Algorithm selector
    assert "algo-select" in dom.elements_by_id

    # Live status callout banner
    assert "cells-status" in dom.elements_by_id
    assert dom.elements_by_id["cells-status"]["attrs"].get("aria-live") == "polite"


def test_visualization_switcher_and_containers():
    """
    Main Visualizer Workspace
    Map is the single primary visualizer; graph canvas and tabs are excised.
    """
    dom, _ = parse_index_html()

    assert "map" in dom.elements_by_id
    assert "tab-map-view" not in dom.elements_by_id
    assert "tab-graph-view" not in dom.elements_by_id
    assert "graph-canvas" not in dom.elements_by_id
    assert "graph-canvas-container" not in dom.elements_by_id

def test_analytics_dashboard_8_kpis_and_comparison():
    """
    Results Analytics Dashboard
    Must include 8 core KPIs (9 elements with 4G/5G ratio), embedded comparison card,
    and accessible frequency legend toolbar.
    """
    dom, _ = parse_index_html()

    # 8 KPI Metrics:
    # 1. Towers |V|
    assert "metric-towers" in dom.elements_by_id
    # 2. Conflicts |E|
    assert "metric-edges" in dom.elements_by_id
    # 3. Max Degree Δ
    assert "metric-degree" in dom.elements_by_id
    # 4. Density ρ
    assert "metric-density" in dom.elements_by_id
    # 5. 4G/5G Ratio Breakdown
    assert "badge-ratio-4g" in dom.elements_by_id
    assert "badge-ratio-5g" in dom.elements_by_id
    # 6. Colors Used k
    assert "metric-colors" in dom.elements_by_id
    # 7. Solver Runtime ms
    assert "metric-runtime" in dom.elements_by_id
    # 8. Independent Validation Badge
    assert "metric-validation-badge" in dom.elements_by_id

    # Embedded side-by-side comparison card
    assert "dashboard-compare-card" in dom.elements_by_id

    # Frequency Legend Toolbar
    assert "legend-container" in dom.elements_by_id
    assert dom.elements_by_id["legend-container"]["attrs"].get("role") == "toolbar"
    assert "legend-items" in dom.elements_by_id
    assert "btn-clear-isolate" in dom.elements_by_id


def test_vertex_inspector_context_dock():
    """
    Vertex Inspector Dock
    Must provide cell specifications, neighborhood, and frequency explainability.
    """
    dom, _ = parse_index_html()

    assert "vertex-inspector" in dom.elements_by_id
    assert "inspector-cell-id" in dom.elements_by_id
    assert "inspector-radio" in dom.elements_by_id
    assert "insp-coords" in dom.elements_by_id
    assert "insp-range" in dom.elements_by_id
    assert "insp-degree" in dom.elements_by_id
    assert "insp-neighbor-list" in dom.elements_by_id
    assert "insp-blocked-channels" in dom.elements_by_id
    assert "insp-rationale-text" in dom.elements_by_id
    assert "btn-close-inspector" in dom.elements_by_id


def test_js_syntax_validation():
    """Verify JavaScript syntax validity using node --check."""
    res = subprocess.run(
        ["node", "--check", str(APP_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"JS syntax check failed:\n{res.stderr}"


def test_css_responsive_media_queries():
    """
    Verify responsive CSS layout rules across all 4 specified tiers:
    1. Desktop Wide (> 1024px)
    2. Tablet Landscape (901px - 1024px)
    3. Tablet Portrait (641px - 900px)
    4. Mobile (<= 640px)
    """
    assert STYLE_CSS.exists()
    css_content = STYLE_CSS.read_text(encoding="utf-8")

    assert "@media (min-width: 1025px)" in css_content, "Missing desktop wide media query (> 1024px)"
    assert "@media (max-width: 1024px) and (min-width: 901px)" in css_content, "Missing tablet landscape media query (901-1024px)"
    assert "@media (max-width: 900px)" in css_content, "Missing tablet portrait media query (<= 900px)"
    assert "@media (max-width: 640px)" in css_content, "Missing mobile media query (<= 640px)"


def test_css_marker_and_comparison_classes():
    """Verify that required synchronized visual style classes exist in static/style.css."""
    css_content = STYLE_CSS.read_text(encoding="utf-8")

    # Synchronized marker styles
    assert ".selected-marker" in css_content
    assert ".neighbor-marker" in css_content
    assert ".dimmed-marker" in css_content

    # Comparison card styles
    assert ".dashboard-compare-card" in css_content
    assert ".compare-card-container" in css_content
    assert ".compare-solver-box" in css_content
    assert ".winner-box" in css_content


def test_dispatch_contract_id_mapping():
    """
    Verifies that all concepts referenced in the dispatch prompt have exact,
    operational DOM element equivalents in static/index.html.
    Documents the mapping between Worker M3's handoff names and the actual IDs.
    """
    dom, _ = parse_index_html()

    id_mapping = {
        # Concept: (Claimed in Worker M3 Handoff, Implemented in index.html)
        "Radius Slider": ("slider-radius", "radius-slider"),
        "4G Radio Toggle": ("chk-4g", "check-tech-4g"),
        "5G Radio Toggle": ("chk-5g", "check-tech-5g"),
        "Record Limit Slider": ("slider-record-limit", "limit-slider"),
        "Coverage Override Slider": ("slider-coverage-override", "override-slider"),
        "Range Median Statistic": ("stat-range-mean", "range-med"),
        "Section 1 Container": ("section-location", "dock-sec-location"),
        "Section 2 Container": ("section-radios", "dock-sec-radio"),
        "Section 3 Container": ("section-dataset-limit", "dock-sec-limit"),
        "Section 4 Container": ("section-coverage-model", "dock-sec-coverage"),
        "Section 5 Container": ("section-pipeline-actions", "dock-sec-actions"),
    }

    for concept, (claimed_id, implemented_id) in id_mapping.items():
        assert implemented_id in dom.elements_by_id, (
            f"Concept '{concept}' implemented ID '{implemented_id}' is missing from static/index.html"
        )


def test_no_unguarded_null_dom_access_in_app_js():
    """
    CRITICAL EMPIRICAL CHALLENGE:
    Static analysis check verifying that static/app.js does NOT attempt direct,
    unguarded property access (e.g. document.getElementById('...').textContent = ...)
    on elements that do not exist in static/index.html.
    
    Accessing properties on null throws an uncaught TypeError in JavaScript,
    halting execution of the function and breaking critical pipelines (such as
    frequency optimization rendering).
    """
    dom, _ = parse_index_html()
    js_content = APP_JS.read_text(encoding="utf-8")

    # Match direct unguarded calls: document.getElementById("xyz").prop = ...
    # where .prop is textContent, innerHTML, value, etc. (without optional chaining ?.)
    unguarded_pattern = re.compile(
        r'document\.getElementById\(["\']([a-zA-Z0-9_\-]+)["\']\)\.(textContent|innerHTML|value|style|classList)'
    )

    crashes = []
    for match in unguarded_pattern.finditer(js_content):
        target_id = match.group(1)
        prop = match.group(2)
        if target_id not in dom.elements_by_id:
            line_no = js_content[: match.start()].count("\n") + 1
            crashes.append({
                "line": line_no,
                "id": target_id,
                "prop": prop,
                "snippet": match.group(0),
            })

    assert not crashes, (
        f"Found {len(crashes)} unguarded DOM property access(es) on missing elements in static/app.js!\n"
        f"These throw TypeError: Cannot set properties of null at runtime:\n"
        + "\n".join(f"  Line {c['line']}: {c['snippet']} (id '{c['id']}' not in index.html)" for c in crashes)
    )
