/**
 * app.js — SpectraMap frontend logic
 *
 * Handles:
 * 1. Leaflet map initialization with OpenStreetMap tiles.
 * 2. Backend health check (/api/status).
 * 3. Area selection (dragging center marker, map click, geolocation, presets, radius slider).
 * 4. Fetching cell tower records (/api/cells), sub-grid tiling, and rendering interactive markers.
 * 5. Optimization runner (/api/optimize), interference lines, marker coloring, and algorithm scoreboard.
 */

// Global state
const state = {
    map: null,
    centerMarker: null,
    searchCircle: null,
    currentCenter: { lat: 28.5224, lon: 77.1906 }, // Default: South Delhi (dense cellular cluster with 100+ towers)
    radiusMetres: 1500,
    cells: [],
    cellsById: {},
    markersById: {},
    interferenceEdges: [],
    optimizationResults: null,
    activeAlgorithm: "both",
    cellMarkersLayer: null,
    coverageCirclesLayer: null,
    edgesLayer: null,
};

// Distinct color palette for up to 10 frequencies (Hex codes)
const FREQUENCY_COLORS = [
    "#3b82f6", // Frequency 1: Blue
    "#10b981", // Frequency 2: Emerald Green
    "#f59e0b", // Frequency 3: Amber
    "#ef4444", // Frequency 4: Red
    "#8b5cf6", // Frequency 5: Purple
    "#ec4899", // Frequency 6: Pink
    "#06b6d4", // Frequency 7: Cyan
    "#84cc16", // Frequency 8: Lime
    "#f97316", // Frequency 9: Orange
    "#64748b", // Frequency 10: Slate
];

// Preset locations with rich, guaranteed cell tower density
const PRESET_LOCATIONS = {
    south_delhi: { lat: 28.5224, lon: 77.1906, name: "South Delhi (100+ Live Towers)" },
    connaught_place: { lat: 28.6300, lon: 77.2180, name: "Connaught Place (Central Delhi)" },
    mumbai: { lat: 18.9430, lon: 72.8250, name: "Mumbai (Marine Lines)" },
};

// Initialize application when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initControls();
    checkBackendStatus();
});

/**
 * Initializes the Leaflet map centered at default coordinates.
 */
function initMap() {
    // 1. Create map instance
    state.map = L.map("map", {
        center: [state.currentCenter.lat, state.currentCenter.lon],
        zoom: 14,
    });

    // 2. Add OpenStreetMap tile layer
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(state.map);

    // 3. Layer groups to manage dynamic markers and lines easily
    state.coverageCirclesLayer = L.layerGroup().addTo(state.map);
    state.edgesLayer = L.layerGroup().addTo(state.map);
    state.cellMarkersLayer = L.layerGroup().addTo(state.map);

    // 4. Draw initial search center and radius circle
    updateCenterVisuals(state.currentCenter.lat, state.currentCenter.lon);

    // 5. Allow clicking on the map to change the search center
    state.map.on("click", (e) => {
        const presetSelect = document.getElementById("preset-select");
        if (presetSelect) presetSelect.value = "custom";
        setNewCenter(e.latlng.lat, e.latlng.lng);
    });
}

/**
 * Updates or creates the center pin and the search radius boundary circle.
 */
function updateCenterVisuals(lat, lon) {
    if (!state.centerMarker) {
        state.centerMarker = L.marker([lat, lon], {
            draggable: true,
            title: "Analysis Center",
        }).addTo(state.map);

        // When the user drags the pin, update center coordinates
        state.centerMarker.on("dragend", (e) => {
            const pos = e.target.getLatLng();
            const presetSelect = document.getElementById("preset-select");
            if (presetSelect) presetSelect.value = "custom";
            setNewCenter(pos.lat, pos.lng);
        });
    } else {
        state.centerMarker.setLatLng([lat, lon]);
    }

    if (!state.searchCircle) {
        state.searchCircle = L.circle([lat, lon], {
            radius: state.radiusMetres,
            color: "#3b82f6",
            fillColor: "#3b82f6",
            fillOpacity: 0.1,
            weight: 2,
            dashArray: "5, 5",
        }).addTo(state.map);
    } else {
        state.searchCircle.setLatLng([lat, lon]);
        state.searchCircle.setRadius(state.radiusMetres);
    }
}

/**
 * Sets a new search center and re-draws center visuals.
 */
function setNewCenter(lat, lon) {
    state.currentCenter = { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) };
    updateCenterVisuals(lat, lon);
    const overlay = document.getElementById("map-overlay");
    if (overlay) {
        overlay.textContent = `Center: ${state.currentCenter.lat}, ${state.currentCenter.lon} (Click 'Fetch Nearby Towers')`;
    }
}

/**
 * Hooks up UI event listeners (slider, buttons, checkboxes, dropdowns).
 */
function initControls() {
    // Radius slider
    const radiusSlider = document.getElementById("radius-slider");
    const radiusLabel = document.getElementById("radius-label");
    if (radiusSlider && radiusLabel) {
        radiusSlider.addEventListener("input", (e) => {
            state.radiusMetres = Number(e.target.value);
            radiusLabel.textContent = state.radiusMetres;
            if (state.searchCircle) {
                state.searchCircle.setRadius(state.radiusMetres);
            }
        });
    }

    // Popular Presets dropdown
    const presetSelect = document.getElementById("preset-select");
    if (presetSelect) {
        presetSelect.addEventListener("change", (e) => {
            const val = e.target.value;
            if (val !== "custom" && PRESET_LOCATIONS[val]) {
                const loc = PRESET_LOCATIONS[val];
                setNewCenter(loc.lat, loc.lon);
                state.map.setView([loc.lat, loc.lon], 14);
                fetchNearbyCells();
            }
        });
    }

    // "My GPS Location" button (HTML5 Geolocation)
    const btnLocate = document.getElementById("btn-locate");
    if (btnLocate) {
        btnLocate.addEventListener("click", handleGeolocation);
    }

    // "Demo Grid" button (Generates simulated towers anywhere)
    const btnDemo = document.getElementById("btn-demo");
    if (btnDemo) {
        btnDemo.addEventListener("click", loadDemoTowers);
    }

    // "Fetch Nearby Towers" button
    const btnFetch = document.getElementById("btn-fetch");
    if (btnFetch) {
        btnFetch.addEventListener("click", fetchNearbyCells);
    }

    // "Optimize Frequencies" button
    const btnOptimize = document.getElementById("btn-optimize");
    if (btnOptimize) {
        btnOptimize.addEventListener("click", runFrequencyOptimization);
    }

    // Toggle interference lines checkbox
    const toggleEdges = document.getElementById("toggle-edges");
    if (toggleEdges) {
        toggleEdges.addEventListener("change", (e) => {
            if (e.target.checked) {
                if (!state.map.hasLayer(state.edgesLayer)) {
                    state.map.addLayer(state.edgesLayer);
                }
            } else {
                if (state.map.hasLayer(state.edgesLayer)) {
                    state.map.removeLayer(state.edgesLayer);
                }
            }
        });
    }

    // Algorithm selection dropdown
    const algoSelect = document.getElementById("algo-select");
    if (algoSelect) {
        algoSelect.addEventListener("change", (e) => {
            state.activeAlgorithm = e.target.value;
            if (state.optimizationResults) {
                applyActiveColoring();
            }
        });
    }
}

/**
 * Uses browser HTML5 Geolocation to center map on user's current location.
 */
function handleGeolocation() {
    const statusMsg = document.getElementById("cells-status");
    if (!navigator.geolocation) {
        if (statusMsg) statusMsg.textContent = "Geolocation is not supported by your browser.";
        return;
    }

    if (statusMsg) {
        statusMsg.textContent = "Locating your position via GPS...";
        statusMsg.style.color = "var(--text-secondary)";
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const { latitude, longitude } = pos.coords;
            setNewCenter(latitude, longitude);
            state.map.setView([latitude, longitude], 14);
            if (statusMsg) {
                statusMsg.textContent = "Location updated to your coordinates! Click 'Fetch Nearby Towers'.";
                statusMsg.style.color = "var(--accent-success)";
            }
        },
        (err) => {
            console.warn("Geolocation failed:", err.message);
            if (statusMsg) {
                statusMsg.textContent = "Could not get GPS location. Using manual map point.";
                statusMsg.style.color = "var(--accent-warning)";
            }
        },
        { timeout: 10000 }
    );
}

/**
 * Generates simulated cellular towers around the current center.
 * Ensures the user can test graph coloring anywhere, even if an area lacks OpenCellID data.
 */
function loadDemoTowers() {
    const statusMsg = document.getElementById("cells-status");
    const metricTowers = document.getElementById("metric-towers");
    const btnOptimize = document.getElementById("btn-optimize");

    const center = state.currentCenter;
    const demoTowers = [];
    const count = 12;

    // Arrange 12 simulated towers in two concentric rings with overlapping coverage
    for (let i = 0; i < count; i++) {
        const isInner = i < 6;
        const angle = ((i % 6) * 2 * Math.PI) / 6 + (isInner ? 0 : Math.PI / 6);
        const dist = isInner ? 600 : 1200;
        const dLat = (dist * Math.cos(angle)) / 111139.0;
        const dLon = (dist * Math.sin(angle)) / (111139.0 * Math.cos((center.lat * Math.PI) / 180));

        demoTowers.push({
            tower_id: `DEMO_LTE_${i + 1}`,
            cell_id: 900000 + (i + 1),
            radio: i % 3 === 0 ? "5G NR" : "4G LTE",
            latitude: Number((center.lat + dLat).toFixed(5)),
            longitude: Number((center.lon + dLon).toFixed(5)),
            range_m: 850.0,
            mcc: 404,
            mnc: 11,
            lac: 50001,
        });
    }

    state.cells = demoTowers;
    renderCellTowers(demoTowers);

    if (metricTowers) metricTowers.textContent = demoTowers.length;
    resetOptimizationScoreboard();

    statusMsg.textContent = `Generated ${demoTowers.length} simulated cellular towers with overlapping coverage. Click 'Optimize Frequencies'!`;
    statusMsg.style.color = "var(--accent-success)";
    if (btnOptimize) btnOptimize.disabled = false;
}

/**
 * Fetches nearby cell towers from /api/cells and renders them on the map.
 */
async function fetchNearbyCells() {
    const btnFetch = document.getElementById("btn-fetch");
    const statusMsg = document.getElementById("cells-status");
    const btnOptimize = document.getElementById("btn-optimize");
    const metricTowers = document.getElementById("metric-towers");

    // Prevent concurrent requests
    btnFetch.disabled = true;
    btnFetch.textContent = "Fetching Cells...";
    statusMsg.textContent = "Querying cell towers via sub-grid tiling...";
    statusMsg.style.color = "var(--text-secondary)";

    try {
        const url = `/api/cells?lat=${state.currentCenter.lat}&lon=${state.currentCenter.lon}&radius_m=${state.radiusMetres}`;
        const res = await fetch(url);
        const data = await res.json();

        if (!res.ok) {
            const errorMsg = data.detail || `Server error (HTTP ${res.status})`;
            throw new Error(errorMsg);
        }

        state.cells = data.cells || [];
        renderCellTowers(state.cells);

        // Update scoreboard
        if (metricTowers) {
            metricTowers.textContent = state.cells.length;
        }

        // Reset previous optimization results
        resetOptimizationScoreboard();

        if (state.cells.length === 0) {
            statusMsg.innerHTML = "No crowd-sourced towers registered at this exact spot. <strong>Tip:</strong> Pick <em>'South Delhi (100+ Live Towers)'</em> or click <em>'⚡ Demo Grid'</em>!";
            statusMsg.style.color = "var(--accent-warning)";
            if (btnOptimize) btnOptimize.disabled = true;
        } else {
            let info = `Found ${state.cells.length} towers within ${state.radiusMetres}m.`;
            if (data.metadata?.is_partial) {
                info += " (Results include 50-limit tile caps).";
            }
            if (data.metadata?.cached) {
                info += " [Loaded from cache]";
            }
            statusMsg.textContent = info;
            statusMsg.style.color = "var(--accent-success)";
            if (btnOptimize) btnOptimize.disabled = false;
        }
    } catch (err) {
        console.error("Fetch cells failed:", err);
        statusMsg.textContent = `Error: ${err.message}`;
        statusMsg.style.color = "var(--accent-error)";
        if (btnOptimize) btnOptimize.disabled = true;
    } finally {
        btnFetch.disabled = false;
        btnFetch.textContent = "Fetch Nearby Towers";
    }
}

/**
 * Renders cell towers on the map as styled circle markers with interactive popups.
 */
function renderCellTowers(cells) {
    state.cellMarkersLayer.clearLayers();
    state.coverageCirclesLayer.clearLayers();
    state.edgesLayer.clearLayers();
    state.markersById = {};
    state.cellsById = {};

    cells.forEach((cell) => {
        state.cellsById[cell.tower_id] = cell;

        // 1. Faint coverage circle showing transmission range
        const coverageCircle = L.circle([cell.latitude, cell.longitude], {
            radius: cell.range_m,
            color: "#0284c7",
            weight: 1,
            opacity: 0.35,
            fillColor: "#38bdf8",
            fillOpacity: 0.05,
            dashArray: "3, 4",
        });
        state.coverageCirclesLayer.addLayer(coverageCircle);

        // 2. Crisp, styled center marker for the tower
        const marker = L.circleMarker([cell.latitude, cell.longitude], {
            radius: 8,
            fillColor: "#38bdf8",
            color: "#ffffff",
            weight: 2,
            opacity: 1,
            fillOpacity: 0.9,
        });

        // 3. Informative popup card
        const popupContent = `
            <div class="tower-popup">
                <div class="tower-popup-header">
                    <span class="tower-popup-title">Cell #${cell.cell_id}</span>
                    <span class="radio-badge">${cell.radio}</span>
                </div>
                <div class="tower-popup-details">
                    <span class="label">Latitude:</span>
                    <span class="val">${cell.latitude.toFixed(5)}°</span>
                    <span class="label">Longitude:</span>
                    <span class="val">${cell.longitude.toFixed(5)}°</span>
                    <span class="label">Coverage:</span>
                    <span class="val">${Math.round(cell.range_m)} m</span>
                    <span class="label">MCC / MNC:</span>
                    <span class="val">${cell.mcc ?? "-"} / ${cell.mnc ?? "-"}</span>
                    <span class="label">LAC:</span>
                    <span class="val">${cell.lac ?? "-"}</span>
                </div>
            </div>
        `;

        marker.bindPopup(popupContent);
        state.cellMarkersLayer.addLayer(marker);
        state.markersById[cell.tower_id] = marker;
    });

    // Auto-fit map to show all rendered cell towers
    const markerList = Object.values(state.markersById);
    if (markerList.length > 0) {
        const group = L.featureGroup(markerList);
        state.map.fitBounds(group.getBounds().pad(0.12));
    }
}

/**
 * Calls POST /api/optimize, displays metrics on scoreboard,
 * renders interference lines, and recolours cell markers by assigned frequency.
 */
async function runFrequencyOptimization() {
    const btnOptimize = document.getElementById("btn-optimize");
    const statusMsg = document.getElementById("cells-status");

    btnOptimize.disabled = true;
    btnOptimize.textContent = "Optimizing...";
    statusMsg.textContent = "Running Welsh-Powell & DSATUR algorithms on backend...";
    statusMsg.style.color = "var(--text-secondary)";

    try {
        const payload = {
            center: {
                latitude: state.currentCenter.lat,
                longitude: state.currentCenter.lon,
            },
            radius_m: state.radiusMetres,
            cells: state.cells.length > 0 ? state.cells : null,
        };

        const res = await fetch("/api/optimize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) {
            const err = data.detail || `Optimization failed (HTTP ${res.status})`;
            throw new Error(err);
        }

        state.optimizationResults = {
            welsh_powell: data.welsh_powell,
            dsatur: data.dsatur,
        };
        state.interferenceEdges = data.edges || [];

        // 1. Populate scoreboard metrics
        const m = data.metrics || {};
        document.getElementById("metric-towers").textContent = m.node_count ?? state.cells.length;
        document.getElementById("metric-edges").textContent = m.edge_count ?? 0;
        document.getElementById("metric-degree").textContent = m.max_degree ?? 0;
        document.getElementById("metric-density").textContent = `${((m.density ?? 0) * 100).toFixed(1)}%`;

        // 2. Populate comparison table
        const wp = data.welsh_powell;
        const ds = data.dsatur;

        if (wp) {
            const isValid = wp.validation?.is_valid ?? wp.is_valid;
            document.getElementById("res-wp-colors").textContent = `${wp.color_count} colors (${wp.runtime_ms.toFixed(2)} ms)`;
            document.getElementById("res-wp-valid").innerHTML = isValid
                ? '<span style="color: var(--accent-success)">✔ Valid</span>'
                : '<span style="color: var(--accent-error)">✖ Collision</span>';
        }

        if (ds) {
            const isValid = ds.validation?.is_valid ?? ds.is_valid;
            document.getElementById("res-dsatur-colors").textContent = `${ds.color_count} colors (${ds.runtime_ms.toFixed(2)} ms)`;
            document.getElementById("res-dsatur-valid").innerHTML = isValid
                ? '<span style="color: var(--accent-success)">✔ Valid</span>'
                : '<span style="color: var(--accent-error)">✖ Collision</span>';
        }

        // 3. Render interference edge polylines
        renderInterferenceEdges(state.interferenceEdges);

        // 4. Color cell markers according to the active algorithm
        applyActiveColoring();

        statusMsg.textContent = `Optimization complete! DSATUR: ${ds?.color_count} frequencies, Welsh-Powell: ${wp?.color_count} frequencies.`;
        statusMsg.style.color = "var(--accent-success)";
    } catch (err) {
        console.error("Optimization failed:", err);
        statusMsg.textContent = `Error: ${err.message}`;
        statusMsg.style.color = "var(--accent-error)";
    } finally {
        btnOptimize.disabled = false;
        btnOptimize.textContent = "Optimize Frequencies";
    }
}

/**
 * Draws polyline edges between towers that interfere with each other.
 */
function renderInterferenceEdges(edges) {
    state.edgesLayer.clearLayers();

    edges.forEach((edge) => {
        const line = L.polyline(
            [edge.source_coords, edge.target_coords],
            {
                color: "#ef4444",
                weight: 2,
                opacity: 0.65,
                dashArray: "4, 4",
            }
        );

        line.bindTooltip(
            `Interference: ${edge.source_id} ↔ ${edge.target_id} (${Math.round(edge.distance_m)}m)`,
            { sticky: true }
        );

        state.edgesLayer.addLayer(line);
    });

    const toggle = document.getElementById("toggle-edges");
    if (toggle && !toggle.checked) {
        if (state.map.hasLayer(state.edgesLayer)) {
            state.map.removeLayer(state.edgesLayer);
        }
    } else {
        if (!state.map.hasLayer(state.edgesLayer)) {
            state.map.addLayer(state.edgesLayer);
        }
    }
}

/**
 * Updates marker colors and popup details to reflect the chosen algorithm's coloring.
 */
function applyActiveColoring() {
    if (!state.optimizationResults) return;

    // Pick algorithm result based on selector:
    // If 'welsh_powell', use Welsh-Powell; otherwise default to DSATUR
    const algoKey = state.activeAlgorithm === "welsh_powell" ? "welsh_powell" : "dsatur";
    const algoResult = state.optimizationResults[algoKey];
    if (!algoResult || !algoResult.coloring) return;

    const coloring = algoResult.coloring;
    const maxFreq = algoResult.color_count || 1;

    // 1. Recolour each marker
    Object.entries(coloring).forEach(([towerId, freq]) => {
        const marker = state.markersById[towerId];
        const cell = state.cellsById[towerId];
        if (!marker || !cell) return;

        const color = FREQUENCY_COLORS[(freq - 1) % FREQUENCY_COLORS.length];
        marker.setStyle({
            fillColor: color,
            color: "#ffffff",
            weight: 2,
            fillOpacity: 0.95,
        });

        // Update popup with assigned frequency
        const algoName = algoKey === "welsh_powell" ? "Welsh-Powell" : "DSATUR";
        const popupContent = `
            <div class="tower-popup">
                <div class="tower-popup-header">
                    <span class="tower-popup-title">Cell #${cell.cell_id}</span>
                    <span class="radio-badge">${cell.radio}</span>
                </div>
                <div class="tower-popup-details">
                    <span class="label">Assigned Freq:</span>
                    <span class="val" style="color: ${color}; font-weight: 700;">Channel f${freq} (${algoName})</span>
                    <span class="label">Latitude:</span>
                    <span class="val">${cell.latitude.toFixed(5)}°</span>
                    <span class="label">Longitude:</span>
                    <span class="val">${cell.longitude.toFixed(5)}°</span>
                    <span class="label">Coverage:</span>
                    <span class="val">${Math.round(cell.range_m)} m</span>
                    <span class="label">MCC / MNC:</span>
                    <span class="val">${cell.mcc ?? "-"} / ${cell.mnc ?? "-"}</span>
                    <span class="label">LAC:</span>
                    <span class="val">${cell.lac ?? "-"}</span>
                </div>
            </div>
        `;
        marker.setPopupContent(popupContent);
    });

    // 2. Render color palette legend
    renderLegend(maxFreq, algoKey);
}

/**
 * Renders the frequency color palette legend chips.
 */
function renderLegend(maxFreq, algoKey) {
    const legendContainer = document.getElementById("legend-container");
    const legendItems = document.getElementById("legend-items");
    if (!legendContainer || !legendItems) return;

    legendItems.innerHTML = "";
    for (let f = 1; f <= maxFreq; f++) {
        const color = FREQUENCY_COLORS[(f - 1) % FREQUENCY_COLORS.length];
        const chip = document.createElement("div");
        chip.className = "legend-chip";
        chip.innerHTML = `
            <span class="legend-color-dot" style="background-color: ${color};"></span>
            <span>Freq ${f} (f${f})</span>
        `;
        legendItems.appendChild(chip);
    }

    legendContainer.style.display = "block";
}

/**
 * Resets optimization scoreboard metrics and hides legend.
 */
function resetOptimizationScoreboard() {
    const elEdges = document.getElementById("metric-edges");
    const elDegree = document.getElementById("metric-degree");
    const elDensity = document.getElementById("metric-density");
    const elWpColors = document.getElementById("res-wp-colors");
    const elWpValid = document.getElementById("res-wp-valid");
    const elDsaturColors = document.getElementById("res-dsatur-colors");
    const elDsaturValid = document.getElementById("res-dsatur-valid");
    const legendContainer = document.getElementById("legend-container");

    if (elEdges) elEdges.textContent = "-";
    if (elDegree) elDegree.textContent = "-";
    if (elDensity) elDensity.textContent = "-";
    if (elWpColors) elWpColors.textContent = "-";
    if (elWpValid) elWpValid.textContent = "-";
    if (elDsaturColors) elDsaturColors.textContent = "-";
    if (elDsaturValid) elDsaturValid.textContent = "-";
    if (legendContainer) legendContainer.style.display = "none";
}

/**
 * Verifies the backend API is reachable at /api/status.
 */
async function checkBackendStatus() {
    const badge = document.getElementById("status-badge");
    try {
        const res = await fetch("/api/status");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (badge) {
            badge.textContent = `Backend: ${data.status.toUpperCase()}`;
            badge.className = "badge badge-ok";
        }
    } catch (err) {
        console.error("Backend health check failed:", err);
        if (badge) {
            badge.textContent = "Backend Offline";
            badge.className = "badge badge-error";
        }
    }
}
