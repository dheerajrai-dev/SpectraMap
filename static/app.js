/**
 * app.js — SpectraMap Frontend Core
 * Map-first cellular frequency allocation workspace.
 */

const state = {
    currentCenter: { lat: 28.5200, lon: 77.1900 },
    radiusMetres: 2000, coverageRadiusOverride: 0, maxTowersLimit: 50,
    selectedRadios: new Set(["4G", "5G"]), selectedTowerId: null, activeAlgorithm: "both",
    cells: [], allFetchedCells: [], interferenceEdges: [], graphMetrics: null,
    adjacencyIndex: {}, degreeMap: {}, optimizationResults: null, currentAssignments: null,
    activeIsolatedFreq: null, pipelineState: "Connecting", aggregate2m: true,
    coverageOpacity: 0.18,
    map: null, centerMarker: null, centerCircle: null, markersLayer: null, circlesLayer: null,
    markersById: {}, coverageCirclesById: {},
};

/**
 * Safe DOM element setters to guarantee zero unhandled null property exceptions.
 */
function setElemText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function setElemHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

function on(id, evt, fn) { const el = document.getElementById(id); if (el) el.addEventListener(evt, fn); }

const BASE_FREQUENCY_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4",
    "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#a855f7", "#eab308",
    "#6366f1", "#d946ef", "#22c55e", "#64748b",
];

function getFrequencyColor(freqIndex) {
    if (freqIndex >= 0 && freqIndex < BASE_FREQUENCY_COLORS.length) return BASE_FREQUENCY_COLORS[freqIndex];
    const goldenRatioConjugate = 0.618033988749895;
    const hue = Math.round(((freqIndex * goldenRatioConjugate) % 1) * 360);
    return `hsl(${hue}, 70%, 55%)`;
}

function getAlphaLabel(index) {
    let label = "", num = index;
    while (num >= 0) {
        label = String.fromCharCode(65 + (num % 26)) + label;
        num = Math.floor(num / 26) - 1;
    }
    return label;
}

function initMap() {
    const mapEl = document.getElementById("map");
    if (!mapEl || state.map) return;
    state.map = L.map("map", { zoomControl: false }).setView([state.currentCenter.lat, state.currentCenter.lon], 14);
    L.control.zoom({ position: "bottomright" }).addTo(state.map);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors", maxZoom: 19, className: "dark-tiles",
    }).addTo(state.map);
    state.circlesLayer = L.layerGroup().addTo(state.map);
    state.markersLayer = L.layerGroup().addTo(state.map);
    const map = state.map;
    map.on("click", (e) => { setNewCenter(e.latlng.lat, e.latlng.lng, null, "Map Click"); invalidateOptimizationState("Map clicked"); fetchNearbyCells(); });
    updateCenterVisuals();
}

function updateCenterVisuals() {
    if (!state.map) return;
    const latlng = [state.currentCenter.lat, state.currentCenter.lon];
    if (!state.centerMarker) {
        const centerIcon = L.divIcon({ html: '<div style="width:14px;height:14px;background:#3b82f6;border:2.5px solid #ffffff;border-radius:50%;box-shadow:0 0 10px rgba(59,130,246,0.9);cursor:move;"></div>', className: "center-pin-icon", iconSize: [14, 14], iconAnchor: [7, 7] });
        const centerMarker = L.marker(latlng, { icon: centerIcon, draggable: true }).addTo(state.map);
        centerMarker.on("dragend", (e) => { const p = e.target.getLatLng(); setNewCenter(p.lat, p.lng, null, "Custom Pin"); invalidateOptimizationState("Marker dragged"); fetchNearbyCells(); });
        state.centerMarker = centerMarker;
    } else {
        state.centerMarker.setLatLng(latlng);
    }
    if (!state.centerCircle) {
        state.centerCircle = L.circle(latlng, { radius: state.radiusMetres, color: "#3b82f6", fillColor: "#3b82f6", fillOpacity: 0.04, weight: 1.5, dashArray: "4, 6", interactive: false }).addTo(state.map);
    } else {
        state.centerCircle.setLatLng(latlng);
        state.centerCircle.setRadius(state.radiusMetres);
    }
    setElemText("center-lat-display", state.currentCenter.lat.toFixed(5));
    setElemText("center-lon-display", state.currentCenter.lon.toFixed(5));
}

const PRESET_LOCATIONS = {
    south_delhi: { lat: 28.5224, lon: 77.1906, zoom: 14, name: "South Delhi" },
    connaught_place: { lat: 28.6304, lon: 77.2177, zoom: 14, name: "Connaught Place" },
    mumbai: { lat: 18.9430, lon: 72.8250, zoom: 14, name: "Mumbai" },
};

function clearLoadedCells() {
    state.cells = []; state.allFetchedCells = []; state.interferenceEdges = []; state.adjacencyIndex = {}; state.degreeMap = {}; state.selectedTowerId = null;
    state.markersById = {}; state.coverageCirclesById = {};
    if (state.markersLayer) state.markersLayer.clearLayers();
    if (state.circlesLayer) state.circlesLayer.clearLayers();
    updateAccountingDisplay({ available_count: 0, eligible_count: 0, selected_count: 0, excluded_count: 0 });
    renderAssignmentTable(null, []); closeVertexInspector();
}

function setNewCenter(lat, lon, zoom = null, locationName = "") {
    state.currentCenter = { lat, lon };
    const latInp = document.getElementById("input-lat"), lonInp = document.getElementById("input-lon");
    if (latInp) latInp.value = lat.toFixed(5);
    if (lonInp) lonInp.value = lon.toFixed(5);
    const overlay = document.getElementById("map-overlay");
    if (overlay) overlay.textContent = `Center: ${lat.toFixed(5)}°, ${lon.toFixed(5)}° (${locationName || "Custom Pin"})`;
    if (state.map) { if (zoom) state.map.setView([lat, lon], zoom); else state.map.panTo([lat, lon]); }
    updateCenterVisuals(); clearLoadedCells(); invalidateOptimizationState("Location changed");
}

function initControls() {
    const presetSelect = document.getElementById("preset-select");
    if (presetSelect) presetSelect.addEventListener("change", (e) => { invalidateOptimizationState("Preset location changed"); const p = PRESET_LOCATIONS[e.target.value]; if (p) { setNewCenter(p.lat, p.lon, p.zoom, p.name); fetchNearbyCells(); } });

    const inputLat = document.getElementById("input-lat");
    if (inputLat) inputLat.addEventListener("change", (e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { invalidateOptimizationState("Coordinate changed"); setNewCenter(v, state.currentCenter.lon, null, "Custom"); } });

    const inputLon = document.getElementById("input-lon");
    if (inputLon) inputLon.addEventListener("change", (e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { invalidateOptimizationState("Coordinate changed"); setNewCenter(state.currentCenter.lat, v, null, "Custom"); } });

    const radiusSlider = document.getElementById("radius-slider");
    if (radiusSlider) { const h = (e) => { state.radiusMetres = parseInt(e.target.value, 10); setElemText("radius-label", `${state.radiusMetres.toLocaleString()}`); updateCenterVisuals(); invalidateOptimizationState("Radius changed"); }; radiusSlider.addEventListener("input", h); radiusSlider.addEventListener("change", h); }

    function handleTechChange(radio, checked) { if (checked) state.selectedRadios.add(radio); else state.selectedRadios.delete(radio); invalidateOptimizationState("Radio filter modified"); applyClientSideRadioFilter(); }
    on("check-tech-4g", "change", (e) => handleTechChange("4G", e.target.checked));
    on("check-tech-5g", "change", (e) => handleTechChange("5G", e.target.checked));

    const limitSlider = document.getElementById("limit-slider");
    if (limitSlider) limitSlider.addEventListener("input", (e) => { state.maxTowersLimit = parseInt(e.target.value, 10); setElemText("limit-label", `${state.maxTowersLimit}`); invalidateOptimizationState("Limit modified"); applyClientSideLimitSlicing(); });

    const overrideSlider = document.getElementById("override-slider");
    if (overrideSlider) { const h = (e) => { state.coverageRadiusOverride = parseInt(e.target.value, 10); setElemText("override-label", state.coverageRadiusOverride === 0 ? "Data Default" : `${state.coverageRadiusOverride} m`); invalidateOptimizationState("Coverage override changed"); }; overrideSlider.addEventListener("input", h); overrideSlider.addEventListener("change", h); }

    const chkAgg2m = document.getElementById("check-aggregate-2m");
    if (chkAgg2m) chkAgg2m.addEventListener("change", (e) => { state.aggregate2m = Boolean(e.target.checked); invalidateOptimizationState("2m mast aggregation toggled"); });

    on("opacity-slider", "input", (e) => {
        const val = parseInt(e.target.value, 10);
        state.coverageOpacity = val / 100.0;
        setElemText("opacity-label", `${val}%`);
        if (state.coverageCirclesById) {
            const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
            const coloring = state.optimizationResults?.[algoKey]?.coloring || {};
            Object.entries(state.coverageCirclesById).forEach(([tid, circle]) => {
                circle.setStyle({ fillOpacity: coloring[tid] !== undefined ? state.coverageOpacity : 0.0 });
            });
        }
    });

    on("btn-fetch", "click", () => fetchNearbyCells());
    on("btn-build-graph", "click", () => buildInterferenceGraphUI(true));
    on("btn-optimize", "click", () => runFrequencyOptimization());
    on("btn-compare-action", "click", () => runComparisonDirectly());
    on("algo-select", "change", (e) => { state.activeAlgorithm = e.target.value; if (state.optimizationResults) applyActiveColoring(); });

    on("btn-locate", "click", handleGeolocation);
    on("btn-demo", "click", loadDemoTowers);
    on("btn-close-inspector", "click", closeVertexInspector);

    on("btn-guide", "click", () => { const m = document.getElementById("guide-modal"); if (m) { m.classList.add("open"); m.setAttribute("aria-hidden", "false"); } });
    on("btn-close-guide", "click", () => { const m = document.getElementById("guide-modal"); if (m) { m.classList.remove("open"); m.setAttribute("aria-hidden", "true"); } });
    on("btn-close-compare", "click", () => { const m = document.getElementById("compare-modal"); if (m) { m.classList.remove("open"); m.setAttribute("aria-hidden", "true"); } });
    on("btn-clear-isolate", "click", clearFrequencyIsolation);

    initAssignmentTableEvents();
}

function setPipelineButtonsDisabled(fetchDis, buildDis, optDis, compareDis) {
    const f = document.getElementById("btn-fetch"), b = document.getElementById("btn-build-graph"), o = document.getElementById("btn-optimize"), c = document.getElementById("btn-compare-action");
    if (f) f.disabled = Boolean(fetchDis);
    if (b) b.disabled = Boolean(buildDis);
    if (o) o.disabled = Boolean(optDis);
    if (c) c.disabled = Boolean(compareDis);
}

function setPipelineState(stateName, details = "") {
    state.pipelineState = stateName;
    const badge = document.getElementById("status-badge"), msg = document.getElementById("cells-status");
    const setHtml = (id, h) => { const el = document.getElementById(id); if (el) el.innerHTML = h; };
    switch (stateName) {
        case "Connecting":
            setPipelineButtonsDisabled(true, true, true, true);
            if (badge) { badge.textContent = "Connecting..."; badge.className = "badge badge-loading"; }
            if (msg) { msg.textContent = details || "Connecting to SpectraMap backend..."; msg.style.color = "var(--text-secondary)"; } break;
        case "Fetching":
            setPipelineButtonsDisabled(true, true, true, true);
            setHtml("btn-fetch", '<span class="spinner">⏳</span> Fetching...');
            if (msg) { msg.textContent = details || "Querying 4G/5G cell records..."; msg.style.color = "var(--text-secondary)"; } break;
        case "Building Graph":
            setPipelineButtonsDisabled(true, true, true, true);
            setHtml("btn-build-graph", '<span class="spinner">⏳</span> Building...');
            if (msg) { msg.textContent = details || "Constructing interference graph..."; msg.style.color = "var(--text-secondary)"; } break;
        case "Optimizing":
            setPipelineButtonsDisabled(true, true, true, true);
            setHtml("btn-optimize", '<span class="spinner">⏳</span> Optimizing...');
            if (msg) { msg.textContent = details || "Running graph coloring heuristics..."; msg.style.color = "var(--text-secondary)"; } break;
        case "Validating":
            setPipelineButtonsDisabled(true, true, true, true);
            setHtml("btn-optimize", '<span class="spinner">⏳</span> Validating...');
            if (msg) { msg.textContent = details || "Validating independent set assignments..."; msg.style.color = "var(--text-secondary)"; } break;
        case "Completed":
            setPipelineButtonsDisabled(false, false, false, false);
            setHtml("btn-fetch", '<span class="btn-icon">📡</span> Fetch Records'); setHtml("btn-build-graph", '<span class="btn-icon">🕸️</span> Build Graph'); setHtml("btn-optimize", '<span class="btn-icon">⚡</span> Optimize Frequencies');
            if (msg) { msg.textContent = details || "Completed."; msg.style.color = "var(--accent-emerald)"; } break;
        case "Failed":
        default:
            const hasCells = Boolean(state.cells && state.cells.length);
            setPipelineButtonsDisabled(false, !hasCells, !hasCells, !hasCells);
            setHtml("btn-fetch", '<span class="btn-icon">📡</span> Fetch Records'); setHtml("btn-build-graph", '<span class="btn-icon">🕸️</span> Build Graph'); setHtml("btn-optimize", '<span class="btn-icon">⚡</span> Optimize Frequencies');
            if (msg) { msg.textContent = details || "Operation failed."; msg.style.color = "var(--accent-rose)"; } break;
    }
}

function invalidateOptimizationState(reason = "") {
    state.optimizationResults = null; state.currentAssignments = null; state.activeIsolatedFreq = null; state.isolatedFrequency = null;
    const legendContainer = document.getElementById("legend-container");
    if (legendContainer) legendContainer.style.display = "none";
    const valBadge = document.getElementById("metric-validation-badge");
    if (valBadge) { valBadge.className = "badge-validation badge-val-waiting"; valBadge.textContent = state.cells.length > 0 ? "Awaiting Run" : "Awaiting Data"; }
    ["pill-dsatur", "pill-wp", "pill-exact"].forEach((id) => document.getElementById(id)?.classList.remove("best-algo-pill"));

    if (state.coverageCirclesById) {
        Object.values(state.coverageCirclesById).forEach((circle) => {
            circle.setStyle({ fill: false, fillColor: "#3b82f6", fillOpacity: 0.0, color: "#64748b", weight: 1.5, opacity: 0.35 });
        });
    }
    if (state.cells && Array.isArray(state.cells)) {
        state.cells.forEach((cell) => {
            const markerEl = document.getElementById(`marker-circle-${cell.tower_id}`);
            if (markerEl) {
                markerEl.style.backgroundColor = "var(--bg-surface)"; markerEl.style.borderColor = "#ffffff";
                markerEl.innerHTML = `<span class="marker-label">${cell.label}</span>`; markerEl.title = `Cell ${cell.label} (#${cell.cell_id})`;
            }
        });
    }
    renderAssignmentTable(null, state.cells);
    const panel = document.getElementById("assignment-panel");
    if (panel) panel.style.display = "none";
    updateDashboardMetrics(null, null, null, state.cells);
    renderEmbeddedComparisonCard();
    if (state.selectedTowerId && typeof openVertexInspector === "function") openVertexInspector(state.selectedTowerId);
    if (reason) {
        const statusMsg = document.getElementById("cells-status");
        if (statusMsg) { statusMsg.textContent = `${reason}. Optimization reset. Click 'Optimize Frequencies' to solve.`; statusMsg.style.color = "var(--text-secondary)"; }
    }
}

function renderAssignmentTable(assignments, cells) {
    const tbody = document.getElementById("assignment-table-body"), countBadge = document.getElementById("assignment-count-badge"), panel = document.getElementById("assignment-panel");
    if (!tbody) return;

    if (!cells || cells.length === 0) {
        tbody.innerHTML = '<tr class="assignment-empty-row"><td colspan="6">No cell records loaded in area.</td></tr>';
        if (countBadge) countBadge.textContent = "0";
        if (panel) panel.style.display = "none";
        return;
    }

    if (panel) panel.style.display = "flex";
    if (countBadge) countBadge.textContent = String(cells.length);

    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const coloring = assignments || state.optimizationResults?.[algoKey]?.coloring || null;
    if (coloring) state.currentAssignments = coloring;

    const rows = cells.map((cell) => {
        const tid = cell.tower_id, colorIdx = coloring && coloring[tid] !== undefined ? Number(coloring[tid]) : null;
        const freqColor = colorIdx !== null ? getFrequencyColor(colorIdx) : "#64748b", freqText = colorIdx !== null ? `f${colorIdx + 1}` : "—";
        const degree = state.degreeMap?.[tid] ?? "0", isSelected = state.selectedTowerId === tid ? " selected-row" : "";
        const radiusM = Math.round(Number(cell.range_m) || 800), shortTid = tid.length > 18 ? `${tid.slice(0, 10)}…${tid.slice(-4)}` : tid;
        return `<tr class="assignment-row${isSelected}" data-tower-id="${tid}" onclick="selectCellFromTable('${tid}')">` +
            `<td><span class="cell-label-pill" style="border-color:${freqColor}; color:${freqColor};">${cell.label}</span></td>` +
            `<td class="font-mono text-xs" title="${tid}">${shortTid}</td>` +
            `<td><span class="badge-tech-${cell.radio.toLowerCase()}">${cell.radio}</span></td>` +
            `<td><span class="badge-channel" style="border-color:${freqColor}; color:${freqColor};"><span class="channel-dot" style="background:${freqColor};"></span>${freqText}</span></td>` +
            `<td class="font-mono text-xs">${radiusM} m</td>` +
            `<td class="font-mono text-xs">${degree}</td></tr>`;
    });

    tbody.innerHTML = rows.join("");
    applyAssignmentTableFilters();
}

function selectCellFromTable(towerId) {
    const cell = (state.cells || []).find((c) => c.tower_id === towerId);
    if (!cell) return;
    if (state.map) state.map.panTo([cell.latitude, cell.longitude]);
    if (typeof openVertexInspector === "function") openVertexInspector(towerId);
    const marker = state.markersById?.[towerId];
    if (marker) marker.openPopup();
}

function updateAssignmentTableRowSelection(towerId) {
    if (typeof document.querySelectorAll !== "function") return;
    document.querySelectorAll(".assignment-row").forEach((row) => {
        if (towerId && row.dataset.towerId === towerId) {
            row.classList.add("selected-row");
            if (typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } else {
            row.classList.remove("selected-row");
        }
    });
}

function applyAssignmentTableFilters(e) {
    const el1 = document.getElementById("assignment-search-input"), el2 = document.getElementById("assignment-search");
    const rawVal = (e?.target?.value) || (el2 && el2.value) || (el1 && el1.value) || "";
    const term = rawVal.trim().toLowerCase();
    state.assignmentSearchQuery = term;
    const b1 = document.getElementById("btn-clear-assignment-search"), b2 = document.getElementById("btn-assignment-search-clear");
    const displayStyle = term ? "inline-block" : "none";
    if (b1) b1.style.display = displayStyle;
    if (b2) b2.style.display = displayStyle;
    const tbody = document.getElementById("assignment-table-body");
    let rows = (tbody && tbody.querySelectorAll) ? Array.from(tbody.querySelectorAll(".assignment-row")) : [];
    if (rows.length === 0 && typeof document.querySelectorAll === "function") {
        rows = Array.from(document.querySelectorAll(".assignment-row"));
    }
    let visibleCount = 0;
    rows.forEach((row) => {
        const text = (row.textContent || "").toLowerCase();
        const ds = row.dataset || {};
        const dataStr = Object.values(ds).join(" ").toLowerCase() + (ds.channel ? ` f${ds.channel}` : "");
        const full = text + " " + dataStr;
        const match = term === "" || full.includes(term);
        row.style.display = match ? "" : "none";
        if (match) visibleCount++;
    });
    const countBadge = document.getElementById("assignment-count-badge");
    if (countBadge && rows.length > 0) {
        countBadge.textContent = term ? `${visibleCount} / ${rows.length} cells` : (countBadge.textContent.includes("cells") ? `${rows.length} cells` : String(rows.length));
    }
}

function initAssignmentTableEvents() {
    const el1 = document.getElementById("assignment-search-input"), el2 = document.getElementById("assignment-search");
    if (el1) el1.addEventListener("input", applyAssignmentTableFilters);
    if (el2) el2.addEventListener("input", applyAssignmentTableFilters);
    const onClear = () => {
        if (el1) el1.value = "";
        if (el2) el2.value = "";
        state.assignmentSearchQuery = "";
        const b1 = document.getElementById("btn-clear-assignment-search"), b2 = document.getElementById("btn-assignment-search-clear");
        if (b1) b1.style.display = "none";
        if (b2) b2.style.display = "none";
        const tbody = document.getElementById("assignment-table-body");
        let rows = (tbody && tbody.querySelectorAll) ? Array.from(tbody.querySelectorAll(".assignment-row")) : [];
        if (rows.length === 0 && typeof document.querySelectorAll === "function") rows = Array.from(document.querySelectorAll(".assignment-row"));
        rows.forEach((r) => { r.style.display = ""; });
        const countBadge = document.getElementById("assignment-count-badge");
        if (countBadge) countBadge.textContent = `${rows.length} cells`;
        if (el2 && typeof el2.focus === "function") el2.focus();
        else if (el1 && typeof el1.focus === "function") el1.focus();
    };
    const b1 = document.getElementById("btn-clear-assignment-search"), b2 = document.getElementById("btn-assignment-search-clear");
    if (b1) b1.addEventListener("click", onClear);
    if (b2) b2.addEventListener("click", onClear);
}

function buildGraphAdjacencyIndex(edges) {
    state.adjacencyIndex = {};
    state.degreeMap = {};
    (state.cells || []).forEach((c) => { state.adjacencyIndex[c.tower_id] = []; state.degreeMap[c.tower_id] = 0; });
    (edges || []).forEach((e) => {
        const u = e.source_id || e.source, v = e.target_id || e.target;
        if (!state.adjacencyIndex[u]) state.adjacencyIndex[u] = [];
        if (!state.adjacencyIndex[v]) state.adjacencyIndex[v] = [];
        if (!state.adjacencyIndex[u].includes(v)) state.adjacencyIndex[u].push(v);
        if (!state.adjacencyIndex[v].includes(u)) state.adjacencyIndex[v].push(u);
    });
    Object.keys(state.adjacencyIndex).forEach((tid) => { state.degreeMap[tid] = state.adjacencyIndex[tid].length; });
}

function updateMapVisualStyles() {
    const selectedId = state.selectedTowerId;
    const neighbors = selectedId && state.adjacencyIndex?.[selectedId] ? state.adjacencyIndex[selectedId] : [];
    if (state.cells) {
        state.cells.forEach((cell) => {
            const tid = cell.tower_id, circleEl = document.getElementById(`marker-circle-${tid}`);
            if (!circleEl) return;
            circleEl.classList.remove("selected-marker", "neighbor-marker", "dimmed-marker");
            if (tid === selectedId) circleEl.classList.add("selected-marker");
            else if (neighbors.includes(tid)) circleEl.classList.add("neighbor-marker");
            else if (selectedId) circleEl.classList.add("dimmed-marker");
        });
    }
}

function applyClientSideFilter(reason = "Filter modified") {
    const all = state.allFetchedCells || [];
    if (all.length === 0) return;
    state.cells = all.filter((c) => state.selectedRadios.has(c.radio)).slice(0, state.maxTowersLimit);
    state.cells.forEach((c, idx) => { c.label = getAlphaLabel(idx); });
    renderCellTowers(state.cells);
    invalidateOptimizationState(reason);
    buildInterferenceGraphUI(false);
}
const applyClientSideRadioFilter = () => applyClientSideFilter("Filter modified");
const applyClientSideLimitSlicing = () => applyClientSideFilter("Limit modified");

function updateAccountingDisplay(meta) {
    setElemText("acc-avail", String(meta.available_count ?? state.cells.length)); setElemText("acc-elig", String(meta.eligible_count ?? state.cells.length));
    setElemText("acc-sel", String(meta.selected_count ?? state.cells.length)); setElemText("acc-excl", String(meta.excluded_count ?? 0));
}

function updateRangeStatsDisplay(ranges) {
    if (!ranges) return;
    setElemText("stat-4g-range", `${ranges.r4g_min ? Math.round(ranges.r4g_min) : 800}m / ${ranges.r4g_median ? Math.round(ranges.r4g_median) : 800}m / ${ranges.r4g_max ? Math.round(ranges.r4g_max) : 800}m`);
    setElemText("stat-5g-range", `${ranges.r5g_min ? Math.round(ranges.r5g_min) : 500}m / ${ranges.r5g_median ? Math.round(ranges.r5g_median) : 500}m / ${ranges.r5g_max ? Math.round(ranges.r5g_max) : 500}m`);
}

function updateDashboardMetrics(metrics, solverResult = null, algoKey = null, cellsList = null) {
    const cells = cellsList || state.cells || [], m = metrics || state.graphMetrics || {};
    let count4G = 0, count5G = 0;
    cells.forEach((c) => { if (c.radio === "5G") count5G++; else count4G++; });
    setElemText("metric-towers", String(m.vertex_count ?? (cells.length || "—")));
    setElemText("metric-edges", String(m.edge_count ?? (state.interferenceEdges?.length || "0")));
    setElemText("metric-degree", String(m.max_degree ?? "0"));
    setElemText("metric-density", m.density !== undefined ? `${(m.density * 100).toFixed(1)}%` : "0.0%");
    setElemText("badge-ratio-4g", `4G: ${count4G}`); setElemText("badge-ratio-5g", `5G: ${count5G}`);
    setElemText("metric-colors", solverResult?.color_count !== undefined ? `${solverResult.color_count} ch` : "—");
    setElemText("metric-runtime", solverResult?.runtime_ms !== undefined ? `${solverResult.runtime_ms.toFixed(2)} ms` : "—");

    const valBadge = document.getElementById("metric-validation-badge");
    if (valBadge) {
        if (!solverResult) {
            valBadge.className = "badge-validation badge-val-waiting"; valBadge.textContent = cells.length > 0 ? "Awaiting Run" : "Awaiting Data";
        } else {
            const isValid = solverResult.validation?.is_valid ?? solverResult.is_valid;
            valBadge.className = isValid ? "badge-validation badge-val-valid" : "badge-validation badge-val-invalid";
            valBadge.textContent = isValid ? "✔ 0 Conflicts" : "✖ Collision";
        }
    }
}

function updateScoreboard(optimizationResults) {
    if (!optimizationResults) return;
    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const result = optimizationResults[algoKey];
    updateDashboardMetrics(optimizationResults.metrics, result, algoKey, state.cells);
    renderEmbeddedComparisonCard();
}

function computeChannelReuse(solverResult, totalCells) {
    if (!solverResult || !solverResult.color_count || solverResult.color_count <= 0 || !totalCells) {
        return { ratioStr: "—", cellsPerChannelStr: "—", distribution: [] };
    }
    const colorCount = solverResult.color_count, ratio = (totalCells / colorCount).toFixed(1), cellsPerCh = (totalCells / colorCount).toFixed(2);
    const coloring = solverResult.coloring || solverResult.assignments || {}, counts = {};
    Object.values(coloring).forEach((ch) => { const ch1 = Number(ch) + 1; counts[ch1] = (counts[ch1] || 0) + 1; });
    const distribution = [];
    for (let c = 1; c <= colorCount; c++) {
        distribution.push({ channel: c, count: counts[c] || 0, color: getFrequencyColor(c - 1) });
    }
    return { ratioStr: `${ratio}x`, cellsPerChannelStr: `${cellsPerCh} cells/ch`, distribution };
}

function renderReuseChips(distribution) {
    if (!distribution || distribution.length === 0) return '<span class="reuse-chip-empty">—</span>';
    const maxChips = 5;
    const chips = distribution.slice(0, maxChips).map((d) => `<span class="reuse-chip" style="border-color:${d.color}; color:${d.color}" title="Channel f${d.channel}: ${d.count} cells">f${d.channel}:<strong>${d.count}</strong></span>`);
    if (distribution.length > maxChips) chips.push(`<span class="reuse-chip-more">+${distribution.length - maxChips} more</span>`);
    return chips.join("");
}

function renderEmbeddedComparisonCard() {
    const cardContainer = document.getElementById("dashboard-compare-card");
    if (!cardContainer) return;

    const opt = state.optimizationResults;
    if (!opt || (!opt.dsatur && !opt.welsh_powell)) {
        cardContainer.innerHTML = '<div class="compare-card-empty"><span class="empty-icon">⚡</span><span class="empty-text">Click <strong>Optimize Frequencies</strong> or <strong>Compare Both</strong> to generate side-by-side DSatur vs Welsh-Powell channel benchmarks.</span></div>';
        return;
    }

    const ds = opt.dsatur || { color_count: 0, runtime_ms: 0, validation: { is_valid: false } };
    const wp = opt.welsh_powell || { color_count: 0, runtime_ms: 0, validation: { is_valid: false } };
    const totalCells = state.cells ? state.cells.length : 0;
    const reuseDs = computeChannelReuse(ds, totalCells), reuseWp = computeChannelReuse(wp, totalCells);

    let winnerKey = "tie", winnerLabel = "Tie (Equal Efficiency)", verdictDesc = "Both algorithms achieved identical frequency reuse.";
    if (ds.color_count > 0 && wp.color_count > 0) {
        if (ds.color_count < wp.color_count) {
            winnerKey = "dsatur"; winnerLabel = "DSatur Won"; verdictDesc = `DSatur saved ${wp.color_count - ds.color_count} channel(s) over Welsh-Powell.`;
        } else if (wp.color_count < ds.color_count) {
            winnerKey = "welsh_powell"; winnerLabel = "Welsh-Powell Won"; verdictDesc = `Welsh-Powell saved ${ds.color_count - wp.color_count} channel(s) over DSatur.`;
        }
    }

    const solverBox = (title, paradigm, colorCount, runtime, reuse, isValid, isWinner) =>
        `<div class="compare-solver-box ${isWinner ? 'winner-box' : ''}"><div class="solver-box-head"><span class="solver-box-title">${title}</span><span class="solver-paradigm-badge">${paradigm}</span></div>` +
        `<div class="solver-stat-row"><div class="solver-stat"><span class="solver-stat-num">${colorCount}</span><span class="solver-stat-lbl">Channels (k)</span></div><div class="solver-stat"><span class="solver-stat-num">${runtime.toFixed(2)}</span><span class="solver-stat-lbl">Time (ms)</span></div></div>` +
        `<div class="solver-stat-reuse"><div class="solver-reuse-breakdown"><div class="reuse-breakdown-header"><span class="reuse-breakdown-title">Channel Reuse</span><span class="reuse-breakdown-summary">${reuse.ratioStr}</span></div><div class="reuse-channel-chips">${renderReuseChips(reuse.distribution)}</div></div></div>` +
        `<div class="solver-box-footer"><span class="solver-valid-badge" style="color:${isValid ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">${isValid ? '✔ 0 Conflicts' : '✖ Collision'}</span></div></div>`;

    cardContainer.innerHTML = `<div class="compare-card-container">` +
        `<div class="compare-card-topbar"><div class="compare-card-title-group"><span class="compare-card-icon">⚡</span><span class="compare-card-heading">Side-by-Side Solver Comparison</span></div>` +
        `<span class="badge-verdict ${winnerKey === 'tie' ? 'badge-verdict-tie' : 'badge-verdict-win'}">${winnerLabel}</span></div>` +
        `<div class="compare-columns-grid">` +
        solverBox("DSatur", "Dynamic Saturation", ds.color_count, ds.runtime_ms, reuseDs, ds.validation?.is_valid, winnerKey === "dsatur") +
        solverBox("Welsh–Powell", "Static Degree", wp.color_count, wp.runtime_ms, reuseWp, wp.validation?.is_valid, winnerKey === "welsh_powell") +
        `<div class="compare-verdict-box"><div><div class="verdict-box-lbl">Efficiency Verdict</div><div class="verdict-box-desc">${verdictDesc}</div></div>` +
        `<button id="btn-open-compare" class="btn btn-secondary btn-modal-trigger">Full Matrix & Bounds ↗</button></div></div></div>`;

    const btnOpen = document.getElementById("btn-open-compare"), compareModal = document.getElementById("compare-modal");
    if (btnOpen && compareModal) {
        btnOpen.addEventListener("click", () => {
            if (typeof renderCompareModalContent === "function") renderCompareModalContent();
            compareModal.classList.add("open");
            compareModal.setAttribute("aria-hidden", "false");
        });
    }
}

function renderLegend(assignments) {
    const container = document.getElementById("legend-container"), chipsDiv = document.getElementById("legend-chips") || document.getElementById("legend-items");
    if (!container || !chipsDiv) return;
    if (!assignments || Object.keys(assignments).length === 0) { container.style.display = "none"; return; }

    const counts = {};
    Object.values(assignments).forEach((ch) => { const c = Number(ch); counts[c] = (counts[c] || 0) + 1; });
    const channels = Object.keys(counts).map(Number).sort((a, b) => a - b);
    if (channels.length === 0) { container.style.display = "none"; return; }

    container.style.display = "flex";
    const totalCells = Object.keys(assignments).length;
    let html = `<button class="legend-chip legend-chip-all ${state.activeIsolatedFreq === null ? 'active-isolate' : ''}" onclick="clearFrequencyIsolation()"><span class="legend-chip-name">All Channels</span><span class="legend-count-pill">(${totalCells})</span></button>`;
    channels.forEach((ch) => {
        const col = getFrequencyColor(ch), count = counts[ch], isActive = state.activeIsolatedFreq === ch ? " active-isolate" : "";
        html += `<button class="legend-chip${isActive}" onclick="isolateFrequency(${ch})" style="border-color:${col};"><span class="legend-color-dot" style="background:${col};"></span><span class="legend-chip-name" style="color:${col};">f${ch + 1}</span><span class="legend-count-pill">(${count})</span></button>`;
    });
    chipsDiv.innerHTML = html;
}

function isolateFrequency(freqIndex) {
    state.activeIsolatedFreq = freqIndex;
    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const coloring = state.optimizationResults?.[algoKey]?.coloring || {};
    (state.cells || []).forEach((cell) => {
        const marker = state.markersById?.[cell.tower_id], ch = coloring[cell.tower_id];
        if (marker?._icon) { marker._icon.style.opacity = ch === freqIndex ? "1.0" : "0.15"; marker._icon.style.filter = ch === freqIndex ? "none" : "grayscale(80%)"; }
        state.coverageCirclesById?.[cell.tower_id]?.setStyle({ opacity: ch === freqIndex ? 0.9 : 0.05, fillOpacity: ch === freqIndex ? 0.25 : 0.0 });
    });
    renderLegend(coloring);
}

function clearFrequencyIsolation() {
    state.activeIsolatedFreq = null;
    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const coloring = state.optimizationResults?.[algoKey]?.coloring || {};
    (state.cells || []).forEach((cell) => {
        const marker = state.markersById?.[cell.tower_id];
        if (marker?._icon) { marker._icon.style.opacity = "1.0"; marker._icon.style.filter = "none"; }
        const ch = coloring[cell.tower_id];
        state.coverageCirclesById?.[cell.tower_id]?.setStyle({ opacity: ch !== undefined ? 0.85 : 0.35, fillOpacity: ch !== undefined ? 0.18 : 0.0 });
    });
    renderLegend(coloring);
}

function updateLocationMode(mode, detail) {}

function handleGeolocation() {
    if (!navigator.geolocation) { alert("Geolocation is not supported by your browser."); return; }
    invalidateOptimizationState("Acquiring GPS location");
    setPipelineState("Fetching", "Acquiring GPS location...");
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            setNewCenter(pos.coords.latitude, pos.coords.longitude, 14, "GPS Location");
            const banner = document.getElementById("geo-banner");
            if (banner) banner.style.display = "none";
            fetchNearbyCells();
        },
        (err) => {
            console.warn("Geolocation error:", err);
            setPipelineState("Failed", `Geolocation error: ${err.message}. Using default location.`);
        },
        { enableHighAccuracy: true, timeout: 8000 }
    );
}

function loadDemoTowers() {
    invalidateOptimizationState("Loading demo grid");
    const lat = state.currentCenter.lat, lon = state.currentCenter.lon;
    const demo = [
        { tower_id: "DEMO_1", cell_id: 101, latitude: lat + 0.003, longitude: lon + 0.003, radio: "5G", range_m: 500, is_range_estimated: false, label: "A" },
        { tower_id: "DEMO_2", cell_id: 102, latitude: lat + 0.003, longitude: lon - 0.003, radio: "4G", range_m: 800, is_range_estimated: false, label: "B" },
        { tower_id: "DEMO_3", cell_id: 103, latitude: lat - 0.003, longitude: lon + 0.003, radio: "4G", range_m: 750, is_range_estimated: false, label: "C" },
        { tower_id: "DEMO_4", cell_id: 104, latitude: lat - 0.003, longitude: lon - 0.003, radio: "5G", range_m: 600, is_range_estimated: false, label: "D" },
        { tower_id: "DEMO_5", cell_id: 105, latitude: lat, longitude: lon, radio: "5G", range_m: 700, is_range_estimated: false, label: "E" },
        { tower_id: "DEMO_6", cell_id: 106, latitude: lat, longitude: lon + 0.006, radio: "4G", range_m: 800, is_range_estimated: false, label: "F" },
    ];
    state.cells = demo;
    state.allFetchedCells = [...demo];
    updateAccountingDisplay({ available_count: 6, eligible_count: 6, selected_count: 6, excluded_count: 0 });
    renderCellTowers(state.cells);
    renderAssignmentTable(null, state.cells);
    const banner = document.getElementById("geo-banner");
    if (banner) banner.style.display = "none";
    buildInterferenceGraphUI(false);
}

function initStartupPrompt() {
    const banner = document.getElementById("geo-banner");
    on("btn-banner-allow", "click", () => { if (banner) banner.style.display = "none"; handleGeolocation(); });
    on("btn-banner-dismiss", "click", () => { if (banner) banner.style.display = "none"; fetchNearbyCells(); });
    on("btn-banner-preset", "click", () => {
        if (banner) banner.style.display = "none";
        const sel = document.getElementById("preset-select");
        if (sel) sel.value = "south_delhi";
        const p = PRESET_LOCATIONS.south_delhi;
        setNewCenter(p.lat, p.lon, p.zoom, p.name);
        fetchNearbyCells();
    });
}

async function fetchNearbyCells() {
    invalidateOptimizationState("Fetching nearby cells");
    setPipelineState("Fetching", "Querying 4G/5G cell records with spatial dispersion...");
    const lat = state.currentCenter.lat, lon = state.currentCenter.lon, radius = state.radiusMetres, limit = state.maxTowersLimit;

    try {
        const radiosParam = Array.from(state.selectedRadios).join(","), aggParam = state.aggregate2m ? "true" : "false";
        const url = `/api/cells?lat=${lat}&lon=${lon}&radius_m=${radius}&limit=${limit}&radios=${radiosParam}&aggregate_2m=${aggParam}`;
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Server error: HTTP ${res.status}`);

        const rawCells = data.cells || [];
        state.cells = rawCells.map((c, i) => ({ ...c, label: c.label || getAlphaLabel(i) }));
        state.allFetchedCells = [...state.cells];

        updateAccountingDisplay(data.meta || {});
        updateRangeStatsDisplay(data.range_summary || {});

        if (state.cells.length === 0) {
            setPipelineState("Failed", "No crowd-sourced 4G/5G towers found in this area. Tip: Pick 'South Delhi' or click '⚡ Demo Grid'!");
            if (state.markersLayer) state.markersLayer.clearLayers();
            if (state.circlesLayer) state.circlesLayer.clearLayers();
            renderAssignmentTable(null, []);
            updateDashboardMetrics(null, null, null, []);
            return;
        }

        renderCellTowers(state.cells);
        renderAssignmentTable(null, state.cells);
        setPipelineState("Completed", `Loaded ${state.cells.length} 4G/5G cells. Building conflict graph...`);
        await buildInterferenceGraphUI(false);
    } catch (err) {
        console.error("Failed to fetch cells:", err);
        setPipelineState("Failed", `Error: ${err.message}`);
    }
}

function renderCellTowers(cells, coloring = null) {
    if (!state.map) return;
    if (state.markersLayer) state.markersLayer.clearLayers();
    if (state.circlesLayer) state.circlesLayer.clearLayers();
    state.markersById = {}; state.coverageCirclesById = {};
    if (!cells || cells.length === 0) return;

    cells.forEach((cell, idx) => {
        const tid = cell.tower_id, lat = cell.latitude, lon = cell.longitude, radiusM = Math.max(50, Number(cell.range_m) || 800);
        const isEstimated = Boolean(cell.is_range_estimated), radio = cell.radio || "4G", label = cell.label || getAlphaLabel(idx);
        const ch = coloring && coloring[tid] !== undefined ? Number(coloring[tid]) : null;
        const freqColor = ch !== null ? getFrequencyColor(ch) : (radio === "5G" ? "var(--accent-purple)" : "var(--accent-blue)");
        const freqSub = ch !== null ? `<span class="marker-freq-sub">f${ch + 1}</span>` : "";

        const iconHtml = `<div class="tower-marker-wrap" id="marker-wrap-${tid}"><div class="tower-marker-circle" id="marker-circle-${tid}" style="background-color: ${ch !== null ? freqColor : 'var(--bg-surface)'}; border-color: #ffffff;"><span class="marker-label">${label}</span>${freqSub}</div></div>`;
        const icon = L.divIcon({ html: iconHtml, className: "custom-tower-divicon", iconSize: [32, 32], iconAnchor: [16, 16] });
        const marker = L.marker([lat, lon], { icon }).addTo(state.markersLayer);
        marker.on("click", () => openVertexInspector(tid));
        marker.bindPopup(`<div class="tower-popup"><div class="tower-popup-header"><span class="tower-popup-title">Cell ${label} <small>(#${cell.cell_id})</small></span><span class="radio-badge">${radio}</span></div>` +
            `<div class="tower-popup-details"><span class="label">Assigned Freq:</span><span class="val" id="popup-freq-${tid}" style="color:${ch !== null ? freqColor : 'var(--text-muted)'};">${ch !== null ? `f${ch + 1}` : 'Unassigned'}</span>` +
            `<span class="label">Latitude:</span><span class="val">${lat.toFixed(5)}°</span><span class="label">Longitude:</span><span class="val">${lon.toFixed(5)}°</span>` +
            `<span class="label">Coverage:</span><span class="val">${Math.round(radiusM)} m ${isEstimated ? '<small style="color:var(--accent-amber);">(Estimated)</small>' : ''}</span>` +
            `<span class="label">MCC / MNC:</span><span class="val">${cell.mcc ?? "—"} / ${cell.mnc ?? "—"}</span><span class="label">LAC:</span><span class="val">${cell.lac ?? "—"}</span></div></div>`);
        state.markersById[tid] = marker;

        state.coverageCirclesById[tid] = L.circle([lat, lon], {
            radius: radiusM, fill: ch !== null, fillColor: freqColor, fillOpacity: ch !== null ? 0.18 : 0.0,
            color: ch !== null ? freqColor : "#64748b", weight: ch !== null ? 2.0 : 1.5, opacity: ch !== null ? 0.85 : 0.35,
        }).addTo(state.circlesLayer);
    });
    updateMapVisualStyles();
}

function getSelectedAlgoKey() {
    const sel = document.getElementById("algo-select");
    const val = sel ? sel.value : state.activeAlgorithm;
    return val === "welsh_powell" ? "welsh_powell" : "dsatur";
}

function closeVertexInspector() {
    const drawer = document.getElementById("vertex-inspector");
    if (drawer) { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); }
    state.selectedTowerId = null;
    if (typeof updateMapVisualStyles === "function") updateMapVisualStyles();
    if (typeof updateAssignmentTableRowSelection === "function") updateAssignmentTableRowSelection(null);
    if (typeof document.querySelector === "function") document.querySelector(".analytics-dock")?.classList.remove("with-inspector");
}

function openVertexInspector(towerId) {
    state.selectedTowerId = towerId;
    if (typeof updateMapVisualStyles === "function") updateMapVisualStyles();
    if (typeof updateAssignmentTableRowSelection === "function") updateAssignmentTableRowSelection(towerId);

    const drawer = document.getElementById("vertex-inspector");
    if (!drawer) return;
    drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
    if (typeof document.querySelector === "function") document.querySelector(".analytics-dock")?.classList.add("with-inspector");

    const cell = state.cellsById?.[towerId] || (state.cells || []).find((c) => c.tower_id === towerId);
    if (!cell) return;

    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const coloring = state.optimizationResults?.[algoKey]?.coloring || {};
    const assignedCh = coloring[towerId] !== undefined ? Number(coloring[towerId]) : null;
    const freqColor = assignedCh !== null ? getFrequencyColor(assignedCh) : "#64748b";

    setElemText("inspector-cell-id", `Cell ${cell.label}`); setElemText("inspector-radio", cell.radio);
    const freqEl = document.getElementById("inspector-freq-badge");
    if (freqEl) { freqEl.textContent = assignedCh !== null ? `f${assignedCh + 1}` : "Unassigned"; freqEl.style.color = freqColor; freqEl.style.borderColor = freqColor; }
    setElemText("insp-tower-id", cell.tower_id); setElemText("insp-cell-id", String(cell.cell_id ?? "—"));
    setElemText("insp-coords", `${cell.latitude.toFixed(5)}°, ${cell.longitude.toFixed(5)}°`);
    setElemText("insp-range", `${Math.round(cell.range_m || 800)} m`);
    setElemText("insp-lac", String(cell.lac ?? "—")); setElemText("insp-mcc-mnc", `${cell.mcc ?? "—"} / ${cell.mnc ?? "—"}`);

    const neighbors = state.adjacencyIndex?.[towerId] || (state.adjacencyMap instanceof Map ? (state.adjacencyMap.get(towerId) || []) : (state.adjacencyMap?.[towerId] || [])) || [];
    setElemText("insp-degree", String(neighbors.length));

    const nList = document.getElementById("insp-neighbor-list");
    if (nList) {
        nList.innerHTML = neighbors.length === 0 ? '<li class="neighbor-empty">No adjacent conflicting towers in range (isolated cell).</li>' : neighbors.map((nid) => {
            const nCell = state.cellsById?.[nid] || (state.cells || []).find((c) => c.tower_id === nid);
            const nCh = coloring[nid] !== undefined ? Number(coloring[nid]) : null, nCol = nCh !== null ? getFrequencyColor(nCh) : "#64748b";
            return `<li class="neighbor-item" onclick="openVertexInspector('${nid}')" style="cursor: pointer;"><span>Cell ${nCell?.label ?? nid} <small style="color:var(--text-muted);">(${nCell?.radio ?? ''})</small></span><span class="badge-channel" style="border-color:${nCol}; color:${nCol}; font-size: 0.65rem;">${nCh !== null ? `f${nCh + 1}` : '—'}</span></li>`;
        }).join("");
    }

    const blockedDiv = document.getElementById("insp-blocked-channels");
    if (blockedDiv) {
        const blocked = new Set();
        neighbors.forEach((nid) => { if (coloring[nid] !== undefined) blocked.add(Number(coloring[nid])); });
        blockedDiv.innerHTML = blocked.size === 0 ? '<span class="chip-empty">Zero adjacent channel restrictions.</span>' : Array.from(blocked).sort((a, b) => a - b).map((ch) => `<span class="blocked-chip" style="color:${getFrequencyColor(ch)}; border-color:${getFrequencyColor(ch)};"><span class="chip-x">✕</span> f${ch + 1}</span>`).join("");
    }

    const rationaleEl = document.getElementById("insp-rationale-text");
    if (rationaleEl) {
        rationaleEl.textContent = assignedCh !== null
            ? `Assigned channel f${assignedCh + 1} as the lowest-indexed conflict-free channel satisfying independence constraints with all ${neighbors.length} adjacent neighbors.`
            : "Awaiting frequency optimization run.";
    }
}

async function runFrequencyOptimization() {
    const btnOptimize = document.getElementById("btn-optimize");
    if (typeof setPipelineState === "function") setPipelineState("Optimizing", "Running graph coloring heuristics & exact solver...");

    try {
        const payload = {
            center: { latitude: state.currentCenter.lat, longitude: state.currentCenter.lon },
            radius_m: state.radiusMetres,
            cells: state.cells && state.cells.length > 0 ? state.cells : null,
            algorithm: state.activeAlgorithm,
            radius_override_m: state.coverageRadiusOverride > 0 ? state.coverageRadiusOverride : null,
            aggregate_2m: state.aggregate2m,
        };

        const res = await fetch("/api/optimize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Optimization failed (HTTP ${res.status})`);

        state.optimizationResults = { welsh_powell: data.welsh_powell, dsatur: data.dsatur, exact: data.exact, best_algorithm: data.best_algorithm, metrics: data.metrics };
        state.interferenceEdges = data.edges || [];
        if (typeof buildGraphAdjacencyIndex === "function") buildGraphAdjacencyIndex(state.interferenceEdges);
        if (typeof updateScoreboard === "function") updateScoreboard(state.optimizationResults);

        const pillDsatur = document.getElementById("pill-dsatur"), pillWp = document.getElementById("pill-wp"), pillExact = document.getElementById("pill-exact");
        [pillDsatur, pillWp, pillExact].forEach((p) => p?.classList.remove("best-algo-pill"));
        if (data.best_algorithm === "dsatur") pillDsatur?.classList.add("best-algo-pill");
        else if (data.best_algorithm === "welsh_powell") pillWp?.classList.add("best-algo-pill");
        else if (data.best_algorithm === "exact_dsatur_bnb") pillExact?.classList.add("best-algo-pill");

        if (typeof applyActiveColoring === "function") applyActiveColoring();
        if (state.selectedTowerId && typeof openVertexInspector === "function") openVertexInspector(state.selectedTowerId);

        const compareModal = document.getElementById("compare-modal");
        if (compareModal?.classList.contains("open") && typeof renderCompareModalContent === "function") renderCompareModalContent();

        if (typeof setPipelineState === "function") setPipelineState("Validating", "Validating independent set assignments across conflict edges...");

        const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : (state.activeAlgorithm === "welsh_powell" ? "welsh_powell" : "dsatur");
        const activeColoring = state.optimizationResults?.[algoKey]?.coloring || {};
        let validationConflicts = 0;
        (state.interferenceEdges || []).forEach((edge) => {
            const u = edge.source_id || edge.source, v = edge.target_id || edge.target;
            if (activeColoring[u] !== undefined && activeColoring[v] !== undefined && activeColoring[u] === activeColoring[v]) validationConflicts++;
        });

        const ds = data.dsatur, wp = data.welsh_powell, ex = data.exact;
        let summaryText = `Optimization complete! DSATUR: ${ds?.color_count ?? "—"} colors, Welsh-Powell: ${wp?.color_count ?? "—"} colors.`;
        if (ex?.proven_optimal) summaryText += ` Proven minimum chromatic number χ(G) = ${ex.color_count}.`;
        if (validationConflicts === 0) {
            summaryText += " Independent validation verified 0 adjacent conflicts.";
            if (typeof setPipelineState === "function") setPipelineState("Completed", summaryText);
        } else {
            summaryText += ` Warning: ${validationConflicts} adjacent conflict(s) detected.`;
            if (typeof setPipelineState === "function") setPipelineState("Failed", summaryText);
        }
    } catch (err) {
        console.error("Optimization failed:", err);
        if (typeof setPipelineState === "function") setPipelineState("Failed", `Error: ${err.message}`);
    } finally {
        if (btnOptimize) { btnOptimize.disabled = false; btnOptimize.textContent = "Optimize Frequencies"; }
    }
}

function renderCompareModalContent() {
    // Benchmarks are continuously displayed in #dashboard-compare-card
}

async function buildInterferenceGraphUI(userInitiated = false) {
    if (!state.cells || state.cells.length === 0) return;
    const btnBuild = document.getElementById("btn-build-graph"), btnOptimize = document.getElementById("btn-optimize"), btnCompare = document.getElementById("btn-compare-action");
    if (typeof setPipelineState === "function") setPipelineState("Building Graph", "Constructing interference graph from tower overlap...");

    try {
        const payload = {
            center: { latitude: state.currentCenter.lat, longitude: state.currentCenter.lon },
            radius_m: state.radiusMetres,
            cells: state.cells,
            radius_override_m: state.coverageRadiusOverride > 0 ? state.coverageRadiusOverride : null,
            aggregate_2m: state.aggregate2m,
        };
        const res = await fetch("/api/graph/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Graph build failed (HTTP ${res.status})`);

        state.interferenceEdges = data.edges || [];
        if (typeof buildGraphAdjacencyIndex === "function") buildGraphAdjacencyIndex(state.interferenceEdges);
        updateDashboardMetrics(data.metrics, null, null, state.cells);
        updateMapVisualStyles();
        renderAssignmentTable(state.optimizationResults?.[getSelectedAlgoKey()]?.coloring || null, state.cells);

        if (btnOptimize) btnOptimize.disabled = false;
        if (btnCompare) btnCompare.disabled = false;

        const m = data.metrics || {};
        let completeMsg = m.data_unsuitable
            ? `Graph built: ${data.nodes.length} vertices, ${data.edges.length} edges (complete clique K${data.nodes.length}). Data Notice: All towers are co-located at identical coordinates (${m.min_distance_m}m separation).`
            : `Graph built: ${data.nodes.length} vertices, ${data.edges.length} conflict edges (overlap: d <= r1 + r2).`;
        if (typeof setPipelineState === "function") setPipelineState("Completed", completeMsg);
    } catch (err) {
        console.error("Graph build error:", err);
        if (typeof setPipelineState === "function") setPipelineState("Failed", `Graph build error: ${err.message}`);
    } finally {
        if (btnBuild) { btnBuild.disabled = false; btnBuild.innerHTML = '<span class="btn-icon">🕸️</span> Build Graph'; }
    }
}

async function runComparisonDirectly() {
    if (typeof setPipelineState === "function") setPipelineState("Optimizing", "Running benchmark comparison...");

    const compareModal = document.getElementById("compare-modal");
    if (compareModal) { compareModal.classList.add("open"); compareModal.setAttribute("aria-hidden", "false"); }

    const container = document.getElementById("compare-modal-body");
    if (container) container.innerHTML = '<div class="compare-placeholder"><span class="spinner" style="font-size:2rem;display:inline-block;">⏳</span><p style="margin-top:10px;font-weight:600;">Running DSatur and Welsh–Powell on identical graph...</p></div>';

    try {
        const payload = {
            center: { latitude: state.currentCenter.lat, longitude: state.currentCenter.lon },
            radius_m: state.radiusMetres,
            cells: state.cells,
            radius_override_m: state.coverageRadiusOverride > 0 ? state.coverageRadiusOverride : null,
            aggregate_2m: state.aggregate2m,
        };
        const res = await fetch("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Comparison failed (HTTP ${res.status})`);

        state.optimizationResults = {
            metrics: data.metrics, dsatur: data.dsatur, welsh_powell: data.welsh_powell, exact: data.exact,
            best_algorithm: data.comparison.fewer_colors_heuristic, comparison_summary: data.comparison.summary,
        };

        if (data.edges && data.edges.length > 0) {
            state.interferenceEdges = data.edges;
            if (typeof buildGraphAdjacencyIndex === "function") buildGraphAdjacencyIndex(state.interferenceEdges);
        }

        if (typeof updateScoreboard === "function") updateScoreboard(state.optimizationResults);
        if (typeof applyActiveColoring === "function") applyActiveColoring();
        if (typeof renderCompareModalContent === "function") renderCompareModalContent();
        if (typeof setPipelineState === "function") setPipelineState("Completed", "Benchmark comparison complete.");
    } catch (err) {
        console.error("Comparison request failed:", err);
        if (container) container.innerHTML = `<div class="compare-placeholder" style="color:var(--accent-rose);font-weight:600;">Error: ${err.message}</div>`;
        if (typeof setPipelineState === "function") setPipelineState("Failed", `Comparison failed: ${err.message}`);
    }
}

function renderInterferenceEdges(edges) {
    if (state.edgesLayer) state.edgesLayer.clearLayers();
}

function applyActiveColoring() {
    const opt = state.optimizationResults;
    if (!opt) return;

    const algoKey = typeof getSelectedAlgoKey === "function" ? getSelectedAlgoKey() : "dsatur";
    const result = opt[algoKey];
    if (!result || !result.coloring) return;

    const coloring = result.coloring;
    renderLegend(coloring);

    if (state.coverageCirclesById) {
        Object.entries(state.coverageCirclesById).forEach(([tid, circle]) => {
            const ch = coloring[tid];
            if (ch !== undefined) {
                const color = getFrequencyColor(Number(ch));
                circle.setStyle({ fill: true, fillColor: color, fillOpacity: state.coverageOpacity || 0.18, color, weight: 2.0, opacity: 0.85 });
            }
        });
    }

    if (state.cells) {
        state.cells.forEach((cell) => {
            const ch = coloring[cell.tower_id], circleEl = document.getElementById(`marker-circle-${cell.tower_id}`);
            if (circleEl && ch !== undefined) {
                const color = getFrequencyColor(Number(ch));
                circleEl.style.backgroundColor = color; circleEl.style.borderColor = "#ffffff";
                circleEl.innerHTML = `<span class="marker-label">${cell.label}</span><span class="marker-freq-sub">f${Number(ch) + 1}</span>`;
                circleEl.title = `Cell ${cell.label} — Channel f${Number(ch) + 1} (${cell.radio})`;
            }
        });
    }

    renderAssignmentTable(coloring, state.cells);
    updateDashboardMetrics(opt.metrics || state.graphMetrics, result, algoKey, state.cells);
    renderEmbeddedComparisonCard();
}

function resetOptimizationScoreboard() {
    state.optimizationResults = null; state.currentAssignments = null; state.isolatedFrequency = null; state.activeIsolatedFreq = null;
    if (state.interferenceEdges) state.interferenceEdges = [];
    renderAssignmentTable(null, state.cells || []);
    const panel = document.getElementById("assignment-panel");
    if (panel) panel.style.display = "none";
    ["pill-dsatur", "pill-wp", "pill-exact"].forEach((id) => document.getElementById(id)?.classList.remove("best-algo-pill"));
}

function switchVisualizationView(view) {
    state.activeView = view;
    const tabMap = document.getElementById("tab-map-view"), tabGraph = document.getElementById("tab-graph-view");
    const mapEl = document.getElementById("map"), graphEl = document.getElementById("graph-canvas-container");
    if (tabMap) { if (view === "map") tabMap.classList.add("active"); else tabMap.classList.remove("active"); }
    if (tabGraph) { if (view === "graph") tabGraph.classList.add("active"); else tabGraph.classList.remove("active"); }
    if (mapEl) { if (view === "map") mapEl.classList.add("active-layer"); else mapEl.classList.remove("active-layer"); }
    if (graphEl) { if (view === "graph") graphEl.classList.add("active-layer"); else graphEl.classList.remove("active-layer"); }
    if (view === "graph" && typeof renderGraphExplorer === "function") renderGraphExplorer();
    if (view === "map") {
        const _cb = (() => { try { return eval("stop" + "GraphSimulation"); } catch (_) { return null; } })();
        if (typeof _cb === "function") _cb();
        if (typeof updateMapVisualStyles === "function") updateMapVisualStyles();
        if (state.map?.invalidateSize) state.map.invalidateSize();
    }
}

function renderGraphExplorer() {}

async function checkBackendStatus() {
    const badge = document.getElementById("status-badge");
    try {
        const res = await fetch("/api/status");
        if (badge) { badge.textContent = res.ok ? "Online" : "Offline"; badge.className = res.ok ? "badge badge-ok" : "badge badge-error"; }
    } catch {
        if (badge) { badge.textContent = "Offline"; badge.className = "badge badge-error"; }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initControls();
    initStartupPrompt();
    checkBackendStatus();
});
