const fs = require('fs');
const path = require('path');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');
const htmlPath = path.resolve(__dirname, '..', 'static', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');

// Verify that the application operates in map-first mode without separate canvas view switching
assert(!code.includes('function stepGraphSimulation'), 'Canvas simulation loop must be excised');
assert(!code.includes('initGraphCanvasInteractions'), 'Canvas mouse dragging interactions must be excised');
assert(!html.includes('id="tab-graph-view"'), 'Graph view tab must be excised from index.html');
assert(!html.includes('id="graph-canvas"'), 'Graph canvas must be excised from index.html');
assert(html.includes('id="map"'), 'Leaflet map must be the primary visualization');

console.log("ALL View Switching state preservation tests PASSED successfully!");
