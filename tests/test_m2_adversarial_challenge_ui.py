"""
Automated Adversarial Empirical Challenge Suite for Milestone 2:
UI Robustness, Benchmark Card, and View Switching.

Verified by: teamwork_preview_challenger_m2_2

Challenges Covered:
1. DOM Property Safety Scan:
   Confirm that 100% of document.getElementById calls in openVertexInspector
   and runFrequencyOptimization are guarded against null reference exceptions,
   and execute headless DOM tests with null elements.
2. Duplicate Object Literal Keys Scan:
   Verify zero duplicate keys across static/app.js (e.g. aggregate_2m).
3. Benchmark Card Frequency Channel Reuse:
   Verify computeChannelReuse and renderReuseChips calculate correct distribution
   and reuse ratio for tied, asymmetric, single-color, and large-chromatic allocations.
4. View Switching State Preservation:
   Verify that switching between Map and Graph does not reset state.cells,
   state.coloring, or state.selectedTowerId.
5. Parameter Passing:
   Verify that runComparisonDirectly passes aggregate_2m in the POST /api/compare payload.
"""

import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "static" / "index.html"
STYLE_CSS = REPO_ROOT / "static" / "style.css"


def extract_function_body(content: str, func_sig: str) -> str:
    """Extracts function body bounded by curly braces."""
    idx = content.find(func_sig)
    assert idx != -1, f"Function signature '{func_sig}' not found"
    open_brace = content.find("{", idx)
    assert open_brace != -1, f"Opening brace not found for '{func_sig}'"
    count = 1
    i = open_brace + 1
    while i < len(content) and count > 0:
        if content[i] == "{":
            count += 1
        elif content[i] == "}":
            count -= 1
        i += 1
    return content[open_brace:i]


def test_challenge_dom_property_safety_scan():
    """Challenge 1: Confirm 100% of getElementById calls in openVertexInspector and runFrequencyOptimization are guarded."""
    content = APP_JS.read_text(encoding="utf-8")
    ovi_body = extract_function_body(content, "function openVertexInspector")
    rfo_body = extract_function_body(content, "async function runFrequencyOptimization")

    # Static assertion 1: Zero direct unguarded dot accesses on document.getElementById
    for name, body in [("openVertexInspector", ovi_body), ("runFrequencyOptimization", rfo_body)]:
        direct_dots = re.findall(r'document\.getElementById\([^)]+\)\.[a-zA-Z]', body)
        assert len(direct_dots) == 0, f"{name} contains unguarded direct DOM accesses: {direct_dots}"

    # Static assertion 2: Check all getElementById variable assignments are guarded before usage
    for name, body in [("openVertexInspector", ovi_body), ("runFrequencyOptimization", rfo_body)]:
        var_assigns = re.findall(r'(?:const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*document\.getElementById\(([^)]+)\)', body)
        assert len(var_assigns) > 0, f"{name} should have DOM element references"
        for var, elem_id in var_assigns:
            for match in re.finditer(r'\b' + var + r'\.([a-zA-Z0-9_]+)', body):
                pos = match.start()
                prefix = body[:pos]
                is_guarded = (
                    f"if ({var})" in prefix
                    or f"if (!{var}) return" in prefix
                    or f"if ({var} &&" in prefix
                    or f"[{var}" in prefix
                )
                assert is_guarded, f"Variable '{var}' ({elem_id}) in {name} accessed without null check!"

    # Empirical assertion 3: Execute headless Node.js null safety test runner
    res = subprocess.run(
        ["node", "tests/test_dom_null_safety.js"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"Headless DOM null safety test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ALL Headless DOM Null Safety Stress Tests PASSED successfully!" in res.stdout


def test_challenge_duplicate_object_literal_keys_scan():
    """Challenge 2: Verify zero duplicate keys across static/app.js (e.g. aggregate_2m)."""
    content = APP_JS.read_text(encoding="utf-8")

    # Check payload objects specifically for aggregate_2m
    for func_sig in [
        "async function runFrequencyOptimization",
        "function buildInterferenceGraphUI",
        "async function runComparisonDirectly",
    ]:
        body = extract_function_body(content, func_sig)
        payload_matches = re.findall(r"const payload = \{([\s\S]*?)\};", body)
        assert len(payload_matches) == 1, f"Expected 1 payload object in {func_sig}"
        payload_str = payload_matches[0]
        keys = [line.split(":")[0].strip() for line in payload_str.splitlines() if ":" in line]
        assert len(keys) == len(set(keys)), f"Duplicate keys in {func_sig}: {keys}"
        assert keys.count("aggregate_2m") == 1, f"aggregate_2m must appear exactly once in {func_sig}"

    # Empirical assertion: Execute full AST / tokenizer duplicate key scanner
    res = subprocess.run(
        ["node", "tests/scan_duplicate_keys.js"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"Duplicate keys scanner failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "SUCCESS: Zero duplicate keys detected across all object literals." in res.stdout


def test_challenge_benchmark_card_frequency_channel_reuse():
    """Challenge 3: Verify computeChannelReuse and renderReuseChips calculate correct distribution and reuse ratio."""
    # Execute dedicated Node.js test suite with tied, asymmetric, single-color, and large-chromatic cases
    res = subprocess.run(
        ["node", "tests/test_benchmark_card_reuse.js"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"Benchmark card reuse test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ALL Channel Reuse & Benchmark Card stress tests PASSED successfully!" in res.stdout


def test_challenge_view_switching_state_preservation():
    """Challenge 4: Verify switching between Map and Graph does not reset state.cells, state.coloring, or state.selectedTowerId."""
    # Execute dedicated Node.js view switching state preservation test
    res = subprocess.run(
        ["node", "tests/test_view_switching.js"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"View switching test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ALL View Switching state preservation tests PASSED successfully!" in res.stdout


def test_challenge_run_comparison_directly_parameter_passing():
    """Challenge 5: Verify that runComparisonDirectly passes aggregate_2m in POST /api/compare payload."""
    content = APP_JS.read_text(encoding="utf-8")
    body = extract_function_body(content, "async function runComparisonDirectly")
    assert "aggregate_2m: state.aggregate2m" in body

    # Empirical assertion: Execute network intercept test in Node
    res = subprocess.run(
        ["node", "tests/test_run_comparison_directly.js"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, f"runComparisonDirectly test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "runComparisonDirectly correctly passes aggregate_2m: true in payload." in res.stdout
    assert "runComparisonDirectly correctly passes aggregate_2m: false in payload." in res.stdout
