/**
 * Milestone 1 Challenger 2 Iteration 2 Empirical Test Suite:
 * Assignment Table Display Lifecycle, Invalidation, and Real-Time Search Verification.
 *
 * Directly executes static/app.js functions:
 * - renderAssignmentTable
 * - invalidateOptimizationState
 * - resetOptimizationScoreboard
 * - applyAssignmentTableFilters
 * - initAssignmentTableEvents
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
        this.dataset = {};
        this.classList = {
            classes: new Set(),
            add: (cls) => this.classList.classes.add(cls),
            remove: (cls) => this.classList.classes.delete(cls),
            contains: (cls) => this.classList.classes.has(cls),
            toggle: (cls, force) => {
                if (force === undefined) {
                    if (this.classList.classes.has(cls)) {
                        this.classList.classes.delete(cls);
                        return false;
                    } else {
                        this.classList.classes.add(cls);
                        return true;
                    }
                } else if (force) {
                    this.classList.classes.add(cls);
                    return true;
                } else {
                    this.classList.classes.delete(cls);
                    return false;
                }
            }
        };
        this.style = {};
        this.eventListeners = {};
        this.attributes = {};
        this.children = [];
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

    querySelectorAll(selector) {
        // Simple mock for querySelectorAll
        if (selector === ".assignment-row" || selector.includes("tr.assignment-row")) {
            return this.children.filter(c => c.classList.contains("assignment-row"));
        }
        return [];
    }

    querySelector(selector) {
        const list = this.querySelectorAll(selector);
        return list.length > 0 ? list[0] : null;
    }

    appendChild(child) {
        this.children.push(child);
    }
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
        const res = [];
        for (const el of this.elements.values()) {
            if (selector === ".legend-chip" && el.classList.contains("legend-chip")) {
                res.push(el);
            }
        }
        return res;
    }

    querySelector(selector) {
        const list = this.querySelectorAll(selector);
        return list.length > 0 ? list[0] : null;
    }
}

console.log("=== EMPIRICAL CHALLENGE 1: renderAssignmentTable unhides #assignment-panel ===");
{
    const doc = new MockDocument();
    const panel = doc.getElementById("assignment-panel");
    panel.style.display = "none"; // initial hidden state as in index.html

    const tableBody = doc.getElementById("assignment-table-body");
    const countBadge = doc.getElementById("assignment-count-badge");

    const globalState = {
        cells: [
            { tower_id: "T1", label: "A", radio: "4G" },
            { tower_id: "T2", label: "B", radio: "5G" }
        ],
        optimizationResults: null,
        currentAssignments: null,
        adjacencyMap: new Map([["T1", []], ["T2", []]]),
        selectedTowerId: null,
        assignmentSearchQuery: "",
        isolatedFrequency: null
    };

    const renderAssignmentTableCode = extractFunction('renderAssignmentTable');
    const applyAssignmentTableFiltersCode = extractFunction('applyAssignmentTableFilters');

    const fnRenderAssignmentTable = new Function(
        'state', 'document', 'getSelectedAlgoKey', 'getFrequencyColor', 'selectCellFromTable',
        `
        ${applyAssignmentTableFiltersCode}
        ${renderAssignmentTableCode}
        return renderAssignmentTable;
        `
    )(globalState, doc, () => "dsatur", () => "#ff0000", () => {});

    // Call renderAssignmentTable
    fnRenderAssignmentTable({ "T1": 0, "T2": 1 }, globalState.cells);

    // Verify panel is now display: block
    assert.strictEqual(panel.style.display, "block", "renderAssignmentTable must set #assignment-panel to 'block'");
    assert.strictEqual(globalState.currentAssignments["T1"], 0);
    assert.strictEqual(globalState.currentAssignments["T2"], 1);
    console.log("✔ PASS: renderAssignmentTable sets #assignment-panel to visible ('block').");
}

console.log("=== EMPIRICAL CHALLENGE 2: invalidateOptimizationState hides #assignment-panel ===");
{
    const doc = new MockDocument();
    const panel = doc.getElementById("assignment-panel");
    panel.style.display = "block"; // currently visible after optimization

    const globalState = {
        cells: [
            { tower_id: "T1", label: "A", radio: "4G" },
            { tower_id: "T2", label: "B", radio: "5G" }
        ],
        optimizationResults: { dsatur: { coloring: { "T1": 0, "T2": 1 } } },
        currentAssignments: { "T1": 0, "T2": 1 },
        isolatedFrequency: 1,
        coverageCirclesById: {
            "T1": { setStyle: () => {} },
            "T2": { setStyle: () => {} }
        },
        selectedTowerId: null
    };

    const invalidateCode = extractFunction('invalidateOptimizationState');

    let renderAssignmentTableCalledWith = undefined;
    const mockRenderAssignmentTable = (coloring, cells) => {
        renderAssignmentTableCalledWith = { coloring, cells };
        // Simulates renderAssignmentTable setting display: block
        panel.style.display = "block";
    };

    const fnInvalidate = new Function(
        'state', 'document', 'renderAssignmentTable', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'openVertexInspector',
        `
        ${invalidateCode}
        return invalidateOptimizationState;
        `
    )(globalState, doc, mockRenderAssignmentTable, () => {}, () => {}, () => {});

    fnInvalidate("User moved map center");

    // After invalidateOptimizationState completes:
    assert.strictEqual(renderAssignmentTableCalledWith.coloring, null, "Must call renderAssignmentTable with null coloring");
    assert.strictEqual(panel.style.display, "none", "invalidateOptimizationState must ensure #assignment-panel is 'none'");
    assert.strictEqual(globalState.optimizationResults, null, "optimizationResults must be reset");
    assert.strictEqual(globalState.currentAssignments, null, "currentAssignments must be reset");
    assert.strictEqual(globalState.isolatedFrequency, null, "isolatedFrequency must be reset");

    console.log("✔ PASS: invalidateOptimizationState resets state and sets #assignment-panel to 'none'.");
}

console.log("=== EMPIRICAL CHALLENGE 3: resetOptimizationScoreboard hides #assignment-panel ===");
{
    const doc = new MockDocument();
    const panel = doc.getElementById("assignment-panel");
    panel.style.display = "block"; // currently visible

    const globalState = {
        cells: [
            { tower_id: "T1", label: "A", radio: "4G" }
        ],
        optimizationResults: { dsatur: {} },
        interferenceEdges: [{ source_id: "T1", target_id: "T2" }],
        isolatedFrequency: 1,
        coverageCirclesById: {
            "T1": { setStyle: () => {} }
        }
    };

    const resetScoreboardCode = extractFunction('resetOptimizationScoreboard');

    let renderAssignmentTableCalled = false;
    const mockRenderAssignmentTable = (coloring, cells) => {
        renderAssignmentTableCalled = true;
        panel.style.display = "block";
    };

    const fnResetScoreboard = new Function(
        'state', 'document', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'renderAssignmentTable',
        `
        ${resetScoreboardCode}
        return resetOptimizationScoreboard;
        `
    )(globalState, doc, () => {}, () => {}, mockRenderAssignmentTable);

    fnResetScoreboard();

    assert.strictEqual(renderAssignmentTableCalled, true, "renderAssignmentTable must be called");
    assert.strictEqual(panel.style.display, "none", "resetOptimizationScoreboard must set #assignment-panel to 'none'");
    assert.strictEqual(globalState.optimizationResults, null);
    assert.strictEqual(globalState.interferenceEdges.length, 0);
    assert.strictEqual(globalState.isolatedFrequency, null);

    console.log("✔ PASS: resetOptimizationScoreboard sets #assignment-panel to 'none'.");
}

console.log("=== EMPIRICAL CHALLENGE 4: Rapid Alternating Render / Invalidate Lifecycle Stress ===");
{
    const doc = new MockDocument();
    const panel = doc.getElementById("assignment-panel");
    panel.style.display = "none";

    const globalState = {
        cells: [{ tower_id: "T1", label: "A", radio: "4G" }],
        optimizationResults: null,
        currentAssignments: null,
        adjacencyMap: new Map([["T1", []]]),
        selectedTowerId: null,
        coverageCirclesById: { "T1": { setStyle: () => {} } }
    };

    const renderCode = extractFunction('renderAssignmentTable');
    const invalidateCode = extractFunction('invalidateOptimizationState');
    const applyFiltersCode = extractFunction('applyAssignmentTableFilters');

    // Wire up real functions
    const scope = new Function(
        'state', 'document', 'getSelectedAlgoKey', 'getFrequencyColor', 'selectCellFromTable', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'openVertexInspector',
        `
        ${applyFiltersCode}
        ${renderCode}
        ${invalidateCode}
        return { renderAssignmentTable, invalidateOptimizationState };
        `
    )(globalState, doc, () => "dsatur", () => "#00ff00", () => {}, () => {}, () => {}, () => {});

    // Loop 100 cycles of Render -> Invalidate -> Render -> Invalidate
    for (let cycle = 0; cycle < 100; cycle++) {
        // Optimize / render
        globalState.optimizationResults = { dsatur: { coloring: { "T1": 0 } } };
        scope.renderAssignmentTable({ "T1": 0 }, globalState.cells);
        assert.strictEqual(panel.style.display, "block", `Cycle ${cycle}: display must be 'block' after render`);

        // Invalidate
        scope.invalidateOptimizationState(`Cycle ${cycle} test mutation`);
        assert.strictEqual(panel.style.display, "none", `Cycle ${cycle}: display must be 'none' after invalidate`);
    }

    console.log("✔ PASS: 100 rapid render/invalidate cycles maintain 100% display state consistency.");
}

console.log("=== EMPIRICAL CHALLENGE 5: Null DOM Element Graceful Handling ===");
{
    // Verify that if #assignment-panel is absent (e.g. headless or altered DOM), no unhandled exceptions are thrown
    const emptyDoc = {
        getElementById: () => null,
        querySelectorAll: () => []
    };

    const globalState = {
        cells: [{ tower_id: "T1", label: "A" }],
        optimizationResults: null,
        currentAssignments: null
    };

    const renderCode = extractFunction('renderAssignmentTable');
    const invalidateCode = extractFunction('invalidateOptimizationState');
    const resetScoreboardCode = extractFunction('resetOptimizationScoreboard');

    const fnRender = new Function('state', 'document', 'getSelectedAlgoKey', 'getFrequencyColor', 'selectCellFromTable', `${renderCode}; return renderAssignmentTable;`)(globalState, emptyDoc, () => "dsatur", () => "#000", () => {});
    const fnInvalidate = new Function('state', 'document', 'renderAssignmentTable', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'openVertexInspector', `${invalidateCode}; return invalidateOptimizationState;`)(globalState, emptyDoc, () => {}, () => {}, () => {}, () => {});
    const fnReset = new Function('state', 'document', 'updateDashboardMetrics', 'renderEmbeddedComparisonCard', 'renderAssignmentTable', `${resetScoreboardCode}; return resetOptimizationScoreboard;`)(globalState, emptyDoc, () => {}, () => {}, () => {});

    // None of these should throw
    assert.doesNotThrow(() => fnRender(null, []));
    assert.doesNotThrow(() => fnInvalidate("Missing DOM test"));
    assert.doesNotThrow(() => fnReset());

    console.log("✔ PASS: All table functions safely guard against null DOM elements.");
}

console.log("=== EMPIRICAL CHALLENGE 6: Search Input & Clear Button Binding & Filtering ===");
{
    const doc = new MockDocument();
    const searchInput = doc.getElementById("assignment-search");
    const clearBtn = doc.getElementById("btn-assignment-search-clear");
    const tableBody = doc.getElementById("assignment-table-body");
    const countBadge = doc.getElementById("assignment-count-badge");

    // Add 3 mock rows to tableBody
    const r1 = new MockElement("assignment-row-T1");
    r1.classList.add("assignment-row");
    r1.dataset = { towerId: "T1", label: "Alpha", radio: "4G", channel: "1" };
    tableBody.appendChild(r1);

    const r2 = new MockElement("assignment-row-T2");
    r2.classList.add("assignment-row");
    r2.dataset = { towerId: "T2", label: "Beta", radio: "5G", channel: "2" };
    tableBody.appendChild(r2);

    const r3 = new MockElement("assignment-row-T3");
    r3.classList.add("assignment-row");
    r3.dataset = { towerId: "T3", label: "Gamma", radio: "4G", channel: "1" };
    tableBody.appendChild(r3);

    const globalState = {
        cells: [{ tower_id: "T1" }, { tower_id: "T2" }, { tower_id: "T3" }],
        assignmentSearchQuery: "",
        isolatedFrequency: null
    };

    const applyFiltersCode = extractFunction('applyAssignmentTableFilters');
    const initEventsCode = extractFunction('initAssignmentTableEvents');

    new Function(
        'state', 'document',
        `
        ${applyFiltersCode}
        ${initEventsCode}
        initAssignmentTableEvents();
        `
    )(globalState, doc);

    clearBtn.style.display = "none"; // initial state from index.html:470
    assert.strictEqual(clearBtn.style.display, "none", "Clear button hidden when search query empty");

    // Simulate user typing "5g"
    searchInput.value = "5G";
    searchInput.trigger("input", { target: searchInput });

    assert.strictEqual(globalState.assignmentSearchQuery, "5g");
    assert.strictEqual(clearBtn.style.display, "inline-block", "Clear button displayed when query present");
    assert.strictEqual(r1.style.display, "none", "Row 1 (4G) hidden");
    assert.strictEqual(r2.style.display, "", "Row 2 (5G) visible");
    assert.strictEqual(r3.style.display, "none", "Row 3 (4G) hidden");
    assert.strictEqual(countBadge.textContent, "1 / 3 cells");

    // Simulate user typing channel "f1"
    searchInput.value = "f1";
    searchInput.trigger("input", { target: searchInput });

    assert.strictEqual(r1.style.display, "", "Row 1 (f1) visible");
    assert.strictEqual(r2.style.display, "none", "Row 2 (f2) hidden");
    assert.strictEqual(r3.style.display, "", "Row 3 (f1) visible");
    assert.strictEqual(countBadge.textContent, "2 / 3 cells");

    // Simulate user clicking clear button
    clearBtn.trigger("click");

    assert.strictEqual(searchInput.value, "", "Input value cleared");
    assert.strictEqual(globalState.assignmentSearchQuery, "", "Search query reset");
    assert.strictEqual(clearBtn.style.display, "none", "Clear button hidden again");
    assert.strictEqual(r1.style.display, "", "Row 1 visible");
    assert.strictEqual(r2.style.display, "", "Row 2 visible");
    assert.strictEqual(r3.style.display, "", "Row 3 visible");
    assert.strictEqual(countBadge.textContent, "3 cells");

    console.log("✔ PASS: Search input filtering and clear button lifecycle verified end-to-end.");
}

console.log("\nALL CHALLENGER 2 ITERATION 2 EMPIRICAL LIFECYCLE TESTS PASSED SUCCESSFULLY!");
