const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');

// Mock DOM elements
class MockClassList {
    constructor() { this.classes = new Set(); }
    add(...args) { args.forEach(c => this.classes.add(c)); }
    remove(...args) { args.forEach(c => this.classes.delete(c)); }
    contains(c) { return this.classes.has(c); }
}

class MockElement {
    constructor(id) {
        this.id = id;
        this.classList = new MockClassList();
        this.attributes = {};
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
}

const elements = {
    "tab-map-view": new MockElement("tab-map-view"),
    "tab-graph-view": new MockElement("tab-graph-view"),
    "map": new MockElement("map"),
    "graph-canvas-container": new MockElement("graph-canvas-container"),
};

let stoppedSimulationCount = 0;
let updateMapVisualStylesCount = 0;
let renderGraphExplorerCount = 0;
let mapInvalidateCount = 0;

const state = {
    activeView: "map",
    cells: [{ tower_id: "tower-1" }, { tower_id: "tower-2" }],
    optimizationResults: {
        dsatur: { coloring: { "tower-1": 0, "tower-2": 1 }, color_count: 2 },
    },
    selectedTowerId: "tower-1",
    map: {
        invalidateSize: () => { mapInvalidateCount++; }
    }
};

function extractFunction(name) {
    const idx = code.indexOf(`function ${name}`);
    assert(idx !== -1, `Function ${name} not found`);
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

const switchFn = new Function(
    'state', 'document', 'stopGraphSimulation', 'updateMapVisualStyles', 'renderGraphExplorer', 'requestAnimationFrame', 'setTimeout',
    `
    ${extractFunction('switchVisualizationView')}
    return switchVisualizationView;
    `
)(
    state,
    { getElementById: (id) => elements[id] || null },
    () => { stoppedSimulationCount++; },
    () => { updateMapVisualStylesCount++; },
    () => { renderGraphExplorerCount++; },
    (cb) => cb(), // synchronous raf
    (cb, ms) => cb() // synchronous timeout
);

console.log("=== EMPIRICAL CHALLENGE 4: View Switching State Preservation ===");

const initialCells = JSON.stringify(state.cells);
const initialOpt = JSON.stringify(state.optimizationResults);
const initialSelected = state.selectedTowerId;

// 1. Switch from Map to Graph
switchFn("graph");
assert.strictEqual(state.activeView, "graph");
assert.strictEqual(elements["tab-graph-view"].classList.contains("active"), true);
assert.strictEqual(elements["tab-map-view"].classList.contains("active"), false);
assert.strictEqual(elements["graph-canvas-container"].classList.contains("active-layer"), true);
assert.strictEqual(elements["map"].classList.contains("active-layer"), false);
assert.strictEqual(renderGraphExplorerCount, 1);

// State preservation verification
assert.strictEqual(JSON.stringify(state.cells), initialCells, "state.cells corrupted after switch to graph!");
assert.strictEqual(JSON.stringify(state.optimizationResults), initialOpt, "state.optimizationResults corrupted after switch to graph!");
assert.strictEqual(state.selectedTowerId, initialSelected, "state.selectedTowerId corrupted after switch to graph!");
console.log("  [PASS] 1. Switch Map -> Graph preserves all state.");

// 2. Switch from Graph to Map
switchFn("map");
assert.strictEqual(state.activeView, "map");
assert.strictEqual(elements["tab-map-view"].classList.contains("active"), true);
assert.strictEqual(elements["tab-graph-view"].classList.contains("active"), false);
assert.strictEqual(elements["map"].classList.contains("active-layer"), true);
assert.strictEqual(elements["graph-canvas-container"].classList.contains("active-layer"), false);
assert.strictEqual(stoppedSimulationCount, 1);
assert.strictEqual(updateMapVisualStylesCount, 1);
assert.strictEqual(mapInvalidateCount, 1);

// State preservation verification
assert.strictEqual(JSON.stringify(state.cells), initialCells, "state.cells corrupted after switch to map!");
assert.strictEqual(JSON.stringify(state.optimizationResults), initialOpt, "state.optimizationResults corrupted after switch to map!");
assert.strictEqual(state.selectedTowerId, initialSelected, "state.selectedTowerId corrupted after switch to map!");
console.log("  [PASS] 2. Switch Graph -> Map preserves all state.");

// 3. Stress-test rapid toggling (100 iterations)
for (let i = 0; i < 100; i++) {
    const target = (i % 2 === 0) ? "graph" : "map";
    switchFn(target);
    assert.strictEqual(state.activeView, target);
    assert.strictEqual(JSON.stringify(state.cells), initialCells);
    assert.strictEqual(JSON.stringify(state.optimizationResults), initialOpt);
    assert.strictEqual(state.selectedTowerId, initialSelected);
}
console.log("  [PASS] 3. 100 rapid switch iterations preserved state with 0 corruption.");

// 4. Missing DOM elements resilience
const resilientSwitchFn = new Function(
    'state', 'document', 'stopGraphSimulation', 'updateMapVisualStyles', 'renderGraphExplorer', 'requestAnimationFrame', 'setTimeout',
    `
    ${extractFunction('switchVisualizationView')}
    return switchVisualizationView;
    `
)(
    state,
    { getElementById: () => null }, // All elements return null
    () => {}, // stopGraphSimulation
    () => {}, // updateMapVisualStyles
    () => {}, // renderGraphExplorer
    (cb) => cb(), // requestAnimationFrame
    (cb, ms) => cb() // setTimeout
);

assert.doesNotThrow(() => {
    resilientSwitchFn("graph");
    resilientSwitchFn("map");
}, "switchVisualizationView threw when DOM elements returned null!");
console.log("  [PASS] 4. Null DOM elements handled without exception.");

console.log("ALL View Switching state preservation tests PASSED successfully!");
