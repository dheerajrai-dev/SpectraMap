# SpectraMap --- Frontend Specification

**Version:** 2.0\
**UI direction:** Polished, map-first, explanatory, responsive\
**Frontend stack:** HTML, CSS, vanilla JavaScript, Leaflet

## 1. Frontend objective

The interface must help a first-time user understand the complete
relationship between geographic towers and graph coloring. The UI is not
just a map with colored markers. It should expose the graph topology,
algorithm results, and correctness evidence while remaining visually
focused.

Preserve the existing visual identity and working components where
practical. Improve information hierarchy and interactions before
considering a rewrite.

## 2. Information architecture

Use a single main workspace with these primary areas:

1.  **Header:** SpectraMap name, short purpose statement, data/source
    status, help/assumptions access.
2.  **Configuration panel:** area selection or supported bounds, tower
    selection, radius/model assumptions, graph rebuild action.
3.  **Main visualization:** Map and Graph views, sharing the same
    underlying graph.
4.  **Optimization controls:** DSatur, Welsh--Powell, and Compare Both.
5.  **Results panel:** graph metrics, algorithm outputs, independent
    validation.
6.  **Tower inspector:** details for a selected tower, its degree,
    assigned color, and neighbors.
7.  **Explanation/limitations:** how edges are created, what a color
    means, and what the prototype cannot claim.

Do not add unrelated pages or product features.

## 3. Main workspace layout

### Desktop

-   Compact top bar.
-   Left-side configuration/algorithm controls.
-   Center visualization taking the largest share of the viewport.
-   Right-side results/tower inspector, which may use tabs or a
    collapsible panel.
-   Metrics should be visible without scrolling where practical.
-   Avoid crowding the map with every control at once.

### Tablet

-   Keep the map/graph visualization dominant.
-   Move configuration and results into collapsible panels or tabs.
-   Maintain obvious access to algorithm controls.

### Mobile

-   Stack the layout vertically.
-   Use tabs for Map, Graph, Results, and Details if needed.
-   Keep primary actions accessible and avoid horizontal overflow.
-   Do not shrink desktop controls until they become unusable.

## 4. Required screens/states

### State A: Initial/empty

-   Explain the problem in one or two concise sentences.
-   Provide the supported way to select/load an area.
-   Show data-source and model-assumption information.
-   Do not show fake live metrics or imply data is already loaded.

### State B: Towers loaded

-   Display towers on the Leaflet map.
-   Show the selected area and number of valid towers.
-   Explain which coverage values are observed in the data and which are
    assumptions.
-   Allow the user to build the graph.

### State C: Graph built

-   Display graph edges using the graph returned by the backend.
-   Provide Map and Graph tabs or a clear toggle.
-   Show vertex and edge counts.
-   Selecting a tower highlights it and its neighbors in both views.
-   Show an edge explanation such as "modeled coverage circles overlap"
    with measured distance and threshold when available.

### State D: Optimized

-   Color towers/nodes according to the returned assignments.
-   Show selected algorithm, number of colors used, runtime, and
    validator result.
-   Use a legend with frequency/color index labels.
-   Provide controls to run the other algorithm or compare both.

### State E: Comparison

-   Display DSatur and Welsh--Powell side by side.
-   Compare color count, measured algorithm runtime, and conflict count.
-   Ensure both results use the same graph and configuration.
-   Use neutral language if one algorithm uses fewer colors; do not
    imply it is universally superior.
-   Explain that fewer colors in this graph is a better heuristic
    result, not proof of the chromatic number.

### State F: Loading/error/empty result

-   Use a visible loading indicator during data loading, graph building,
    and optimization.
-   Disable duplicate submissions while an operation is running.
-   Display a useful recovery action on errors.
-   Distinguish "no towers found," "graph has no edges," "no result
    yet," and "validation failed."

## 5. Visualization requirements

### 5.1 Geographic map

-   Use Leaflet and the existing map provider/configuration.
-   Markers use stable tower IDs.
-   Show coverage circles only when a valid radius is available.
-   Use distinct visual states: uncolored, assigned, selected, neighbor,
    and conflict.
-   Clicking a marker selects the corresponding tower in the inspector
    and graph view.
-   Render only graph edges returned by the backend. Do not draw lines
    between every tower.
-   Provide a legend and a way to toggle edge visibility when the map
    becomes cluttered.
-   Avoid claiming the circles are actual radio propagation boundaries;
    label them as modeled/estimated coverage.

### 5.2 Graph explorer

-   Show one node per selected valid tower and one edge per modeled
    conflict.
-   Use a simple graph layout suitable for the supported graph size; do
    not add an advanced graph-layout dependency unless one already
    exists.
-   Selected node and its immediate neighbors must be visually
    emphasized.
-   The graph must represent exactly the same vertices and edges as the
    map/API response.
-   Provide node labels or hover details without making large graphs
    unreadable.
-   If graph size exceeds the UI's practical limit, show a clear
    limit/filter message rather than freezing the browser.

### 5.3 Color/frequency encoding

-   Use a consistent palette across map, graph, legend, and result
    table.
-   Do not rely on color alone: include color index, labels, or symbols.
-   Colors are abstract frequency labels, not actual licensed
    radio-channel numbers unless explicitly mapped to real channel data.
-   A conflict should be highlighted distinctly and accompanied by text.

## 6. Metrics panel

Show only values computed from current data:

-   Tower count / vertex count.
-   Interference edge count.
-   Number of colors used by the selected algorithm.
-   Conflict count and validation status.
-   Algorithm runtime in milliseconds.
-   Optional graph density and maximum/average degree, only if
    calculated correctly.

Do not call color count "minimum frequencies" unless an exact solver
proves optimality. Prefer "colors used" or "modeled frequency groups."

## 7. Interaction behavior

### Build graph

1.  Validate configuration.
2.  Show loading state.
3.  Request graph construction.
4.  Update map edges and graph from the same response.
5.  Clear stale assignments or mark them as out of date.
6.  Update vertex/edge metrics.

### Run one algorithm

1.  Require a current graph.
2.  Show the selected algorithm and loading state.
3.  Submit the algorithm request.
4.  Render assignments.
5.  Show independent validation result and measured runtime.

### Compare both

1.  Require a current graph.
2.  Run both algorithms against the same graph/configuration.
3.  Show separate results and comparable metrics.
4.  Allow users to switch the active map/graph coloring to either
    result.

### Select a tower

-   Highlight the selected tower/node.
-   Highlight adjacent vertices and edges.
-   Show tower ID, coordinates, range, degree, assigned color, and
    neighbor list when available.
-   For each neighbor, explain the edge criterion with actual data
    returned by the backend.

### Change model settings

-   Clearly show which values are assumptions or overrides.
-   Mark existing graph/results as stale.
-   Rebuild and recalculate on user action or documented
    auto-recalculation.
-   Do not leave old coloring presented as if it matches the new graph.

## 8. Visual design principles

-   Map-first layout with a clear hierarchy.
-   Modern, restrained visual design; retain glassmorphism only where it
    improves legibility and does not obscure map content.
-   Strong typography, consistent spacing, clear panel boundaries, and
    concise copy.
-   Subtle transitions for loading and assignment changes; avoid
    distracting animation.
-   Good contrast and visible keyboard focus.
-   Clear units (metres, milliseconds) and clear distinctions between
    measured values and assumptions.
-   Empty states should teach the next action.
-   Use the same terminology throughout: tower, vertex, modeled
    interference edge, color/frequency assignment, validation conflict.

## 9. Accessibility and resilience

-   All actions are keyboard-accessible.
-   Buttons have meaningful labels.
-   Color is not the sole carrier of information.
-   Loading and validation updates are announced or otherwise clearly
    visible.
-   The layout works at common desktop, tablet, and mobile widths.
-   API failures, missing coordinates, missing radii, and empty graphs
    have dedicated messages.
-   Avoid uncaught browser errors and unhandled rejected requests.

## 10. Frontend implementation boundaries

-   Use HTML, CSS, vanilla JavaScript, and Leaflet.
-   Reuse the existing structure and dependencies where possible.
-   Do not introduce React, TypeScript, a component framework, a
    charting library, or a graph visualization library unless it is
    already an established dependency and changing it is clearly
    unnecessary.
-   Do not implement graph algorithms separately in the browser if the
    backend is the source of truth.
-   Keep API calls in a small service/helper layer and UI state updates
    in understandable functions.
-   Avoid giant single-file scripts if the repository already has a
    sensible modular structure.

## 11. Frontend acceptance checklist

-   [ ] The first screen explains the project and how to start.
-   [ ] Tower markers are loaded from actual response data.
-   [ ] Graph edges are selective and match the backend graph.
-   [ ] Map and graph views use identical stable IDs, vertices, and
    edges.
-   [ ] Selecting a tower highlights its neighbors in both views.
-   [ ] DSatur and Welsh--Powell can be run and compared.
-   [ ] Metrics are based on actual responses, not hardcoded mock data.
-   [ ] The independent validation result is visible.
-   [ ] Assumptions and limitations are accessible.
-   [ ] Loading, empty, invalid, and error states are handled.
-   [ ] The application is usable on desktop and mobile.
-   [ ] Existing working behavior has not been broken by visual changes.
