const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');

function extractFunction(name) {
    let idx = code.indexOf(`async function ${name}`);
    if (idx === -1) idx = code.indexOf(`function ${name}`);
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

console.log("=== EMPIRICAL CHALLENGE 1: Headless DOM Null Safety Stress Test ===");

// Scenario 1: openVertexInspector with ALL elements returning null except drawer container
{
    const state = {
        selectedTowerId: null,
        cellsById: {
            "T1": {
                tower_id: "T1",
                label: "A",
                cell_id: 101,
                radio: "LTE",
                latitude: 28.6,
                longitude: 77.2,
                range_m: 800,
                is_range_estimated: true,
                mcc: 404,
                mnc: 45,
                lac: 12,
            }
        },
        optimizationResults: {
            dsatur: {
                coloring: { "T1": 0 }
            }
        },
        adjacencyMap: new Map([["T1", []]]),
        interferenceEdges: [],
        activeView: "map",
    };

    const drawer = {
        classList: { add: () => {} },
        setAttribute: () => {}
    };

    // document where drawer exists, but all other 14 inner elements return null
    const doc = {
        getElementById: (id) => {
            if (id === "vertex-inspector") return drawer;
            return null; // ALL inner elements missing
        }
    };

    const fnOvi = new Function(
        'state', 'document', 'updateMapVisualStyles', 'getSelectedAlgoKey', 'setElemText', 'setElemHtml', 'getFrequencyColor', 'renderGraphExplorer',
        `
        ${extractFunction('setElemText')}
        ${extractFunction('setElemHtml')}
        ${extractFunction('openVertexInspector')}
        return openVertexInspector;
        `
    )(
        state,
        doc,
        () => {}, // updateMapVisualStyles
        () => "dsatur",
        (id, text) => { const el = doc.getElementById(id); if (el) el.textContent = text; },
        (id, html) => { const el = doc.getElementById(id); if (el) el.innerHTML = html; },
        () => "#3b82f6",
        () => {}
    );

    assert.doesNotThrow(() => {
        fnOvi("T1");
    }, "openVertexInspector threw when inner DOM elements were null!");

    assert.strictEqual(state.selectedTowerId, "T1");
    console.log("  [PASS] 1. openVertexInspector survived 100% null inner elements without error.");

    // Scenario 1B: vertex-inspector itself is null
    const docNull = { getElementById: () => null };
    const fnOviNull = new Function(
        'state', 'document', 'updateMapVisualStyles', 'getSelectedAlgoKey', 'setElemText', 'setElemHtml', 'getFrequencyColor', 'renderGraphExplorer',
        `
        ${extractFunction('setElemText')}
        ${extractFunction('setElemHtml')}
        ${extractFunction('openVertexInspector')}
        return openVertexInspector;
        `
    )(state, docNull, () => {}, () => "dsatur", () => {}, () => {}, () => "#3b82f6", () => {});

    assert.doesNotThrow(() => {
        fnOviNull("T1");
    });
    console.log("  [PASS] 1B. openVertexInspector gracefully returned on null container.");
}

// Scenario 2: runFrequencyOptimization with 100% null DOM elements (success path)
{
    const state = {
        currentCenter: { lat: 28.5, lon: 77.2 },
        radiusMetres: 2000,
        cells: [{ tower_id: "T1" }],
        activeAlgorithm: "dsatur",
        coverageRadiusOverride: 0,
        aggregate2m: true,
        optimizationResults: null,
        interferenceEdges: [],
        activeView: "map",
        selectedTowerId: null,
    };

    const mockFetch = async () => ({
        ok: true,
        json: async () => ({
            dsatur: { color_count: 2, runtime_ms: 1.5, validation: { is_valid: true } },
            welsh_powell: { color_count: 2, runtime_ms: 1.1, validation: { is_valid: true } },
            exact: { proven_optimal: true, color_count: 2, runtime_ms: 0.5 },
            best_algorithm: "dsatur",
            metrics: {},
            edges: []
        })
    });

    const docNull = { getElementById: () => null };

    const fnRfo = new Function(
        'state', 'document', 'fetch', 'buildGraphAdjacencyIndex', 'updateScoreboard', 'renderInterferenceEdges', 'applyActiveColoring', 'renderGraphExplorer', 'openVertexInspector', 'renderCompareModalContent',
        `
        ${extractFunction('runFrequencyOptimization')}
        return runFrequencyOptimization;
        `
    )(
        state,
        docNull,
        mockFetch,
        () => {},
        () => {},
        () => {},
        () => {},
        () => {},
        () => {},
        () => {}
    );

    (async () => {
        await fnRfo();
        console.log("  [PASS] 2. runFrequencyOptimization survived 100% null DOM elements on success path.");

        // Scenario 3: runFrequencyOptimization with 100% null DOM elements on error/rejection path
        const mockFetchFail = async () => ({
            ok: false,
            status: 500,
            json: async () => ({ detail: "Database connection failed" })
        });

        const fnRfoFail = new Function(
            'state', 'document', 'fetch', 'buildGraphAdjacencyIndex', 'updateScoreboard', 'renderInterferenceEdges', 'applyActiveColoring', 'renderGraphExplorer', 'openVertexInspector', 'renderCompareModalContent',
            `
            ${extractFunction('runFrequencyOptimization')}
            return runFrequencyOptimization;
            `
        )(
            state,
            docNull,
            mockFetchFail,
            () => {},
            () => {},
            () => {},
            () => {},
            () => {},
            () => {},
            () => {}
        );

        await fnRfoFail();
        console.log("  [PASS] 3. runFrequencyOptimization survived 100% null DOM elements on error/exception path.");
        console.log("ALL Headless DOM Null Safety Stress Tests PASSED successfully!");
    })();
}
