/**
 * Milestone 2 Challenger 2 Empirical Stress Test Harness
 * Adversarial Functional & Regression Verification
 * 
 * Verifies:
 * 1. renderAssignmentTable DOM lifecycle, edge cases, missing data, and row generation
 * 2. applyAssignmentTableFilters search filtering, case-insensitivity, and clearing
 * 3. selectCellFromTable synchronization with map panTo, marker popup, and inspector
 * 4. updateAssignmentTableRowSelection row highlighting and scrolling
 * 5. renderLegend, isolateFrequency, and clearFrequencyIsolation channel isolation
 * 6. invalidateOptimizationState state nulling, DOM cleanup, badge updates, and reason reporting
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const appCode = fs.readFileSync(srcPath, 'utf8');

// Lightweight Mock DOM
class MockClassList {
    constructor() {
        this.classes = new Set();
    }
    add(...cls) { cls.forEach(c => this.classes.add(c)); }
    remove(...cls) { cls.forEach(c => this.classes.delete(c)); }
    contains(cls) { return this.classes.has(cls); }
    toString() { return Array.from(this.classes).join(' '); }
}

class MockElement {
    constructor(id = '', tagName = 'div') {
        this.id = id;
        this.tagName = tagName.toUpperCase();
        this.textContent = '';
        this.innerHTML = '';
        this.value = '';
        this.style = {};
        this.classList = new MockClassList();
        this.attributes = {};
        this.dataset = {};
        this.children = [];
        this.listeners = {};
        this._scrolled = false;
    }

    setAttribute(k, v) { this.attributes[k] = String(v); }
    getAttribute(k) { return this.attributes[k]; }
    addEventListener(event, fn) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(fn);
    }
    dispatchEvent(event) {
        if (this.listeners[event.type]) {
            this.listeners[event.type].forEach(fn => fn(event));
        }
    }
    scrollIntoView(opts) { this._scrolled = true; }
    focus() { this._focused = true; }
}

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

    querySelectorAll(selector) {
        const results = [];
        for (const el of this.elements.values()) {
            if (selector.startsWith('.') && el.classList.contains(selector.slice(1))) {
                results.push(el);
            }
        }
        return results;
    }

    querySelector(selector) {
        const all = this.querySelectorAll(selector);
        return all.length > 0 ? all[0] : null;
    }
}

// Function extractor from static/app.js
function extractFunction(name) {
    let idx = appCode.indexOf(`async function ${name}`);
    if (idx === -1) idx = appCode.indexOf(`function ${name}`);
    assert(idx !== -1, `Function ${name} not found in static/app.js`);
    const openBrace = appCode.indexOf('{', idx);
    let count = 1;
    let i = openBrace + 1;
    while (i < appCode.length && count > 0) {
        if (appCode[i] === '{') count++;
        else if (appCode[i] === '}') count--;
        i++;
    }
    return appCode.slice(idx, i);
}

console.log("=== EMPIRICAL CHALLENGE: Milestone 2 Functional Stress Test Suite ===");

// ---------------------------------------------------------
// Test 1: renderAssignmentTable & applyAssignmentTableFilters
// ---------------------------------------------------------
{
    console.log("\n[TEST 1] renderAssignmentTable & Search Filter Verification");
    const doc = new MockDocument();
    
    // Prepare DOM elements
    const tbody = doc.getElementById("assignment-table-body");
    const countBadge = doc.getElementById("assignment-count-badge");
    const panel = doc.getElementById("assignment-panel");
    const searchInput = doc.getElementById("assignment-search-input");
    const btnClear = doc.getElementById("btn-clear-assignment-search");

    const state = {
        cells: [
            { tower_id: "T1", cell_id: "101", label: "Alpha", radio: "4G", range_m: 800, latitude: 28.5, longitude: 77.2 },
            { tower_id: "T2", cell_id: "102", label: "Beta", radio: "5G", range_m: 500, latitude: 28.6, longitude: 77.3 },
            { tower_id: "T3", cell_id: "103", label: "Gamma", radio: "4G", range_m: 1000, latitude: 28.7, longitude: 77.4 }
        ],
        optimizationResults: {
            dsatur: { coloring: { "T1": 0, "T2": 1, "T3": 0 } }
        },
        degreeMap: { "T1": 2, "T2": 1, "T3": 1 },
        selectedTowerId: "T2"
    };

    // Extract functions
    const fnApplyFiltersCode = extractFunction('applyAssignmentTableFilters');
    const fnRenderTableCode = extractFunction('renderAssignmentTable');
    const fnGetFrequencyColorCode = extractFunction('getFrequencyColor');
    const fnInitTableEventsCode = extractFunction('initAssignmentTableEvents');

    const context = {
        state,
        document: doc,
        getSelectedAlgoKey: () => "dsatur"
    };

    const baseColorsCode = `const BASE_FREQUENCY_COLORS = [
        "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4",
        "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#a855f7", "#eab308",
        "#6366f1", "#d946ef", "#22c55e", "#64748b",
    ];`;

    const envFn = new Function(
        'state', 'document', 'getSelectedAlgoKey',
        `
        ${baseColorsCode}
        ${fnGetFrequencyColorCode}
        ${fnApplyFiltersCode}
        ${fnRenderTableCode}
        ${fnInitTableEventsCode}
        return { renderAssignmentTable, applyAssignmentTableFilters, initAssignmentTableEvents };
        `
    );

    const { renderAssignmentTable, applyAssignmentTableFilters, initAssignmentTableEvents } = envFn(state, doc, () => "dsatur");

    // Case 1A: Empty cells
    renderAssignmentTable(null, []);
    assert.strictEqual(panel.style.display, "none", "Empty cells should hide panel");
    assert.strictEqual(countBadge.textContent, "0", "Count badge should be 0");
    assert.ok(tbody.innerHTML.includes("No cell records loaded"), "Empty row text displayed");
    console.log("  [PASS] 1A. Empty cell list properly resets table and hides panel.");

    // Case 1B: Null cells
    renderAssignmentTable(null, null);
    assert.strictEqual(panel.style.display, "none", "Null cells should hide panel");
    console.log("  [PASS] 1B. Null cell list handled safely without crash.");

    // Case 1C: Normal render with assignments
    renderAssignmentTable({ "T1": 0, "T2": 1, "T3": 0 }, state.cells);
    assert.strictEqual(panel.style.display, "flex", "Populated cells should show panel as flex");
    assert.strictEqual(countBadge.textContent, "3", "Count badge should be 3");
    assert.ok(tbody.innerHTML.includes('data-tower-id="T1"'), "T1 row rendered");
    assert.ok(tbody.innerHTML.includes('selected-row'), "Selected row class applied for T2");
    assert.ok(tbody.innerHTML.includes('badge-tech-4g'), "4G badge rendered");
    assert.ok(tbody.innerHTML.includes('badge-tech-5g'), "5G badge rendered");
    assert.ok(tbody.innerHTML.includes('f1'), "Channel f1 rendered");
    assert.ok(tbody.innerHTML.includes('f2'), "Channel f2 rendered");
    console.log("  [PASS] 1C. Assignment table successfully rendered 3 rows with channels and selection.");

    // Case 1D: Search filter interaction
    initAssignmentTableEvents();
    // Simulate rows in mock DOM
    const row1 = new MockElement('', 'tr'); row1.classList.add('assignment-row'); row1.textContent = "Alpha T1 4G f1 800m 2";
    const row2 = new MockElement('', 'tr'); row2.classList.add('assignment-row'); row2.textContent = "Beta T2 5G f2 500m 1";
    const row3 = new MockElement('', 'tr'); row3.classList.add('assignment-row'); row3.textContent = "Gamma T3 4G f1 1000m 1";
    doc.elements.set('row1', row1);
    doc.elements.set('row2', row2);
    doc.elements.set('row3', row3);

    // Search for "5G"
    searchInput.value = "5G";
    applyAssignmentTableFilters();
    assert.strictEqual(row1.style.display, "none", "Row 1 hidden for 5G filter");
    assert.strictEqual(row2.style.display, "", "Row 2 visible for 5G filter");
    assert.strictEqual(row3.style.display, "none", "Row 3 hidden for 5G filter");
    console.log("  [PASS] 1D. Search filter strictly isolated 5G row.");

    // Clear search button
    btnClear.dispatchEvent({ type: "click" });
    assert.strictEqual(searchInput.value, "", "Search input cleared");
    assert.strictEqual(row1.style.display, "", "Row 1 restored");
    assert.strictEqual(row2.style.display, "", "Row 2 restored");
    assert.strictEqual(row3.style.display, "", "Row 3 restored");
    console.log("  [PASS] 1E. Search clear button cleanly resets all rows to visible.");
}

// ---------------------------------------------------------
// Test 2: selectCellFromTable & updateAssignmentTableRowSelection
// ---------------------------------------------------------
{
    console.log("\n[TEST 2] selectCellFromTable & Row Selection Sync");
    const doc = new MockDocument();

    let pannedCoords = null;
    let inspectedTowerId = null;
    let popupOpened = false;

    const state = {
        cells: [
            { tower_id: "T1", latitude: 28.5, longitude: 77.2 },
            { tower_id: "T2", latitude: 28.6, longitude: 77.3 }
        ],
        map: {
            panTo: (coords) => { pannedCoords = coords; }
        },
        markersById: {
            "T1": { openPopup: () => { popupOpened = true; } }
        }
    };

    const fnSelectCellCode = extractFunction('selectCellFromTable');
    const fnUpdateSelectionCode = extractFunction('updateAssignmentTableRowSelection');

    const envFn = new Function(
        'state', 'document', 'openVertexInspector',
        `
        ${fnSelectCellCode}
        ${fnUpdateSelectionCode}
        return { selectCellFromTable, updateAssignmentTableRowSelection };
        `
    );

    const { selectCellFromTable, updateAssignmentTableRowSelection } = envFn(
        state,
        doc,
        (tid) => { inspectedTowerId = tid; }
    );

    // Test valid selection
    selectCellFromTable("T1");
    assert.deepStrictEqual(pannedCoords, [28.5, 77.2], "Map panned to T1 coordinates");
    assert.strictEqual(inspectedTowerId, "T1", "Inspector opened for T1");
    assert.strictEqual(popupOpened, true, "Marker popup opened for T1");
    console.log("  [PASS] 2A. selectCellFromTable correctly synchronizes map pan, inspector, and popup.");

    // Test non-existent tower ID
    pannedCoords = null;
    inspectedTowerId = null;
    popupOpened = false;
    selectCellFromTable("INVALID_ID");
    assert.strictEqual(pannedCoords, null, "Map should not pan on invalid ID");
    assert.strictEqual(inspectedTowerId, null, "Inspector should not open on invalid ID");
    assert.strictEqual(popupOpened, false, "Popup should not open on invalid ID");
    console.log("  [PASS] 2B. selectCellFromTable gracefully ignores invalid tower ID.");

    // Test row selection synchronization
    const rowT1 = new MockElement('', 'tr'); rowT1.classList.add('assignment-row'); rowT1.dataset.towerId = "T1";
    const rowT2 = new MockElement('', 'tr'); rowT2.classList.add('assignment-row'); rowT2.dataset.towerId = "T2";
    doc.elements.set('rowT1', rowT1);
    doc.elements.set('rowT2', rowT2);

    updateAssignmentTableRowSelection("T2");
    assert.strictEqual(rowT1.classList.contains("selected-row"), false, "T1 row deselected");
    assert.strictEqual(rowT2.classList.contains("selected-row"), true, "T2 row selected");
    assert.strictEqual(rowT2._scrolled, true, "T2 row scrolled into view");
    console.log("  [PASS] 2C. updateAssignmentTableRowSelection sets class and calls scrollIntoView.");
}

// ---------------------------------------------------------
// Test 3: Channel Isolation (renderLegend, isolateFrequency, clearFrequencyIsolation)
// ---------------------------------------------------------
{
    console.log("\n[TEST 3] Interactive Channel Isolation & Legend Workflow");
    const doc = new MockDocument();

    const legendContainer = doc.getElementById("legend-container");
    const legendChips = doc.getElementById("legend-chips");

    let marker1Style = { opacity: "1.0", filter: "none" };
    let marker2Style = { opacity: "1.0", filter: "none" };
    let circle1Style = {};
    let circle2Style = {};

    const state = {
        activeIsolatedFreq: null,
        optimizationResults: {
            dsatur: {
                coloring: { "T1": 0, "T2": 1, "T3": 0 }
            }
        },
        cells: [
            { tower_id: "T1" },
            { tower_id: "T2" },
            { tower_id: "T3" }
        ],
        markersById: {
            "T1": { _icon: { style: marker1Style } },
            "T2": { _icon: { style: marker2Style } }
        },
        coverageCirclesById: {
            "T1": { setStyle: (s) => { Object.assign(circle1Style, s); } },
            "T2": { setStyle: (s) => { Object.assign(circle2Style, s); } }
        }
    };

    const fnGetFrequencyColorCode = extractFunction('getFrequencyColor');
    const fnRenderLegendCode = extractFunction('renderLegend');
    const fnIsolateFreqCode = extractFunction('isolateFrequency');
    const fnClearIsolationCode = extractFunction('clearFrequencyIsolation');

    const baseColorsCode = `const BASE_FREQUENCY_COLORS = [
        "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4",
        "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#a855f7", "#eab308",
        "#6366f1", "#d946ef", "#22c55e", "#64748b",
    ];`;

    const envFn = new Function(
        'state', 'document', 'getSelectedAlgoKey',
        `
        ${baseColorsCode}
        ${fnGetFrequencyColorCode}
        ${fnRenderLegendCode}
        ${fnIsolateFreqCode}
        ${fnClearIsolationCode}
        return { renderLegend, isolateFrequency, clearFrequencyIsolation };
        `
    );

    const { renderLegend, isolateFrequency, clearFrequencyIsolation } = envFn(state, doc, () => "dsatur");

    // Case 3A: Render legend with 2 frequencies (f1: 2 towers, f2: 1 tower)
    renderLegend({ "T1": 0, "T2": 1, "T3": 0 });
    assert.strictEqual(legendContainer.style.display, "flex", "Legend container visible");
    assert.ok(legendChips.innerHTML.includes("All Channels"), "All Channels chip rendered");
    assert.ok(legendChips.innerHTML.includes("f1"), "Frequency f1 chip rendered");
    assert.ok(legendChips.innerHTML.includes("f2"), "Frequency f2 chip rendered");
    assert.ok(legendChips.innerHTML.includes("(2)"), "f1 count is 2");
    assert.ok(legendChips.innerHTML.includes("(1)"), "f2 count is 1");
    console.log("  [PASS] 3A. Legend rendered correctly with frequency counts and chips.");

    // Case 3B: Isolate frequency 0 (f1)
    isolateFrequency(0);
    assert.strictEqual(state.activeIsolatedFreq, 0, "state.activeIsolatedFreq set to 0");
    assert.strictEqual(marker1Style.opacity, "1.0", "T1 (f1) marker fully visible");
    assert.strictEqual(marker1Style.filter, "none", "T1 (f1) marker has no grayscale");
    assert.strictEqual(marker2Style.opacity, "0.15", "T2 (f2) marker dimmed");
    assert.strictEqual(marker2Style.filter, "grayscale(80%)", "T2 (f2) marker grayscaled");
    assert.strictEqual(circle1Style.opacity, 0.9, "T1 circle highlighted");
    assert.strictEqual(circle2Style.opacity, 0.05, "T2 circle dimmed");
    console.log("  [PASS] 3B. isolateFrequency(0) correctly highlights matching towers and dims non-matching.");

    // Case 3C: Clear frequency isolation
    clearFrequencyIsolation();
    assert.strictEqual(state.activeIsolatedFreq, null, "state.activeIsolatedFreq reset to null");
    assert.strictEqual(marker1Style.opacity, "1.0", "T1 restored to full opacity");
    assert.strictEqual(marker1Style.filter, "none", "T1 filter restored");
    assert.strictEqual(marker2Style.opacity, "1.0", "T2 restored to full opacity");
    assert.strictEqual(marker2Style.filter, "none", "T2 filter restored");
    console.log("  [PASS] 3C. clearFrequencyIsolation() restored full visibility to all towers.");
}

// ---------------------------------------------------------
// Test 4: invalidateOptimizationState
// ---------------------------------------------------------
{
    console.log("\n[TEST 4] State Invalidation & DOM Reset");
    const doc = new MockDocument();

    const legendContainer = doc.getElementById("legend-container");
    legendContainer.style.display = "flex";

    const valBadge = doc.getElementById("metric-validation-badge");
    valBadge.className = "badge-validation badge-val-pass";
    valBadge.textContent = "100% Valid";

    const pillDsatur = doc.getElementById("pill-dsatur");
    pillDsatur.classList.add("best-algo-pill");

    const statusMsg = doc.getElementById("cells-status");

    let circleResetCount = 0;
    const state = {
        cells: [
            { tower_id: "T1", label: "A", cell_id: "101" },
            { tower_id: "T2", label: "B", cell_id: "102" }
        ],
        optimizationResults: { dsatur: { coloring: { "T1": 0, "T2": 1 } } },
        currentAssignments: { "T1": 0, "T2": 1 },
        activeIsolatedFreq: 0,
        coverageCirclesById: {
            "T1": { setStyle: () => { circleResetCount++; } },
            "T2": { setStyle: () => { circleResetCount++; } }
        }
    };

    let tableRenderedWithAssignments = "not called";
    let dashboardUpdated = false;
    let cardRendered = false;

    const fnInvalidateCode = extractFunction('invalidateOptimizationState');

    const envFn = new Function(
        'state', 'document', 'renderAssignmentTable', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'openVertexInspector',
        `
        ${fnInvalidateCode}
        return invalidateOptimizationState;
        `
    );

    const invalidateOptimizationState = envFn(
        state,
        doc,
        (assignments) => { tableRenderedWithAssignments = assignments; },
        () => { dashboardUpdated = true; },
        () => { cardRendered = true; },
        () => {}
    );

    // Call invalidation with reason
    invalidateOptimizationState("Query radius changed");

    assert.strictEqual(state.optimizationResults, null, "optimizationResults cleared");
    assert.strictEqual(state.currentAssignments, null, "currentAssignments cleared");
    assert.strictEqual(state.activeIsolatedFreq, null, "activeIsolatedFreq cleared");
    assert.strictEqual(legendContainer.style.display, "none", "Legend container hidden");
    assert.strictEqual(valBadge.textContent, "Awaiting Run", "Validation badge reset to Awaiting Run");
    assert.strictEqual(valBadge.className, "badge-validation badge-val-waiting", "Validation badge class reset");
    assert.strictEqual(pillDsatur.classList.contains("best-algo-pill"), false, "best-algo-pill removed");
    assert.strictEqual(circleResetCount, 2, "Both coverage circles reset");
    assert.strictEqual(tableRenderedWithAssignments, null, "Table re-rendered with null assignments");
    assert.strictEqual(dashboardUpdated, true, "Dashboard metrics updated");
    assert.strictEqual(cardRendered, true, "Comparison card re-rendered");
    assert.ok(statusMsg.textContent.includes("Query radius changed"), "Status message reflects invalidation reason");
    console.log("  [PASS] 4A. invalidateOptimizationState thoroughly cleans up state, DOM, badges, and circles.");
}

console.log("\n=======================================================");
console.log("ALL 4 EMPIRICAL ADVERSARIAL STRESS TEST SUITES PASSED!");
console.log("Zero functional regressions detected.");
console.log("=======================================================\n");
