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

console.log("=== EMPIRICAL CHALLENGE 5: Parameter Passing in runComparisonDirectly ===");

// Test 1: state.aggregate2m = true
{
    let interceptedUrl = null;
    let interceptedMethod = null;
    let interceptedPayload = null;

    const mockFetch = async (url, options) => {
        interceptedUrl = url;
        interceptedMethod = options.method;
        interceptedPayload = JSON.parse(options.body);
        return {
            ok: true,
            json: async () => ({
                metrics: {},
                dsatur: { color_count: 3, runtime_ms: 1.2, validation: { is_valid: true } },
                welsh_powell: { color_count: 3, runtime_ms: 0.9, validation: { is_valid: true } },
                comparison: { fewer_colors_heuristic: "tie", summary: "Tied" },
                edges: [],
            })
        };
    };

    const state = {
        currentCenter: { lat: 28.6139, lon: 77.2090 },
        radiusMetres: 2000,
        cells: [{ tower_id: "T1" }, { tower_id: "T2" }],
        coverageRadiusOverride: 0,
        aggregate2m: true,
        optimizationResults: null,
        interferenceEdges: [],
    };

    const fn = new Function(
        'state', 'fetch', 'document', 'updateScoreboard', 'applyActiveColoring', 'renderCompareModalContent', 'renderInterferenceEdges',
        `
        ${extractFunction('runComparisonDirectly')}
        return runComparisonDirectly;
        `
    )(
        state,
        mockFetch,
        { getElementById: () => ({ classList: { add: () => {} }, setAttribute: () => {} }) },
        () => {},
        () => {},
        () => {},
        () => {}
    );

    (async () => {
        await fn();
        assert.strictEqual(interceptedUrl, "/api/compare");
        assert.strictEqual(interceptedMethod, "POST");
        assert.strictEqual(interceptedPayload.aggregate_2m, true);
        assert.deepStrictEqual(interceptedPayload.center, { latitude: 28.6139, longitude: 77.2090 });
        assert.strictEqual(interceptedPayload.radius_m, 2000);
        console.log("  [PASS] 1. runComparisonDirectly correctly passes aggregate_2m: true in payload.");

        // Test 2: state.aggregate2m = false
        state.aggregate2m = false;
        await fn();
        assert.strictEqual(interceptedPayload.aggregate_2m, false);
        console.log("  [PASS] 2. runComparisonDirectly correctly passes aggregate_2m: false in payload.");
    })();
}
