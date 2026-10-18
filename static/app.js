/**
 * app.js — SpectraMap frontend logic
 *
 * Intermediate developer friendly:
 * 1. Initializes the Leaflet map with OpenStreetMap tiles.
 * 2. Checks backend status (/api/status).
 * 3. Handles radius slider updates.
 */

// Global state
const state = {
    map: null,
    centerMarker: null,
    searchCircle: null,
    currentCenter: { lat: 28.6139, lon: 77.2090 }, // Default: New Delhi
    radiusMetres: 1000,
    cells: [],
    interferenceEdges: [],
    cellMarkersLayer: null,
    edgesLayer: null,
};

// Distinct color palette for up to 10 frequencies (Hex codes)
const FREQUENCY_COLORS = [
    "#3b82f6", // Blue
    "#10b981", // Emerald Green
    "#f59e0b", // Amber
    "#ef4444", // Red
    "#8b5cf6", // Purple
    "#ec4899", // Pink
    "#06b6d4", // Cyan
    "#84cc16", // Lime
    "#f97316", // Orange
    "#64748b", // Slate
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
    state.cellMarkersLayer = L.layerGroup().addTo(state.map);
    state.edgesLayer = L.layerGroup().addTo(state.map);

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

    if (statusMsg) statusMsg.textContent = "Locating your position...";

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const { latitude, longitude } = pos.coords;
            setNewCenter(latitude, longitude);
            state.map.setView([latitude, longitude], 15);
            if (statusMsg) statusMsg.textContent = "Location updated! Click 'Fetch Nearby Towers'.";
        },
        (err) => {
            console.warn("Geolocation failed:", err.message);
            if (statusMsg) statusMsg.textContent = "Could not get location. Using manual map point.";
        },
        { timeout: 10000 }
    );
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
