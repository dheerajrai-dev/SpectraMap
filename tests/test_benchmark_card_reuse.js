const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');

// Extract getFrequencyColor, computeChannelReuse, and renderReuseChips
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

const BASE_FREQUENCY_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"
];

// Context sandbox
const ctx = {
    BASE_FREQUENCY_COLORS,
    getFrequencyColor: (k) => BASE_FREQUENCY_COLORS[k % BASE_FREQUENCY_COLORS.length],
};

const fnReuse = new Function('solverResult', 'totalCells', 'getFrequencyColor', `
    ${extractFunction('computeChannelReuse')}
    return computeChannelReuse(solverResult, totalCells);
`);

const fnRenderChips = new Function('distribution', `
    ${extractFunction('renderReuseChips')}
    return renderReuseChips(distribution);
`);

console.log("=== EMPIRICAL CHALLENGE 3: Channel Reuse & Benchmark Card ===");

// 1. Tied Allocation
{
    const solverResult = {
        color_count: 4,
        coloring: {
            "t1": 0, "t2": 0, "t3": 0, "t4": 0,
            "t5": 1, "t6": 1, "t7": 1, "t8": 1,
            "t9": 2, "t10": 2, "t11": 2, "t12": 2,
            "t13": 3, "t14": 3, "t15": 3, "t16": 3,
        }
    };
    const res = fnReuse(solverResult, 16, ctx.getFrequencyColor);
    assert.strictEqual(res.ratioStr, "4.0x");
    assert.strictEqual(res.cellsPerChannelStr, "4.00 cells/ch");
    assert.strictEqual(res.distribution.length, 4);
    assert.deepStrictEqual(res.distribution.map(d => d.count), [4, 4, 4, 4]);
    assert.deepStrictEqual(res.distribution.map(d => d.channel), [1, 2, 3, 4]);

    const html = fnRenderChips(res.distribution);
    assert(html.includes("f1:<strong>4</strong>"));
    assert(html.includes("f4:<strong>4</strong>"));
    assert(!html.includes("reuse-chip-more"));
    console.log("  [PASS] 1. Tied allocation verified.");
}

// 2. Asymmetric Allocation
{
    const solverResult = {
        color_count: 3,
        coloring: {
            "t1": 0, "t2": 0, "t3": 0, "t4": 0, "t5": 0, "t6": 0, "t7": 0, "t8": 0, "t9": 0, "t10": 0,
            "t11": 1, "t12": 1,
            "t13": 2,
        }
    };
    const res = fnReuse(solverResult, 13, ctx.getFrequencyColor);
    assert.strictEqual(res.ratioStr, "4.3x"); // 13 / 3 = 4.3333 -> 4.3x
    assert.strictEqual(res.cellsPerChannelStr, "4.33 cells/ch");
    assert.strictEqual(res.distribution.length, 3);
    assert.deepStrictEqual(res.distribution.map(d => d.count), [10, 2, 1]);
    console.log("  [PASS] 2. Asymmetric allocation verified.");
}

// 3. Single-Color Allocation
{
    const coloring = {};
    for (let i = 0; i < 50; i++) coloring[`t${i}`] = 0;
    const solverResult = {
        color_count: 1,
        coloring
    };
    const res = fnReuse(solverResult, 50, ctx.getFrequencyColor);
    assert.strictEqual(res.ratioStr, "50.0x");
    assert.strictEqual(res.cellsPerChannelStr, "50.00 cells/ch");
    assert.strictEqual(res.distribution.length, 1);
    assert.strictEqual(res.distribution[0].channel, 1);
    assert.strictEqual(res.distribution[0].count, 50);

    const html = fnRenderChips(res.distribution);
    assert(html.includes("f1:<strong>50</strong>"));
    console.log("  [PASS] 3. Single-color allocation verified.");
}

// 4. Large Chromatic Number (> 5 channels) - verifies '+N more' chip truncation
{
    const coloring = {};
    for (let c = 0; c < 9; c++) {
        coloring[`t${c}_1`] = c;
        coloring[`t${c}_2`] = c;
    }
    const solverResult = {
        color_count: 9,
        coloring
    };
    const res = fnReuse(solverResult, 18, ctx.getFrequencyColor);
    assert.strictEqual(res.ratioStr, "2.0x");
    assert.strictEqual(res.distribution.length, 9);

    const html = fnRenderChips(res.distribution);
    assert(html.includes("+4 more")); // 9 - 5 = 4
    console.log("  [PASS] 4. Large chromatic allocation (> 5 channels) chip truncation verified.");
}

// 5. Boundary & Empty Edge Cases
{
    // null solverResult
    const resNull = fnReuse(null, 50, ctx.getFrequencyColor);
    assert.strictEqual(resNull.ratioStr, "—");
    assert.strictEqual(resNull.distribution.length, 0);

    // zero cells
    const resZeroCells = fnReuse({ color_count: 3, coloring: {} }, 0, ctx.getFrequencyColor);
    assert.strictEqual(resZeroCells.ratioStr, "—");
    assert.strictEqual(resZeroCells.distribution.length, 0);

    // zero color_count
    const resZeroColors = fnReuse({ color_count: 0, coloring: {} }, 50, ctx.getFrequencyColor);
    assert.strictEqual(resZeroColors.ratioStr, "—");

    // assignments alias fallback
    const resAssignments = fnReuse({ color_count: 2, assignments: { "t1": 0, "t2": 1 } }, 2, ctx.getFrequencyColor);
    assert.strictEqual(resAssignments.ratioStr, "1.0x");
    assert.strictEqual(resAssignments.distribution.length, 2);

    // empty chips render
    const emptyHtml = fnRenderChips([]);
    assert.strictEqual(emptyHtml, '<span class="reuse-chip-empty">—</span>');

    console.log("  [PASS] 5. Boundary conditions & empty edge cases verified.");
}

console.log("ALL Channel Reuse & Benchmark Card stress tests PASSED successfully!");
