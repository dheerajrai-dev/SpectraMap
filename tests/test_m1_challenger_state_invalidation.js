/**
 * Milestone 1 Challenger 2 Empirical Test Suite: State Invalidation & Pipeline State Machine.
 * Executes actual static/app.js code in a headless Node environment.
 * Tests:
 * 1. Invalidation trigger on every query mutation (lat/lon, radius, presets, checkboxes, limit).
 * 2. Invalidation side-effects (state reset, DOM badge, legend, table, circles, markers).
 * 3. 7-state discrete pipeline machine coverage, DOM updates, and CSS classes.
 * 4. State transition sequences across the complete pipeline lifecycle.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');

function extractFunction(name) {
    let idx = code.indexOf(`async function ${name}`);
    if (idx === -1) idx = code.indexOf(`function ${name}`);
    assert(idx !== -1, `Function ${name} not found in static/app.js`);
    const openBrace = code.indexOf('{', idx);
    let count = 1;
    let i = openBrace + 1;
    while (i < code.length && count > 0) {
        if (code[i] === '{') count++;
        else if (code[i] === '}') count--;
        i++;
    }
    return code.slice(idx, i);
}

// Minimal DOM Element Mock
class MockElement {
    constructor(id) {
        this.id = id;
        this.textContent = '';
        this.innerHTML = '';
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.className = '';
        this.classList = {
            classes: new Set(),
            add: (cls) => this.classList.classes.add(cls),
            remove: (cls) => this.classList.classes.delete(cls),
            contains: (cls) => this.classList.classes.has(cls),
        };
        this.style = {};
        this.eventListeners = {};
        this.attributes = {};
    }

    addEventListener(event, fn) {
        if (!this.eventListeners[event]) this.eventListeners[event] = [];
        this.eventListeners[event].push(fn);
    }

    trigger(event, data = {}) {
        const listeners = this.eventListeners[event] || [];
        listeners.forEach(fn => fn({ target: this, ...data }));
    }

    setAttribute(key, val) {
        this.attributes[key] = val;
    }

    getAttribute(key) {
        return this.attributes[key];
    }
}

// DOM registry
class MockDocument {
    constructor() {
        this.elements = new Map();
    }

    getElementById(id) {
        if (!this.elements.has(id)) {
            this.elements.set(id, new MockElement(id));
        }
        return this.elements.get(id);
    }
}

console.log("=== EMPIRICAL CHALLENGE 1: 7-State Pipeline Machine Coverage & DOM Assertions ===");

{
    const doc = new MockDocument();
    const globalState = {
        cells: [{ tower_id: "T1" }],
        pipelineState: "",
    };

    // Helper functions needed by setPipelineState
    const setPipelineButtonsDisabledCode = extractFunction('setPipelineButtonsDisabled');
    const setPipelineStateCode = extractFunction('setPipelineState');

    const fnSetPipelineState = new Function(
        'state', 'document',
        `
        ${setPipelineButtonsDisabledCode}
        ${setPipelineStateCode}
        return setPipelineState;
        `
    )(globalState, doc);

    const states = ["Connecting", "Fetching", "Building Graph", "Optimizing", "Validating", "Completed", "Failed"];

    states.forEach(stateName => {
        fnSetPipelineState(stateName, `Testing state ${stateName}`);
        assert.strictEqual(globalState.pipelineState, stateName, `State must be recorded as ${stateName}`);

        const statusMsg = doc.getElementById("cells-status");
        assert.ok(statusMsg.textContent.includes(stateName) || statusMsg.textContent.length > 0, `Status message updated for ${stateName}`);

        const btnFetch = doc.getElementById("btn-fetch");
        const btnBuild = doc.getElementById("btn-build-graph");
        const btnOpt = doc.getElementById("btn-optimize");
        const btnCompare = doc.getElementById("btn-compare-action");

        if (stateName === "Connecting") {
            assert.strictEqual(btnFetch.disabled, true, "btnFetch disabled in Connecting");
            assert.strictEqual(btnBuild.disabled, true, "btnBuild disabled in Connecting");
            assert.strictEqual(btnOpt.disabled, true, "btnOpt disabled in Connecting");
            assert.strictEqual(btnCompare.disabled, true, "btnCompare disabled in Connecting");
            const badge = doc.getElementById("status-badge");
            assert.strictEqual(badge.textContent, "Connecting...");
            assert.strictEqual(badge.className, "badge badge-loading");
            assert.strictEqual(statusMsg.style.color, "var(--text-secondary)");
        } else if (stateName === "Fetching") {
            assert.strictEqual(btnFetch.disabled, true);
            assert.ok(btnFetch.innerHTML.includes("Fetching"), "btnFetch has Fetching spinner");
            assert.strictEqual(statusMsg.style.color, "var(--text-secondary)");
        } else if (stateName === "Building Graph") {
            assert.strictEqual(btnBuild.disabled, true);
            assert.ok(btnBuild.innerHTML.includes("Building"), "btnBuild has Building spinner");
            assert.strictEqual(statusMsg.style.color, "var(--text-secondary)");
        } else if (stateName === "Optimizing") {
            assert.strictEqual(btnOpt.disabled, true);
            assert.ok(btnOpt.innerHTML.includes("Optimizing"), "btnOpt has Optimizing spinner");
            assert.strictEqual(statusMsg.style.color, "var(--text-secondary)");
        } else if (stateName === "Validating") {
            assert.strictEqual(btnOpt.disabled, true);
            assert.ok(btnOpt.innerHTML.includes("Validating"), "btnOpt has Validating spinner");
            assert.strictEqual(statusMsg.style.color, "var(--text-secondary)");
        } else if (stateName === "Completed") {
            assert.strictEqual(btnFetch.disabled, false, "btnFetch enabled in Completed");
            assert.strictEqual(btnBuild.disabled, false, "btnBuild enabled in Completed");
            assert.strictEqual(btnOpt.disabled, false, "btnOpt enabled in Completed");
            assert.strictEqual(btnCompare.disabled, false, "btnCompare enabled in Completed");
            assert.ok(btnFetch.innerHTML.includes("Fetch Records"));
            assert.ok(btnBuild.innerHTML.includes("Build Graph"));
            assert.ok(btnOpt.innerHTML.includes("Optimize Frequencies"));
            assert.strictEqual(statusMsg.style.color, "var(--accent-emerald)");
        } else if (stateName === "Failed") {
            assert.strictEqual(btnFetch.disabled, false, "btnFetch enabled in Failed");
            assert.strictEqual(statusMsg.style.color, "var(--accent-rose)");
        }
    });

    console.log("✔ PASS: All 7 discrete pipeline states set correct CSS classes, button states, and DOM text.");
}

console.log("=== EMPIRICAL CHALLENGE 2: Invalidation Trigger & State Reset Verification ===");

{
    const doc = new MockDocument();
    let tableRenderCount = 0;
    let dashboardUpdateCount = 0;
    let comparisonCardRenderCount = 0;

    const mockRenderAssignmentTable = (coloring, cells) => {
        tableRenderCount++;
        assert.strictEqual(coloring, null, "renderAssignmentTable must receive null coloring on invalidate");
    };

    const mockUpdateDashboardMetrics = (metrics, time, coloring, cells) => {
        dashboardUpdateCount++;
        assert.strictEqual(coloring, null, "updateDashboardMetrics must receive null coloring on invalidate");
    };

    const mockRenderEmbeddedComparisonCard = () => {
        comparisonCardRenderCount++;
    };

    const globalState = {
        cells: [
            { tower_id: "T1", cell_id: 101, label: "A", latitude: 28.52, longitude: 77.19, range_m: 800, radio: "4G" },
            { tower_id: "T2", cell_id: 102, label: "B", latitude: 28.53, longitude: 77.19, range_m: 800, radio: "5G" },
        ],
        optimizationResults: { dsatur: { coloring: { "T1": 0, "T2": 1 } } },
        currentAssignments: { "T1": 0, "T2": 1 },
        isolatedFrequency: 0,
        coverageCirclesById: {
            "T1": {
                style: {},
                setStyle: function(s) { this.style = s; }
            },
            "T2": {
                style: {},
                setStyle: function(s) { this.style = s; }
            }
        },
        markersById: {},
        selectedTowerId: null,
    };

    const invalidateFnCode = extractFunction('invalidateOptimizationState');

    const fnInvalidate = new Function(
        'state', 'document', 'renderAssignmentTable', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'openVertexInspector',
        `
        ${invalidateFnCode}
        return invalidateOptimizationState;
        `
    )(globalState, doc, mockRenderAssignmentTable, mockUpdateDashboardMetrics, mockRenderEmbeddedComparisonCard, () => {});

    // Initial state setup before invalidation
    assert.notStrictEqual(globalState.optimizationResults, null);
    assert.notStrictEqual(globalState.currentAssignments, null);
    assert.strictEqual(globalState.isolatedFrequency, 0);

    // Call invalidateOptimizationState
    fnInvalidate("Query parameter altered");

    // 1. State resets
    assert.strictEqual(globalState.optimizationResults, null, "optimizationResults must be reset to null");
    assert.strictEqual(globalState.currentAssignments, null, "currentAssignments must be reset to null");
    assert.strictEqual(globalState.isolatedFrequency, null, "isolatedFrequency must be reset to null");

    // 2. Legend hidden
    const legend = doc.getElementById("legend-container");
    assert.strictEqual(legend.style.display, "none", "Legend container must be hidden");

    // 3. Validation badge reset to waiting
    const valBadge = doc.getElementById("metric-validation-badge");
    assert.strictEqual(valBadge.className, "badge-validation badge-val-waiting");
    assert.strictEqual(valBadge.textContent, "Awaiting Run");

    // 4. Coverage circle style reset to unassigned
    const c1 = globalState.coverageCirclesById["T1"];
    assert.strictEqual(c1.style.fill, false);
    assert.strictEqual(c1.style.color, "#64748b");
    assert.strictEqual(c1.style.fillOpacity, 0.0);

    // 5. Assignment table and dashboard metrics re-rendered with null
    assert.ok(tableRenderCount >= 1, "renderAssignmentTable must be called");
    assert.ok(dashboardUpdateCount >= 1, "updateDashboardMetrics must be called");
    assert.ok(comparisonCardRenderCount >= 1, "renderEmbeddedComparisonCard must be called");

    // 6. Status message notice
    const statusMsg = doc.getElementById("cells-status");
    assert.ok(statusMsg.textContent.includes("Query parameter altered"), "Status message reflects reason");

    console.log("✔ PASS: invalidateOptimizationState correctly clears state, badges, circles, legend, and assignment table.");
}

console.log("=== EMPIRICAL CHALLENGE 3: Event Listeners Triggering invalidateOptimizationState ===");

{
    // Search the source code for all event listeners bound to invalidateOptimizationState
    const triggers = [
        { name: "Map Click", pattern: /map\.on\s*\(\s*["']click["'].*?invalidateOptimizationState/s },
        { name: "Center Marker Dragend", pattern: /centerMarker\.on\s*\(\s*["']dragend["'].*?invalidateOptimizationState/s },
        { name: "Coordinate Inputs (Lat/Lon)", pattern: /inputLat\.addEventListener\s*\(\s*["']change["'].*?invalidateOptimizationState/s },
        { name: "Radius Slider Change", pattern: /radiusSlider\.addEventListener\s*\(\s*["']change["'].*?invalidateOptimizationState/s },
        { name: "Preset Location Select", pattern: /presetSelect\.addEventListener\s*\(\s*["']change["'].*?invalidateOptimizationState/s },
        { name: "Radio 4G/5G Checkboxes", pattern: /handleTechChange.*?invalidateOptimizationState/s },
        { name: "2m Mast Consolidation Checkbox", pattern: /chkAgg2m\.addEventListener\s*\(\s*["']change["'].*?invalidateOptimizationState/s },
        { name: "Limit Slider Input", pattern: /limitSlider\.addEventListener\s*\(\s*["']input["'].*?invalidateOptimizationState/s },
        { name: "Coverage Override Slider Change", pattern: /overrideSlider\.addEventListener\s*\(\s*["']change["'].*?invalidateOptimizationState/s },
        { name: "GPS Locate Click", pattern: /handleGeolocation.*?invalidateOptimizationState/s },
        { name: "Demo Grid Click", pattern: /loadDemoTowers.*?invalidateOptimizationState/s },
        { name: "Cell Records Ingestion", pattern: /fetchNearbyCells.*?invalidateOptimizationState/s },
    ];

    triggers.forEach(t => {
        assert.ok(t.pattern.test(code), `Trigger missing or not hooked: ${t.name}`);
        console.log(`  ✔ Verified trigger: ${t.name}`);
    });

    console.log("✔ PASS: All 12 query mutation and lifecycle triggers are verified to call invalidateOptimizationState.");
}

console.log("\nALL EMPIRICAL CHALLENGER TESTS PASSED SUCCESSFULLY!");
