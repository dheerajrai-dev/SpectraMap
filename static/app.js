/**
 * app.js — SpectraMap frontend logic
 *
 * Handles:
 * 1. Leaflet map initialization with OpenStreetMap tiles.
 * 2. Backend health check (/api/status).
 * 3. Area selection (dragging center marker, map click, geolocation, radius slider).
 * 4. Fetching cell tower records (/api/cells) and rendering interactive markers.
 * 5. Optimization runner (/api/optimize) and algorithm scoreboard (Step 7).
 */

// Global state
const state = {
    map: null,
    centerMarker: null,
    searchCircle: null,
    currentCenter: { lat: 28.6000, lon: 77.2000 }, // Default: South Delhi (has rich cell data)
    radiusMetres: 700,
    cells: [],
    markersById: {},
    interferenceEdges: [],
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
 * Hooks up UI event listeners (slider, buttons, checkboxes).
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

    // "Use My Current Location" button (HTML5 Geolocation)
    const btnLocate = document.getElementById("btn-locate");
    if (btnLocate) {
        btnLocate.addEventListener("click", handleGeolocation);
    }

    // "Fetch Nearby Towers" button
    const btnFetch = document.getElementById("btn-fetch");
    if (btnFetch) {
        btnFetch.addEventListener("click", fetchNearbyCells);
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
        statusMsg.textContent = "Locating your position...";
        statusMsg.style.color = "var(--text-secondary)";
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const { latitude, longitude } = pos.coords;
            setNewCenter(latitude, longitude);
            state.map.setView([latitude, longitude], 15);
            if (statusMsg) {
                statusMsg.textContent = "Location updated! Click 'Fetch Nearby Towers'.";
                statusMsg.style.color = "var(--accent-success)";
            }
        },
        (err) => {
            console.warn("Geolocation failed:", err.message);
            if (statusMsg) {
                statusMsg.textContent = "Could not get location. Using manual map point.";
                statusMsg.style.color = "var(--accent-warning)";
            }
        },
        { timeout: 10000 }
    );
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
    statusMsg.textContent = "Querying OpenCellID data...";
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
            statusMsg.textContent = "No cell towers found within this search radius. Try increasing the radius or choosing another area.";
            statusMsg.style.color = "var(--accent-warning)";
            if (btnOptimize) btnOptimize.disabled = true;
        } else {
            let info = `Found ${state.cells.length} towers within ${state.radiusMetres}m.`;
            if (data.metadata?.is_partial) {
                info += " (Warning: Max 50 records returned for this area).";
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

    cells.forEach((cell) => {
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
        state.markersById[cell.cell_id] = marker;
    });
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
