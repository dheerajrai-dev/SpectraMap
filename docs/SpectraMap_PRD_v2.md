# SpectraMap --- Product Requirements Document (PRD)

**Version:** 2.0\
**Status:** Revised implementation baseline\
**Project:** SpectraMap --- Spatial Graph Coloring for Cellular
Frequency Optimization

## 1. Executive summary

SpectraMap is an educational, interactive web application that
demonstrates how graph theory can model simplified cellular-frequency
allocation. It uses geographic cell-tower records to construct an
interference graph, then applies the DSatur and Welsh--Powell
vertex-coloring heuristics to assign distinct modeled frequencies to
adjacent vertices.

The product must make the complete reasoning visible: geographic tower
selection → modeled coverage and adjacency → graph topology → graph
coloring → independent validation → comparison and explanation.

SpectraMap is a prototype and educational demonstration. It is not a
carrier-grade radio-frequency planning system, does not access live
operator telemetry, and cannot guarantee the elimination of physical
radio interference.

## 2. Problem statement

When nearby cell towers have overlapping modeled coverage, assigning the
same frequency to both may represent a potential co-channel interference
conflict. Frequency resources are limited, so a planner would prefer to
reuse a frequency where the model does not impose a conflict.

The project translates this simplified problem into graph coloring:

-   Each selected tower is a vertex.
-   An undirected edge joins two towers when the documented
    coverage-overlap rule marks them as conflicting.
-   Each color represents a modeled frequency assignment.
-   Adjacent vertices must receive different colors.
-   The number of colors used is a practical result of a coloring
    algorithm; it is not automatically the graph's proven minimum
    chromatic number.

## 3. Product goals

1.  Demonstrate the practical application of graph theory and vertex
    coloring.
2.  Build a selective, explainable graph rather than connecting every
    tower to every other tower.
3.  Let users explore a geographic region and inspect tower
    relationships.
4.  Compare DSatur and Welsh--Powell on the same graph.
5.  Independently validate that every modeled interference edge has
    differently colored endpoints.
6.  Present the process in a polished, responsive, map-first interface
    that a student can explain in a demonstration or viva.
7.  Keep the implementation small enough to finish and maintain as an
    individual academic project.

## 4. Non-goals

The MVP will not implement:

-   Carrier-grade RF propagation, radio planning, or guaranteed physical
    interference elimination.
-   Access to live mobile-operator telemetry or network control.
-   Claims that DSatur or Welsh--Powell always finds the chromatic
    number.
-   Artificially capping each tower to a fixed number of neighbors.
-   Voronoi diagrams, Delaunay triangulation, terrain/elevation
    analysis, directional antennas, or propagation simulation.
-   Microservices, a database, authentication, accounts, AI chat, or a
    complex deployment platform.
-   Unrequested frameworks or a frontend rewrite.
-   Continuous real-time network monitoring. User-triggered
    recalculation is sufficient.

## 5. Target users

-   Students and instructors assessing discrete-mathematics
    applications.
-   Demonstration users exploring how graph structure changes frequency
    assignments.
-   Recruiters or reviewers evaluating a compact data-driven algorithmic
    application.

## 6. Primary user journey

1.  Open SpectraMap and see a clear explanation of the modeled problem.
2.  Select a supported location/region and a manageable set of tower
    records.
3.  Load towers onto a geographic map.
4.  Choose or adjust the modeled coverage-radius setting, where
    supported.
5.  Build the interference graph using the documented edge rule.
6.  Inspect the graph and select a tower to see its neighbors and why
    each edge exists.
7.  Run DSatur or Welsh--Powell, or compare both on the same graph.
8.  View assignments on the map and graph, plus metrics and independent
    validation.
9.  Change a configuration setting and recalculate to observe how graph
    topology and coloring change.

If the existing data source or implementation does not support a
specific step, retain the existing working path and clearly communicate
the limitation rather than inventing a capability.

## 7. Functional requirements

### FR-01: Tower data loading

-   Use the project's existing supported tower-data source and loading
    path.
-   Filter to the selected region before graph construction.
-   Normalize and validate identifiers, latitude, longitude, and
    coverage range where available.
-   Handle missing or invalid range values using an explicit, documented
    fallback or exclude the record with a visible explanation.
-   Show data source, record count, and relevant limitations.
-   Do not claim that the data is real-time unless the source and update
    mechanism prove that.

### FR-02: Geographic map

-   Display tower locations on an interactive Leaflet map.
-   Display modeled coverage circles only when the required range data
    or explicit user setting exists.
-   Distinguish uncolored, colored, selected, and invalid states without
    relying on color alone.
-   Keep map markers and graph nodes linked to the same stable tower
    IDs.

### FR-03: Interference graph construction

-   Build an undirected graph G=(V,E).
-   A vertex represents one valid selected tower.
-   For circular coverage models, add edge (i,j) when d(i,j) \<= r_i +
    r_j, subject to the project's documented distance and boundary
    convention.
-   Use a correct geographic distance calculation for latitude/longitude
    (e.g., Haversine) or a suitable projected coordinate system. Do not
    use raw degree differences as metres.
-   Avoid an all-to-all graph. Use spatial filtering/indexing if needed
    for performance, but do not remove valid edges merely to enforce a
    maximum degree.
-   Explain why an edge exists in the tower details panel.
-   Keep the graph definition consistent across the map, graph view,
    algorithms, and validator.

### FR-04: Configuration and recalculation

-   Allow users to change only settings supported by the current data
    model, such as selected region or a documented global
    coverage-radius assumption.
-   On change, rebuild the graph and rerun the required calculations.
-   Clearly label assumed or overridden values.
-   Do not label user-triggered recomputation as real-time telecom
    optimization.

### FR-05: Graph exploration

-   Provide a graph view showing vertices and edges for the same graph
    as the map.
-   Selecting a tower in either view highlights the corresponding
    tower/node and its neighbors in both views.
-   Show degree, assigned color/frequency when available, and
    neighboring tower IDs.
-   Use a readable layout for small/medium graphs and provide sensible
    performance limits for large selections.

### FR-06: Coloring algorithms

-   Implement/use DSatur and Welsh--Powell on the same graph input.
-   Each algorithm returns a node-to-color mapping and runtime
    measurement.
-   Make algorithm choice clear.
-   Ensure deterministic tie-breaking where practical so repeated runs
    are explainable.
-   Explain that the algorithms are heuristics and do not guarantee a
    globally minimum coloring for every graph.

### FR-07: Independent validation

-   Validate the resulting assignment separately from the coloring
    routine.
-   Check every edge (u,v) and flag a conflict if color\[u\] ==
    color\[v\].
-   Report total conflicts and valid/invalid status.
-   Do not display a success state if validation has not run or has
    failed.
-   Include tests for empty graphs, isolated vertices, simple paths,
    triangles, disconnected components, and deliberately invalid color
    assignments.

### FR-08: Results and comparison

Show, when available: - Number of selected towers / vertices. - Number
of modeled interference edges. - Number of colors used by each
algorithm. - Validation conflict count. - Measured algorithm runtime. -
Optional graph density and degree statistics if implemented correctly. -
A comparison view based on the same graph and same configuration.

Do not fabricate metrics. Clearly separate calculated results from
assumptions and sample/demo data.

### FR-09: Explainability

-   Describe the edge rule in plain language.
-   Show the selected tower's conflicting neighbors.
-   Explain why an adjacent tower cannot share its assigned color.
-   Provide a short description of each algorithm.
-   Label coverage overlap as a simplified interference proxy, not proof
    of actual RF interference.

### FR-10: Errors and empty states

-   Handle failed data loading, empty regions, missing coordinates,
    invalid ranges, algorithm errors, and large selections gracefully.
-   Provide actionable messages and preserve the user's current context
    where possible.

## 8. Non-functional requirements

-   Use the existing manageable stack: Python, FastAPI, NetworkX, HTML,
    CSS, vanilla JavaScript, and Leaflet.
-   Keep modules small, explicit, and testable.
-   Avoid adding a database, account system, microservices, or new
    frontend framework.
-   Keep map interactions responsive for the supported data size.
-   Use accessible contrast, keyboard-accessible controls, clear labels,
    and responsive layout.
-   Keep API errors structured and user-readable.
-   Document setup, data source, assumptions, and known limitations.

## 9. Acceptance criteria

1.  The graph is selective and is generated by the documented adjacency
    rule; it is not complete unless the data genuinely satisfies that
    rule.
2.  Distances use a valid geographic calculation or projected coordinate
    system.
3.  Map markers, graph nodes, and algorithm results use the same stable
    tower IDs.
4.  Both algorithms run against the same graph and return assignments
    for every graph vertex.
5.  The independent validator checks every edge and correctly detects an
    intentionally introduced conflict.
6.  The UI reports actual vertex count, edge count, color count,
    runtime, and conflict count without fabricated values.
7.  Selecting a tower reveals its graph neighbors and modeled edge
    rationale.
8.  Reconfiguration causes a new graph and result to be computed.
9.  The interface explains that heuristic color count is not necessarily
    the chromatic number.
10. Existing working functionality is preserved unless a change is
    necessary to satisfy this PRD.

## 10. Risks and mitigations

-   **Coverage data is incomplete or estimated:** show the source and
    assumptions; avoid physical-interference claims.
-   **Wrong distance units:** test distance calculations and explicitly
    convert units.
-   **False edges or missing edges:** unit-test boundary cases and
    compare small examples manually.
-   **Heuristic results are mistaken for optimal results:** use precise
    labels such as "colors used," not "minimum frequencies," unless
    optimality is proven.
-   **Overengineering:** freeze non-goals and implement only the
    acceptance criteria.
-   **Large graph slows the UI:** filter the geographic selection and
    use spatial candidate filtering without changing the mathematical
    edge rule.

## 11. MVP completion definition

The MVP is complete when a user can load a manageable geographic tower
set, inspect a selective modeled interference graph, run both coloring
heuristics, compare their outputs, verify zero edge conflicts, and
understand the assumptions and limitations from the interface.
