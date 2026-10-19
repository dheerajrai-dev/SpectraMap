/**
 * app.js — SpectraMap frontend logic
 *
 * Professional Geospatial Analytics Dashboard:
 * 1. Leaflet map management & auto-bounds.
 * 2. Backend health check (/api/status).
 * 3. Area selection (presets, drag pin, map click, geolocation, radius slider).
 * 4. Cell tower data retrieval (/api/cells) with sub-grid tiling.
 * 5. Optimization runner (/api/optimize) with dual heuristics (DSATUR & Welsh-Powell).
 * 6. Dual visualization: Geographic Map View & Topology Graph Explorer.
 * 7. Contextual vertex inspector and interactive channel isolator.
 */

// Global state
const state = {
    map: null,
    centerMarker: null,
    searchCircle: null,
    currentCenter: { lat: 28.5224, lon: 77.1906 }, // Default: South Delhi (dense cellular cluster)
    radiusMetres: 1500,
    cells: [],
    cellsById: {},
    markersById: {},
    interferenceEdges: [],
    optimizationResults: null,
    activeAlgorithm: "both",
    activeView: "map",
    selectedTowerId: null,
    isolatedFrequency: null,
    cellMarkersLayer: null,
    coverageCirclesLayer: null,
    edgesLayer: null,
};

// Comprehensive frequency color palette with dynamic generator for arbitrary k
const BASE_FREQUENCY_COLORS = [
    "#3b82f6", // Frequency 1: Blue
    "#10b981", // Frequency 2: Emerald Green
    "#f59e0b", // Frequency 3: Amber
    "#ef4444", // Frequency 4: Crimson Red
    "#8b5cf6", // Frequency 5: Purple
    "#06b6d4", // Frequency 6: Cyan
    "#ec4899", // Frequency 7: Pink
    "#84cc16", // Frequency 8: Lime
    "#f97316", // Frequency 9: Orange
    "#14b8a6", // Frequency 10: Teal
    "#a855f7", // Frequency 11: Violet
    "#eab308", // Frequency 12: Yellow
    "#6366f1", // Frequency 13: Indigo
    "#d946ef", // Frequency 14: Fuchsia
    "#22c55e", // Frequency 15: Green
    "#64748b", // Frequency 16: Slate
];

/**
 * Returns a distinct, accessible color for frequency group index (0-indexed).
 * Supports arbitrary k colors with golden ratio hue progression.
 */
function getFrequencyColor(freqIndex) {
    if (freqIndex >= 0 && freqIndex < BASE_FREQUENCY_COLORS.length) {
        return BASE_FREQUENCY_COLORS[freqIndex];
    }
    const goldenAngle = 137.508;
    const hue = Math.round((freqIndex * goldenAngle) % 360);
    return `hsl(${hue}, 80%, 54%)`;
}

/**
 * Generates deterministic alphabetic sequence labels: 0 -> A, 25 -> Z, 26 -> AA, etc.
 */
function getAlphaLabel(index) {
    let label = "";
    let n = index;
    while (n >= 0) {
        label = String.fromCharCode(65 + (n % 26)) + label;
        n = Math.floor(n / 26) - 1;
    }
    return label;
}

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
    initStartupPrompt();
});

/**
 * Initializes the Leaflet map centered at default coordinates.
 */
function initMap() {
    // 1. Create map instance
    state.map = L.map("map", {
        center: [state.currentCenter.lat, state.currentCenter.lon],
        zoom: 14,
        zoomControl: true,
    });

    // 2. Add OpenStreetMap tile layer
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(state.map);

    // 3. Layer groups to manage dynamic markers and coverage circles
    // NOTE (Phase 2): As per master prompt Section 4, the main geographic map MUST NOT display
    // lines connecting two towers or cell records. state.edgesLayer is NOT added to state.map.
    state.coverageCirclesLayer = L.layerGroup().addTo(state.map);
    state.edgesLayer = L.layerGroup();
    state.cellMarkersLayer = L.layerGroup().addTo(state.map);

    // 4. Draw initial search center and radius circle
    updateCenterVisuals(state.currentCenter.lat, state.currentCenter.lon);

    // 5. Allow clicking on the map to change the search center
    state.map.on("click", (e) => {
        const presetSelect = document.getElementById("preset-select");
        if (presetSelect) presetSelect.value = "custom";
        setNewCenter(e.latlng.lat, e.latlng.lng);
        updateLocationMode("manual");
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
            updateLocationMode("manual");
        });
    } else {
        state.centerMarker.setLatLng([lat, lon]);
    }

    if (!state.searchCircle) {
        state.searchCircle = L.circle([lat, lon], {
            radius: state.radiusMetres,
            color: "#3b82f6",
            fillColor: "#3b82f6",
            fillOpacity: 0.08,
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
        overlay.innerHTML = `<span>Center: ${state.currentCenter.lat.toFixed(5)}°, ${state.currentCenter.lon.toFixed(5)}° (Click 'Fetch Cell Records')</span>`;
    }
}

/**
 * Hooks up UI event listeners (slider, buttons, checkboxes, dropdowns, tabs).
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
                updateLocationMode("preset", loc.name);
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

    // Toggle coverage circles
    const toggleCircles = document.getElementById("toggle-circles");
    if (toggleCircles) {
        toggleCircles.addEventListener("change", (e) => {
            if (e.target.checked) {
                if (!state.map.hasLayer(state.coverageCirclesLayer)) {
                    state.map.addLayer(state.coverageCirclesLayer);
                }
            } else {
                if (state.map.hasLayer(state.coverageCirclesLayer)) {
                    state.map.removeLayer(state.coverageCirclesLayer);
                }
            }
        });
    }

    // Toggle cell markers & labels
    const toggleMarkers = document.getElementById("toggle-markers");
    if (toggleMarkers) {
        toggleMarkers.addEventListener("change", (e) => {
            if (e.target.checked) {
                if (!state.map.hasLayer(state.cellMarkersLayer)) {
                    state.map.addLayer(state.cellMarkersLayer);
                }
            } else {
                if (state.map.hasLayer(state.cellMarkersLayer)) {
                    state.map.removeLayer(state.cellMarkersLayer);
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

    // View Switcher (Map View vs Graph Topology)
    const tabMapView = document.getElementById("tab-map-view");
    const tabGraphView = document.getElementById("tab-graph-view");
    const mapLayer = document.getElementById("map");
    const graphLayer = document.getElementById("graph-canvas-container");

    if (tabMapView && tabGraphView) {
        tabMapView.addEventListener("click", () => {
            tabMapView.classList.add("active");
            tabMapView.setAttribute("aria-selected", "true");
            tabGraphView.classList.remove("active");
            tabGraphView.setAttribute("aria-selected", "false");
            if (mapLayer) mapLayer.classList.add("active-layer");
            if (graphLayer) graphLayer.classList.remove("active-layer");
            state.activeView = "map";
            setTimeout(() => state.map.invalidateSize(), 50);
        });

        tabGraphView.addEventListener("click", () => {
            tabGraphView.classList.add("active");
            tabGraphView.setAttribute("aria-selected", "true");
            tabMapView.classList.remove("active");
            tabMapView.setAttribute("aria-selected", "false");
            if (graphLayer) graphLayer.classList.add("active-layer");
            if (mapLayer) mapLayer.classList.remove("active-layer");
            state.activeView = "graph";
            renderGraphExplorer();
        });
    }

    // Close Inspector button
    const btnCloseInspector = document.getElementById("btn-close-inspector");
    if (btnCloseInspector) {
        btnCloseInspector.addEventListener("click", () => {
            closeVertexInspector();
        });
    }

    // Educational Guide Modal
    const btnGuide = document.getElementById("btn-guide");
    const guideModal = document.getElementById("guide-modal");
    const btnCloseGuide = document.getElementById("btn-close-guide");
    if (btnGuide && guideModal) {
        btnGuide.addEventListener("click", () => {
            guideModal.classList.add("open");
            guideModal.setAttribute("aria-hidden", "false");
        });
    }
    if (btnCloseGuide && guideModal) {
        btnCloseGuide.addEventListener("click", () => {
            guideModal.classList.remove("open");
            guideModal.setAttribute("aria-hidden", "true");
        });
        guideModal.addEventListener("click", (e) => {
            if (e.target === guideModal) {
                guideModal.classList.remove("open");
                guideModal.setAttribute("aria-hidden", "true");
            }
        });
    }

    // Initialize interactive Graph Topology Canvas handlers
    initGraphCanvasInteractions();
}

/**
 * Updates the location status pill in the navbar.
 */
function updateLocationMode(mode, detail) {
    const badge = document.getElementById("location-badge");
    if (!badge) return;

    if (mode === "gps") {
        badge.textContent = "GPS Active";
        badge.className = "badge badge-gps";
    } else if (mode === "manual") {
        badge.textContent = "Manual Center";
        badge.className = "badge badge-manual";
    } else if (mode === "demo") {
        badge.textContent = "Demo Grid";
        badge.className = "badge badge-demo";
    } else if (mode === "preset") {
        badge.textContent = detail ? `Preset: ${detail}` : "Preset Location";
        badge.className = "badge badge-preset";
    }
}

/**
 * Initializes the initial visit geolocation prompt banner.
 */
function initStartupPrompt() {
    const banner = document.getElementById("geo-banner");
    const btnAllow = document.getElementById("btn-banner-allow");
    const btnPreset = document.getElementById("btn-banner-preset");
    const btnDismiss = document.getElementById("btn-banner-dismiss");

    const hasPrompted = sessionStorage.getItem("spectramap_geo_prompted");
    if (!hasPrompted && banner) {
        banner.style.display = "block";
    }

    if (btnAllow) {
        btnAllow.addEventListener("click", () => {
            sessionStorage.setItem("spectramap_geo_prompted", "true");
            if (banner) banner.style.display = "none";
            handleGeolocation();
        });
    }

    if (btnPreset) {
        btnPreset.addEventListener("click", () => {
            sessionStorage.setItem("spectramap_geo_prompted", "true");
            if (banner) banner.style.display = "none";
            const presetSelect = document.getElementById("preset-select");
            if (presetSelect) presetSelect.value = "south_delhi";
            const loc = PRESET_LOCATIONS.south_delhi;
            setNewCenter(loc.lat, loc.lon);
            state.map.setView([loc.lat, loc.lon], 14);
            updateLocationMode("preset", "South Delhi");
            fetchNearbyCells();
        });
    }

    if (btnDismiss) {
        btnDismiss.addEventListener("click", () => {
            sessionStorage.setItem("spectramap_geo_prompted", "true");
            if (banner) banner.style.display = "none";
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
        updateLocationMode("manual");
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
            updateLocationMode("gps");
            if (statusMsg) {
                statusMsg.textContent = "GPS position acquired. Fetching local cells...";
                statusMsg.style.color = "var(--accent-emerald)";
            }
            fetchNearbyCells();
        },
        (err) => {
            console.warn("Geolocation failed:", err.message);
            updateLocationMode("manual");
            if (statusMsg) {
                statusMsg.textContent = "Could not get GPS location. Using manual map point.";
                statusMsg.style.color = "var(--accent-amber)";
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
    const count = 14;

    // Arrange 14 simulated towers in two concentric rings with overlapping coverage
    for (let i = 0; i < count; i++) {
        const isInner = i < 6;
        const angle = ((i % 6) * 2 * Math.PI) / 6 + (isInner ? 0 : Math.PI / 6);
        const dist = isInner ? 550 : 1150;
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
    updateLocationMode("demo");
    renderCellTowers(demoTowers);

    if (metricTowers) metricTowers.textContent = demoTowers.length;
    resetOptimizationScoreboard();

    statusMsg.textContent = `Generated ${demoTowers.length} simulated cellular towers with overlapping coverage. Ready to optimize!`;
    statusMsg.style.color = "var(--accent-emerald)";
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
            statusMsg.style.color = "var(--accent-amber)";
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
            statusMsg.style.color = "var(--accent-emerald)";
            if (btnOptimize) btnOptimize.disabled = false;
        }
    } catch (err) {
        console.error("Fetch cells failed:", err);
        statusMsg.textContent = `Error: ${err.message}`;
        statusMsg.style.color = "var(--accent-rose)";
        if (btnOptimize) btnOptimize.disabled = true;
    } finally {
        btnFetch.disabled = false;
        btnFetch.textContent = "Fetch Cell Records";
    }
}

/**
 * Renders cell towers on the map with deterministic alphabetic labels,
 * stable markers, and interactive coverage circles.
 */
function renderCellTowers(cells) {
    state.cellMarkersLayer.clearLayers();
    state.coverageCirclesLayer.clearLayers();
    state.edgesLayer.clearLayers();
    state.markersById = {};
    state.cellsById = {};
    state.coverageCirclesById = {};

    // Sort cells deterministically: North to South (lat descending), West to East (lon ascending), then tower_id
    cells.sort((a, b) => {
        if (b.latitude !== a.latitude) return b.latitude - a.latitude;
        if (a.longitude !== b.longitude) return a.longitude - b.longitude;
        return String(a.tower_id).localeCompare(String(b.tower_id));
    });

    // Assign stable alphabetic labels (A, B, C... Z, AA, AB...)
    cells.forEach((cell, idx) => {
        cell.label = getAlphaLabel(idx);
        cell.labelIndex = idx;
        state.cellsById[cell.tower_id] = cell;
    });

    // Group cells by physical mast location (rounded to 5 decimal places) for rosette dispersion
    const mastGroups = {};
    cells.forEach((cell) => {
        const key = `${cell.latitude.toFixed(5)},${cell.longitude.toFixed(5)}`;
        if (!mastGroups[key]) mastGroups[key] = [];
        mastGroups[key].push(cell);
    });

    cells.forEach((cell) => {
        // Calculate visual display coordinates (rosette dispersion for co-located sectors)
        const key = `${cell.latitude.toFixed(5)},${cell.longitude.toFixed(5)}`;
        const group = mastGroups[key];
        let displayLat = cell.latitude;
        let displayLon = cell.longitude;

        if (group.length > 1) {
            const idx = group.indexOf(cell);
            let ringRadiusMeters = 24;
            let ringCount = group.length;
            let angleIndex = idx;

            if (group.length > 8) {
                if (idx < 6) {
                    ringRadiusMeters = 20;
                    ringCount = 6;
                    angleIndex = idx;
                } else if (idx < 22) {
                    ringRadiusMeters = 42;
                    ringCount = Math.min(16, group.length - 6);
                    angleIndex = idx - 6;
                } else {
                    ringRadiusMeters = 64;
                    ringCount = group.length - 22;
                    angleIndex = idx - 22;
                }
            }

            const angle = (2 * Math.PI * angleIndex) / Math.max(1, ringCount);
            const dLat = (ringRadiusMeters * Math.cos(angle)) / 111139.0;
            const dLon = (ringRadiusMeters * Math.sin(angle)) / (111139.0 * Math.cos((cell.latitude * Math.PI) / 180));
            displayLat = cell.latitude + dLat;
            displayLon = cell.longitude + dLon;
        }

        cell._displayLat = displayLat;
        cell._displayLon = displayLon;

        // 1. Coverage circle (subtle faint outline before optimization; filled with frequency color once optimized)
        const isEstimated = Boolean(cell.is_range_estimated);
        const radiusM = Math.max(50, Number(cell.range_m) || 800);
        const coverageCircle = L.circle([cell.latitude, cell.longitude], {
            radius: radiusM,
            color: "#64748b",
            weight: 1.5,
            opacity: 0.35,
            fill: false,
            fillColor: "#3b82f6",
            fillOpacity: 0.0,
        });

        const estTag = isEstimated ? " (Estimated Default)" : "";
        coverageCircle.bindTooltip(`Coverage Area: Cell ${cell.label} (#${cell.cell_id}) — Radius: ${Math.round(radiusM)}m${estTag}`, { sticky: true });
        coverageCircle.on("click", () => openVertexInspector(cell.tower_id));

        state.coverageCirclesLayer.addLayer(coverageCircle);
        state.coverageCirclesById[cell.tower_id] = coverageCircle;

        // 2. High-legibility custom DivIcon marker with stable alphabetic label
        const markerIcon = L.divIcon({
            className: "tower-marker-div",
            html: `<div class="tower-marker-wrap" id="marker-wrap-${cell.tower_id}">
                     <div class="tower-marker-circle" id="marker-circle-${cell.tower_id}" title="Cell ${cell.label} (#${cell.cell_id})">
                       <span class="marker-label">${cell.label}</span>
                     </div>
                   </div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });

        const marker = L.marker([displayLat, displayLon], { icon: markerIcon });

        marker.on("click", () => {
            openVertexInspector(cell.tower_id);
        });

        // Informative popup card
        const popupContent = `
            <div class="tower-popup">
                <div class="tower-popup-header">
                    <span class="tower-popup-title">Cell ${cell.label} <small>(#${cell.cell_id})</small></span>
                    <span class="radio-badge">${cell.radio}</span>
                </div>
                <div class="tower-popup-details">
                    <span class="label">Assigned Freq:</span>
                    <span class="val" id="popup-freq-${cell.tower_id}" style="color: var(--text-muted);">Unassigned</span>
                    <span class="label">Latitude:</span>
                    <span class="val">${cell.latitude.toFixed(5)}°</span>
                    <span class="label">Longitude:</span>
                    <span class="val">${cell.longitude.toFixed(5)}°</span>
                    <span class="label">Coverage:</span>
                    <span class="val">${Math.round(radiusM)} m ${isEstimated ? '<small style="color:var(--accent-amber);">(Estimated)</small>' : ''}</span>
                    <span class="label">MCC / MNC:</span>
                    <span class="val">${cell.mcc ?? "—"} / ${cell.mnc ?? "—"}</span>
                    <span class="label">LAC:</span>
                    <span class="val">${cell.lac ?? "—"}</span>
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
 * Determines which algorithm result to display based on user selection.
 */
function getSelectedAlgoKey() {
    if (state.activeAlgorithm === "welsh_powell") return "welsh_powell";
    if (state.activeAlgorithm === "exact") {
        return state.optimizationResults?.exact?.coloring ? "exact" : "dsatur";
    }
    if (state.activeAlgorithm === "dsatur") return "dsatur";
    // "both": pick proven optimal or best algorithm
    const best = state.optimizationResults?.best_algorithm;
    if (best === "exact_dsatur_bnb" && state.optimizationResults?.exact?.coloring) return "exact";
    if (best === "welsh_powell") return "welsh_powell";
    return "dsatur";
}

/**
 * Closes the slide-over inspector drawer and restores highlights.
 */
function closeVertexInspector() {
    const inspector = document.getElementById("vertex-inspector");
    if (inspector) {
        inspector.classList.remove("open");
        inspector.setAttribute("aria-hidden", "true");
    }
    document.getElementById("analytics-dock")?.classList.remove("with-inspector");

    if (state.selectedTowerId) {
        const circleEl = document.getElementById(`marker-circle-${state.selectedTowerId}`);
        if (circleEl) circleEl.classList.remove("selected-marker");

        const covCircle = state.coverageCirclesById?.[state.selectedTowerId];
        if (covCircle) {
            const algoKey = getSelectedAlgoKey();
            const coloring = state.optimizationResults?.[algoKey]?.coloring;
            if (coloring && coloring[state.selectedTowerId] !== undefined) {
                const color = getFrequencyColor(coloring[state.selectedTowerId]);
                covCircle.setStyle({ fill: true, fillColor: color, fillOpacity: 0.18, color: color, opacity: 0.85, weight: 1.5 });
            } else {
                covCircle.setStyle({ fill: false, fillOpacity: 0.0, opacity: 0.35, color: "#64748b", weight: 1.5 });
            }
        }
        state.selectedTowerId = null;

        if (state.activeView === "graph") {
            renderGraphExplorer();
        }
    }
}

/**
 * Opens the slide-over inspector drawer for a specific cell tower.
 */
function openVertexInspector(towerId) {
    const inspector = document.getElementById("vertex-inspector");
    if (!inspector) return;

    const cell = state.cellsById[towerId];
    if (!cell) return;

    // Remove previous selection styling
    if (state.selectedTowerId && state.selectedTowerId !== towerId) {
        const prevCircle = document.getElementById(`marker-circle-${state.selectedTowerId}`);
        if (prevCircle) prevCircle.classList.remove("selected-marker");

        const prevCov = state.coverageCirclesById?.[state.selectedTowerId];
        if (prevCov) {
            const algoKey = getSelectedAlgoKey();
            const coloring = state.optimizationResults?.[algoKey]?.coloring;
            if (coloring && coloring[state.selectedTowerId] !== undefined) {
                const color = getFrequencyColor(coloring[state.selectedTowerId]);
                prevCov.setStyle({ fill: true, fillColor: color, fillOpacity: 0.18, color: color, opacity: 0.85, weight: 1.5 });
            } else {
                prevCov.setStyle({ fill: false, fillOpacity: 0.0, opacity: 0.35, color: "#64748b", weight: 1.5 });
            }
        }
    }

    state.selectedTowerId = towerId;

    // Highlight current marker on map
    const currCircle = document.getElementById(`marker-circle-${towerId}`);
    if (currCircle) currCircle.classList.add("selected-marker");

    // Highlight current coverage circle on map
    const currCov = state.coverageCirclesById?.[towerId];
    const algoKey = getSelectedAlgoKey();
    const coloring = state.optimizationResults?.[algoKey]?.coloring;
    if (currCov) {
        if (coloring && coloring[towerId] !== undefined) {
            const color = getFrequencyColor(coloring[towerId]);
            currCov.setStyle({ fill: true, fillColor: color, fillOpacity: 0.35, color: color, opacity: 1.0, weight: 3 });
        } else {
            currCov.setStyle({ fill: true, fillColor: "#38bdf8", fillOpacity: 0.15, color: "#38bdf8", opacity: 0.9, weight: 2.5 });
        }
    }

    // Header info with stable cell label
    document.getElementById("inspector-radio").textContent = cell.radio;
    document.getElementById("inspector-cell-id").textContent = `Cell ${cell.label} (#${cell.cell_id})`;

    // Assigned frequency badge (1-indexed channels: f1, f2, f3...)
    const freqBadge = document.getElementById("inspector-freq-badge");
    if (coloring && coloring[towerId] !== undefined) {
        const freq = coloring[towerId];
        const channelNum = freq + 1;
        const color = getFrequencyColor(freq);
        const algoName = algoKey === "welsh_powell" ? "Welsh-Powell" :
                         algoKey === "exact" ? "Exact Optimal" : "DSATUR";
        freqBadge.textContent = `Channel f${channelNum} (${algoName})`;
        freqBadge.style.color = color;
        freqBadge.style.borderColor = color;
        freqBadge.style.display = "inline-block";
    } else {
        freqBadge.textContent = "Unassigned (Run Optimization)";
        freqBadge.style.color = "var(--text-muted)";
        freqBadge.style.borderColor = "var(--border-subtle)";
    }

    // Geographic fields
    const isEstimated = Boolean(cell.is_range_estimated);
    document.getElementById("insp-coords").textContent = `${cell.latitude.toFixed(5)}°, ${cell.longitude.toFixed(5)}°`;
    document.getElementById("insp-range").innerHTML = `${Math.round(cell.range_m)} m ${isEstimated ? '<small style="color:var(--accent-amber); font-size:0.65rem;">(Estimated default)</small>' : ''}`;
    document.getElementById("insp-mcc-mnc").textContent = `${cell.mcc ?? "—"} / ${cell.mnc ?? "—"}`;
    document.getElementById("insp-lac").textContent = `${cell.lac ?? "—"}`;

    // Degree and neighbors
    const neighbors = [];
    state.interferenceEdges.forEach((edge) => {
        if (edge.source_id === towerId) {
            neighbors.push({ id: edge.target_id, dist: edge.distance_m });
        } else if (edge.target_id === towerId) {
            neighbors.push({ id: edge.source_id, dist: edge.distance_m });
        }
    });

    document.getElementById("insp-degree").textContent = neighbors.length;

    // Check validation / conflict status
    const inspValidation = document.getElementById("insp-validation");
    if (coloring) {
        const myFreq = coloring[towerId];
        const hasConflict = neighbors.some((n) => coloring[n.id] === myFreq);
        if (hasConflict) {
            inspValidation.innerHTML = '<span style="color: var(--accent-rose)">✖ Conflict Detected</span>';
        } else {
            inspValidation.innerHTML = '<span style="color: var(--accent-emerald)">✔ Valid (Zero Collisions)</span>';
        }
    } else {
        inspValidation.textContent = "Awaiting optimization";
    }

    // Render neighbor list with stable cell labels
    const listEl = document.getElementById("insp-neighbor-list");
    listEl.innerHTML = "";
    if (neighbors.length === 0) {
        listEl.innerHTML = '<li class="neighbor-empty">No overlapping interference neighbors (isolated node).</li>';
    } else {
        neighbors.forEach((n) => {
            const nCell = state.cellsById[n.id];
            const nFreq = coloring ? coloring[n.id] : null;
            const li = document.createElement("li");
            li.className = "neighbor-item";
            li.style.cursor = "pointer";
            const channelText = nFreq !== null && nFreq !== undefined ? `f${nFreq + 1}` : "—";
            const channelColor = nFreq !== null && nFreq !== undefined ? getFrequencyColor(nFreq) : "var(--text-muted)";
            li.innerHTML = `
                <span>Cell ${nCell?.label ?? '—'} <small>(#${nCell?.cell_id ?? n.id})</small> (${Math.round(n.dist)}m)</span>
                <span style="color: ${channelColor}; font-weight: 700; font-family: var(--font-mono);">
                    ${channelText}
                </span>
            `;
            li.addEventListener("click", () => openVertexInspector(n.id));
            listEl.appendChild(li);
        });
    }

    inspector.classList.add("open");
    inspector.setAttribute("aria-hidden", "false");
    document.getElementById("analytics-dock")?.classList.add("with-inspector");

    // If graph view is active, re-render to highlight selected node and edges
    if (state.activeView === "graph") {
        renderGraphExplorer();
    }
}

/**
 * Calls POST /api/optimize, displays metrics on scoreboard,
 * colors coverage circles on geographic map, and updates comparison strip.
 */
async function runFrequencyOptimization() {
    const btnOptimize = document.getElementById("btn-optimize");
    const statusMsg = document.getElementById("cells-status");

    btnOptimize.disabled = true;
    btnOptimize.textContent = "Optimizing...";
    statusMsg.textContent = "Running graph coloring heuristics & exact solver...";
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
            exact: data.exact,
            best_algorithm: data.best_algorithm,
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
        const ex = data.exact;

        const pillDsatur = document.getElementById("pill-dsatur");
        const pillWp = document.getElementById("pill-wp");
        const pillExact = document.getElementById("pill-exact");

        [pillDsatur, pillWp, pillExact].forEach((p) => p?.classList.remove("best-algo-pill"));

        if (ds) {
            const isValid = ds.validation?.is_valid ?? ds.is_valid;
            document.getElementById("res-dsatur-colors").textContent = `${ds.color_count} colors (${ds.runtime_ms.toFixed(2)} ms)`;
            document.getElementById("res-dsatur-valid").innerHTML = isValid
                ? '<span style="color: var(--accent-emerald)">✔ Valid</span>'
                : '<span style="color: var(--accent-rose)">✖ Collision</span>';
        }

        if (wp) {
            const isValid = wp.validation?.is_valid ?? wp.is_valid;
            document.getElementById("res-wp-colors").textContent = `${wp.color_count} colors (${wp.runtime_ms.toFixed(2)} ms)`;
            document.getElementById("res-wp-valid").innerHTML = isValid
                ? '<span style="color: var(--accent-emerald)">✔ Valid</span>'
                : '<span style="color: var(--accent-rose)">✖ Collision</span>';
        }

        if (ex) {
            const elExColors = document.getElementById("res-exact-colors");
            const elExValid = document.getElementById("res-exact-valid");
            if (ex.proven_optimal) {
                if (elExColors) elExColors.textContent = `${ex.color_count} colors (${ex.runtime_ms.toFixed(2)} ms)`;
                if (elExValid) elExValid.innerHTML = `<span style="color: var(--accent-emerald)">✔ Optimal (χ=${ex.color_count})</span>`;
            } else if (ex.status === "skipped_size_limit") {
                if (elExColors) elExColors.textContent = "N > 25 (Skipped)";
                if (elExValid) elExValid.innerHTML = `<span style="color: var(--text-muted)">Heuristic Only</span>`;
            } else if (ex.status === "timeout") {
                if (elExColors) elExColors.textContent = `${ex.color_count} colors`;
                if (elExValid) elExValid.innerHTML = `<span style="color: var(--accent-amber)">⏱ Timeout</span>`;
            } else {
                if (elExColors) elExColors.textContent = "Unavailable";
                if (elExValid) elExValid.innerHTML = `<span style="color: var(--text-muted)">—</span>`;
            }
        }

        // Highlight best algorithm pill
        const best = data.best_algorithm;
        if (best === "dsatur") pillDsatur?.classList.add("best-algo-pill");
        else if (best === "welsh_powell") pillWp?.classList.add("best-algo-pill");
        else if (best === "exact_dsatur_bnb") pillExact?.classList.add("best-algo-pill");

        // 3. Keep edge lines OFF the geographic map (clear edges layer)
        renderInterferenceEdges(state.interferenceEdges);

        // 4. Color coverage circles & cell markers according to the active algorithm
        applyActiveColoring();

        // 5. If graph view is active, update canvas
        if (state.activeView === "graph") {
            renderGraphExplorer();
        }

        let summaryText = `Optimization complete! DSATUR: ${ds?.color_count} colors, Welsh-Powell: ${wp?.color_count} colors.`;
        if (ex?.proven_optimal) {
            summaryText += ` Proven minimum chromatic number χ(G) = ${ex.color_count}.`;
        }
        statusMsg.textContent = summaryText;
        statusMsg.style.color = "var(--accent-emerald)";
    } catch (err) {
        console.error("Optimization failed:", err);
        statusMsg.textContent = `Error: ${err.message}`;
        statusMsg.style.color = "var(--accent-rose)";
    } finally {
        btnOptimize.disabled = false;
        btnOptimize.textContent = "Optimize Frequencies";
    }
}

/**
 * Draws polyline edges between towers only for internal state/topology.
 * Guaranteed: NO edge lines are added to state.map.
 */
function renderInterferenceEdges(edges) {
    // Phase 2: As required by master prompt Section 4, the main geographic map MUST NOT display
    // lines connecting two towers or cell records. Edge interference is inspected via
    // the dedicated Graph Topology Canvas and the Vertex Inspector panel.
    state.edgesLayer.clearLayers();
    if (state.map.hasLayer(state.edgesLayer)) {
        state.map.removeLayer(state.edgesLayer);
    }
}

/**
 * Updates coverage circle fill colors and marker badges to reflect the chosen algorithm's coloring.
 */
function applyActiveColoring() {
    if (!state.optimizationResults) return;

    const algoKey = getSelectedAlgoKey();
    const algoResult = state.optimizationResults[algoKey];
    if (!algoResult || !algoResult.coloring) return;

    const coloring = algoResult.coloring;
    const maxFreq = algoResult.color_count || 1;

    // 1. Color each cell's coverage circle & marker on the map
    Object.entries(coloring).forEach(([towerId, freq]) => {
        const cell = state.cellsById[towerId];
        if (!cell) return;

        const channelNum = freq + 1;
        const color = getFrequencyColor(freq);

        // Recolor coverage circle on geographic map
        const covCircle = state.coverageCirclesById[towerId];
        if (covCircle) {
            covCircle.setStyle({
                fill: true,
                fillColor: color,
                fillOpacity: 0.18,
                color: color,
                weight: 1.5,
                opacity: 0.85,
            });
        }

        // Recolor marker chip with stable label & channel badge
        const circleEl = document.getElementById(`marker-circle-${towerId}`);
        if (circleEl) {
            circleEl.style.backgroundColor = color;
            circleEl.style.borderColor = "#ffffff";
            circleEl.innerHTML = `<span class="marker-label">${cell.label}</span><span class="marker-freq-sub">f${channelNum}</span>`;
            circleEl.title = `Cell ${cell.label} (#${cell.cell_id}) — Channel f${channelNum}`;
        }

        // Update popup card content
        const marker = state.markersById[towerId];
        if (marker && marker.getPopup()) {
            const algoName = algoKey === "welsh_powell" ? "Welsh-Powell" :
                             algoKey === "exact" ? "Exact Optimal" : "DSATUR";
            const isEstimated = Boolean(cell.is_range_estimated);
            const radiusM = Math.max(50, Number(cell.range_m) || 800);
            const popupContent = `
                <div class="tower-popup">
                    <div class="tower-popup-header">
                        <span class="tower-popup-title">Cell ${cell.label} <small>(#${cell.cell_id})</small></span>
                        <span class="radio-badge">${cell.radio}</span>
                    </div>
                    <div class="tower-popup-details">
                        <span class="label">Assigned Freq:</span>
                        <span class="val" style="color: ${color}; font-weight: 700;">Channel f${channelNum} (${algoName})</span>
                        <span class="label">Latitude:</span>
                        <span class="val">${cell.latitude.toFixed(5)}°</span>
                        <span class="label">Longitude:</span>
                        <span class="val">${cell.longitude.toFixed(5)}°</span>
                        <span class="label">Coverage:</span>
                        <span class="val">${Math.round(radiusM)} m ${isEstimated ? '<small style="color:var(--accent-amber);">(Estimated)</small>' : ''}</span>
                        <span class="label">MCC / MNC:</span>
                        <span class="val">${cell.mcc ?? "—"} / ${cell.mnc ?? "—"}</span>
                        <span class="label">LAC:</span>
                        <span class="val">${cell.lac ?? "—"}</span>
                    </div>
                </div>
            `;
            marker.setPopupContent(popupContent);
        }
    });

    // 2. Render color palette legend
    renderLegend(maxFreq, algoKey);

    // 3. Update inspector if open
    if (state.selectedTowerId && coloring[state.selectedTowerId] !== undefined) {
        const freq = coloring[state.selectedTowerId];
        const channelNum = freq + 1;
        const color = getFrequencyColor(freq);
        const freqBadge = document.getElementById("inspector-freq-badge");
        if (freqBadge) {
            const algoName = algoKey === "welsh_powell" ? "Welsh-Powell" :
                             algoKey === "exact" ? "Exact Optimal" : "DSATUR";
            freqBadge.textContent = `Channel f${channelNum} (${algoName})`;
            freqBadge.style.color = color;
            freqBadge.style.borderColor = color;
        }
    }
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
        const color = getFrequencyColor(f - 1);
        const chip = document.createElement("div");
        chip.className = "legend-chip";
        chip.dataset.channel = f;
        chip.innerHTML = `
            <span class="legend-color-dot" style="background-color: ${color};"></span>
            <span>Freq ${f} (f${f})</span>
        `;
        chip.addEventListener("click", () => isolateFrequency(f));
        legendItems.appendChild(chip);
    }

    legendContainer.style.display = "flex";
}

/**
 * Interactive frequency channel isolation:
 * Highlights towers and coverage circles assigned to channel `channelNum` and dims others.
 */
function isolateFrequency(channelNum) {
    const algoKey = getSelectedAlgoKey();
    const coloring = state.optimizationResults?.[algoKey]?.coloring;
    if (!coloring) return;

    const chips = document.querySelectorAll(".legend-chip");
    if (state.isolatedFrequency === channelNum) {
        // Toggle off isolation
        state.isolatedFrequency = null;
        chips.forEach((c) => c.classList.remove("active-isolate"));

        Object.entries(coloring).forEach(([towerId, freq]) => {
            const circleEl = document.getElementById(`marker-circle-${towerId}`);
            if (circleEl) circleEl.classList.remove("dimmed-marker");

            const covCircle = state.coverageCirclesById[towerId];
            if (covCircle) {
                const color = getFrequencyColor(freq);
                covCircle.setStyle({ fill: true, fillColor: color, fillOpacity: 0.18, color: color, opacity: 0.85, weight: 1.5 });
            }
        });
    } else {
        // Isolate specific channel
        state.isolatedFrequency = channelNum;
        chips.forEach((c) => {
            if (Number(c.dataset.channel) === channelNum) {
                c.classList.add("active-isolate");
            } else {
                c.classList.remove("active-isolate");
            }
        });

        Object.entries(coloring).forEach(([towerId, freq]) => {
            const isMatch = (freq + 1 === channelNum);
            const circleEl = document.getElementById(`marker-circle-${towerId}`);
            if (circleEl) {
                if (isMatch) {
                    circleEl.classList.remove("dimmed-marker");
                } else {
                    circleEl.classList.add("dimmed-marker");
                }
            }

            const covCircle = state.coverageCirclesById[towerId];
            if (covCircle) {
                const color = getFrequencyColor(freq);
                if (isMatch) {
                    covCircle.setStyle({ fill: true, fillColor: color, fillOpacity: 0.32, color: color, opacity: 1.0, weight: 2.5 });
                } else {
                    covCircle.setStyle({ fill: true, fillColor: color, fillOpacity: 0.03, color: color, opacity: 0.15, weight: 0.5 });
                }
            }
        });
    }

    if (state.activeView === "graph") {
        renderGraphExplorer();
    }
}

/**
 * Resets optimization scoreboard metrics, exact solver indicators, and restores circles.
 */
function resetOptimizationScoreboard() {
    const elEdges = document.getElementById("metric-edges");
    const elDegree = document.getElementById("metric-degree");
    const elDensity = document.getElementById("metric-density");
    const elWpColors = document.getElementById("res-wp-colors");
    const elWpValid = document.getElementById("res-wp-valid");
    const elDsaturColors = document.getElementById("res-dsatur-colors");
    const elDsaturValid = document.getElementById("res-dsatur-valid");
    const elExactColors = document.getElementById("res-exact-colors");
    const elExactValid = document.getElementById("res-exact-valid");
    const legendContainer = document.getElementById("legend-container");

    if (elEdges) elEdges.textContent = "—";
    if (elDegree) elDegree.textContent = "—";
    if (elDensity) elDensity.textContent = "—";
    if (elWpColors) elWpColors.textContent = "—";
    if (elWpValid) elWpValid.textContent = "—";
    if (elDsaturColors) elDsaturColors.textContent = "—";
    if (elDsaturValid) elDsaturValid.textContent = "—";
    if (elExactColors) elExactColors.textContent = "—";
    if (elExactValid) elExactValid.textContent = "—";
    if (legendContainer) legendContainer.style.display = "none";

    ["pill-dsatur", "pill-wp", "pill-exact"].forEach((id) => {
        document.getElementById(id)?.classList.remove("best-algo-pill");
    });

    // Reset coverage circles and markers
    if (state.coverageCirclesById) {
        Object.values(state.coverageCirclesById).forEach((circle) => {
            circle.setStyle({
                fill: false,
                fillColor: "#3b82f6",
                fillOpacity: 0.0,
                color: "#64748b",
                weight: 1.5,
                opacity: 0.35,
            });
        });
    }

    if (state.cells) {
        state.cells.forEach((cell) => {
            const circleEl = document.getElementById(`marker-circle-${cell.tower_id}`);
            if (circleEl) {
                circleEl.style.backgroundColor = "var(--bg-surface)";
                circleEl.style.borderColor = "#ffffff";
                circleEl.innerHTML = `<span class="marker-label">${cell.label}</span>`;
                circleEl.title = `Cell ${cell.label} (#${cell.cell_id})`;
            }
        });
    }
}

/**
 * Renders the Topology Graph Explorer view on HTML5 Canvas.
 * Supports Retina HiDPI, interactive selection, and clear channel labels.
 */
function renderGraphExplorer() {
    const canvas = document.getElementById("graph-canvas");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;

    ctx.clearRect(0, 0, width, height);

    if (state.cells.length === 0) {
        ctx.fillStyle = "rgba(148, 163, 184, 0.4)";
        ctx.font = "14px Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("No cell records loaded yet. Click 'Fetch Cell Records' on the map to build graph.", width / 2, height / 2);
        return;
    }

    const algoKey = getSelectedAlgoKey();
    const coloring = state.optimizationResults?.[algoKey]?.coloring || {};

    const nodeCoords = {};
    const total = state.cells.length;
    const centerX = width / 2;
    const centerY = height / 2;

    if (total <= 36) {
        const radius = Math.min(width, height) * 0.38;
        state.cells.forEach((cell, i) => {
            const angle = (i * 2 * Math.PI) / total - Math.PI / 2;
            nodeCoords[cell.tower_id] = {
                x: centerX + radius * Math.cos(angle),
                y: centerY + radius * Math.sin(angle),
                r: 14,
                cell: cell,
            };
        });
    } else {
        const innerCount = Math.min(12, Math.floor(total * 0.25));
        const midCount = Math.min(36, Math.floor(total * 0.45));
        const outerCount = total - innerCount - midCount;

        const r1 = Math.min(width, height) * 0.16;
        const r2 = Math.min(width, height) * 0.28;
        const r3 = Math.min(width, height) * 0.40;

        state.cells.forEach((cell, i) => {
            let r = r1, ringIdx = i, ringTotal = innerCount;
            if (i >= innerCount && i < innerCount + midCount) {
                r = r2;
                ringIdx = i - innerCount;
                ringTotal = midCount;
            } else if (i >= innerCount + midCount) {
                r = r3;
                ringIdx = i - innerCount - midCount;
                ringTotal = outerCount;
            }
            const angle = (ringIdx * 2 * Math.PI) / Math.max(1, ringTotal) - Math.PI / 2;
            nodeCoords[cell.tower_id] = {
                x: centerX + r * Math.cos(angle),
                y: centerY + r * Math.sin(angle),
                r: total > 80 ? 8 : 11,
                cell: cell,
            };
        });
    }

    state.graphNodePositions = nodeCoords;

    // 1. Draw interference edges
    const selectedId = state.selectedTowerId;
    state.interferenceEdges.forEach((edge) => {
        const p1 = nodeCoords[edge.source_id];
        const p2 = nodeCoords[edge.target_id];
        if (!p1 || !p2) return;

        const isIncident = selectedId && (edge.source_id === selectedId || edge.target_id === selectedId);

        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);

        if (isIncident) {
            ctx.lineWidth = 2.5;
            ctx.strokeStyle = "rgba(245, 158, 11, 0.95)";
        } else if (selectedId) {
            ctx.lineWidth = 0.5;
            ctx.strokeStyle = "rgba(239, 68, 68, 0.08)";
        } else {
            ctx.lineWidth = 1;
            ctx.strokeStyle = "rgba(239, 68, 68, 0.22)";
        }
        ctx.stroke();
    });

    // 2. Draw vertices
    state.cells.forEach((cell) => {
        const pos = nodeCoords[cell.tower_id];
        if (!pos) return;

        const freq = coloring[cell.tower_id];
        const channelNum = freq !== undefined ? freq + 1 : null;
        const color = channelNum !== null ? getFrequencyColor(freq) : "#38bdf8";

        const isSelected = selectedId === cell.tower_id;
        const isDimmed = state.isolatedFrequency && channelNum !== state.isolatedFrequency;

        ctx.save();
        if (isDimmed) {
            ctx.globalAlpha = 0.2;
        }

        // Selected halo pulse ring
        if (isSelected) {
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, pos.r + 6, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(245, 158, 11, 0.35)";
            ctx.fill();
        }

        // Main node circle
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, pos.r, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.lineWidth = isSelected ? 3 : 1.5;
        ctx.strokeStyle = isSelected ? "#f59e0b" : "#ffffff";
        ctx.stroke();

        // Node text label: stable alphabetic label
        if (pos.r >= 9) {
            ctx.fillStyle = "#ffffff";
            ctx.font = `bold ${Math.round(pos.r * 0.72)}px 'JetBrains Mono', monospace`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(cell.label, pos.x, pos.y);
        }

        ctx.restore();
    });
}

/**
 * Initializes hover tooltips and click selection on the Graph Topology Canvas.
 */
function initGraphCanvasInteractions() {
    const canvas = document.getElementById("graph-canvas");
    const tooltip = document.getElementById("graph-tooltip");
    if (!canvas || !tooltip) return;

    function getNodeAt(x, y) {
        if (!state.graphNodePositions) return null;
        for (const [id, pos] of Object.entries(state.graphNodePositions)) {
            const dx = x - pos.x;
            const dy = y - pos.y;
            if (dx * dx + dy * dy <= (pos.r + 5) * (pos.r + 5)) {
                return pos;
            }
        }
        return null;
    }

    canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const node = getNodeAt(mouseX, mouseY);
        if (node) {
            canvas.style.cursor = "pointer";
            const algoKey = getSelectedAlgoKey();
            const coloring = state.optimizationResults?.[algoKey]?.coloring || {};
            const freq = coloring[node.cell.tower_id];
            const channelText = freq !== undefined ? `Channel f${freq + 1}` : "Unassigned";

            tooltip.style.display = "flex";
            tooltip.style.left = `${mouseX + 15}px`;
            tooltip.style.top = `${mouseY + 15}px`;
            tooltip.innerHTML = `
                <div style="font-weight: 700; color: var(--text-primary)">Cell ${node.cell.label} <small>(#${node.cell.cell_id})</small> <span style="font-size: 0.65rem; color: var(--accent-blue)">${node.cell.radio}</span></div>
                <div style="font-size: 0.68rem; color: var(--accent-emerald)">${channelText}</div>
                <div style="font-size: 0.64rem; color: var(--text-muted)">Range: ${Math.round(node.cell.range_m)}m ${node.cell.is_range_estimated ? '(Est)' : ''}</div>
            `;
        } else {
            canvas.style.cursor = "default";
            tooltip.style.display = "none";
        }
    });

    canvas.addEventListener("mouseleave", () => {
        tooltip.style.display = "none";
    });

    canvas.addEventListener("click", (e) => {
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const node = getNodeAt(mouseX, mouseY);
        if (node) {
            openVertexInspector(node.cell.tower_id);
        }
    });
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
