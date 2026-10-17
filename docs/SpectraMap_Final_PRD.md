# SpectraMap --- Final Product Requirements Document

**Product name:** SpectraMap\
**Subtitle:** Graph Coloring for Cellular Frequency Optimization

**Version:** 1.0\
**Product type:** Location-based interactive web application

## 1. Product vision

SpectraMap lets a user explore available cell records around their
current location and run a simplified graph-coloring
frequency-allocation simulation.

The intended experience is straightforward:

1.  The user opens SpectraMap.
2.  The browser asks for location permission.
3.  The map centers on the user's location and shows available nearby
    cell records within a default radius.
4.  The user can change the search radius.
5.  The user clicks **Optimize Frequencies**.
6.  SpectraMap builds an interference graph, runs graph-coloring
    algorithms, validates the assignments, and colors the map.
7.  The user can compare DSatur with Welsh--Powell and optionally
    display interference connections.

The user does not upload or import a dataset. SpectraMap retrieves
permitted data automatically through the backend and caches it where
appropriate.

## 2. Problem statement

Cellular networks reuse a limited set of radio frequencies. Nearby cells
may interfere if they use the same frequency, depending on real-world
factors that this educational model does not fully simulate.

SpectraMap represents the simplified problem as graph coloring:

-   **Vertex:** one cell record returned by the data source.
-   **Edge:** a pair of records considered potentially interfering under
    the project's declared coverage-circle rule.
-   **Color:** an abstract frequency group.
-   **Valid coloring:** the endpoints of every edge have different
    colors.
-   **Optimization goal:** find a valid coloring using as few colors as
    possible.

This project demonstrates discrete mathematics and graph algorithms. It
does not configure carrier equipment or produce a certified real-world
RF plan.

## 3. Final technology stack

  -----------------------------------------------------------------------
  Part                    Technology              Reason
  ----------------------- ----------------------- -----------------------
  Backend/API             Python + FastAPI        One small Python
                                                  application handles
                                                  data, algorithms, and
                                                  API routes

  Graph                   NetworkX                Provides graph data
                                                  structures and graph
                                                  utilities

  Data processing         Python; Pandas only     Normalize and inspect
                          where useful            returned records

  Frontend                HTML + CSS + vanilla    Simple stack without a
                          JavaScript              separate frontend
                                                  framework/build
                                                  pipeline

  Map                     Leaflet                 Interactive map,
                                                  markers, circles, and
                                                  lines

  Data source             OpenCellID area API     Automatically fetches
                                                  available cell records
                                                  near the selected
                                                  location

  Cache                   Local managed files     Avoid unnecessary
                                                  repeat requests and
                                                  retain last-known-good
                                                  data

  Tests                   pytest                  Test graph logic,
                                                  algorithms, validation,
                                                  and data handling
  -----------------------------------------------------------------------

FastAPI will serve both the static frontend and the JSON API. Do not add
React, TypeScript, a database, a task queue, or more infrastructure
unless implementation evidence demonstrates a real need.

## 4. Final feature set

### F-01 --- Automatic location detection

-   On opening the application, request browser geolocation permission.
-   If permission is granted, center the map on the user's location.
-   Do not store the user's exact location in the persistent
    dataset/cache.
-   If permission is denied or unavailable, let the user move the map
    and use the map center as the analysis location.
-   Explain that location permission identifies the user's position; it
    does not itself discover cell records.

### F-02 --- Nearby cell records

-   Automatically request available OpenCellID records around the
    selected map center.
-   Show the selected search radius and the number of records returned.
-   Display available cell records as map markers.
-   Do not describe these records as a complete list of physical towers.
    OpenCellID records are logical cell observations; several cells can
    share physical infrastructure, and coverage is community-dependent.
-   If no records are returned, show a clear empty-data state rather
    than implying that no cellular service exists.

### F-03 --- Adjustable search radius

Provide simple radius choices such as **500 m, 1 km, 2 km, and 5 km**,
subject to the provider's limits and the application's supported
processing range. The selected radius determines which records are
requested/selected for the map and analysis.

If the requested area cannot be fully retrieved because of provider
quotas, bounding-box limits, or record limits, show a clear warning and
indicate whether the results are partial. Do not silently present
partial data as complete.

### F-04 --- Optimize Frequencies button

The user explicitly starts optimization by clicking **Optimize
Frequencies**.

On click, the backend: 1. Uses the available records for the current
center and radius. 2. Normalizes and filters records. 3. Builds the
interference graph. 4. Runs DSatur and Welsh--Powell on the same graph.
5. Independently validates both color assignments. 6. Selects the valid
result with fewer colors as the default display; if tied, use a
documented deterministic tie-break. 7. Returns the result and metrics to
the frontend.

The initial map and cell markers should be available before
optimization. The button is the explicit trigger for graph coloring,
rather than automatically coloring the map on every page load.

### F-05 --- Color-coded results

-   Each color represents an abstract frequency group, not a real
    licensed frequency or MHz channel.
-   Cells connected by an interference edge must have different colors.
-   Non-adjacent cells may reuse a color.
-   Display a legend and make the selected algorithm clear.
-   Never display a result as valid unless the independent validator
    reports zero conflicts and no missing assignments.

### F-06 --- Algorithm comparison

Show DSatur and Welsh--Powell results side by side: - Number of colors
used. - Runtime. - Validation status and conflict count.

Let the user switch the map between the two valid results. The default
should be the valid result that uses fewer colors. If the counts tie,
use the documented deterministic tie-break. Both algorithms are
heuristics; neither guarantees the exact chromatic number on every
graph.

### F-07 --- Optional interference lines

Provide a toggle that draws a line between cell records joined by an
edge in the generated graph. Lines should be hidden by default when the
map is dense, to avoid visual clutter.

### F-08 --- Cell details

Clicking a marker opens a small details panel with available fields,
such as: - Cell identifier and radio technology. - Latitude/longitude
returned by the provider. - Reported range, if available. - Assigned
color after optimization. - Graph degree (number of modeled interference
neighbors), after graph construction.

Do not invent unavailable fields or claim that reported range is
measured ground truth.

### F-09 --- Results and status

Display: - Number of cell records used as vertices. - Number of
interference edges. - Number of colors used by each algorithm. -
Conflict count and validation status. - Data-source attribution. - Data
retrieval/cache status and time when available. - Graph-building and
algorithm runtimes. - Any warning about incomplete data or provider
limits.

### F-10 --- Automatic data acquisition without imports

The system retrieves records from OpenCellID through the backend. Users
do not upload CSV or JSON files. The API key remains server-side. The
backend caches accepted data to reduce repeat requests and can use
last-known-good cached records if a refresh fails.

## 5. Data source and constraints

### Primary source

OpenCellID documents the `GET https://opencellid.org/cell/getInArea`
endpoint for cell records within a bounding box. The API key is
required. Request JSON explicitly with `format=json`.

Official references: - API overview:
https://docs.opencellid.org/docs/api/overview - Area lookup:
https://docs.opencellid.org/docs/api/cells-in-area - Access and limits:
https://docs.opencellid.org/docs/getting-started/access-and-limits -
Attribution: https://docs.opencellid.org/docs/attribution

### Constraints the implementation must respect

-   Current documentation states a daily allowance of 1,000 API request
    credits per user.
-   The area endpoint returns at most 50 records per request and has a
    maximum bounding-box area of 4,000,000 square metres; larger areas
    need tiling and/or pagination.
-   Each returned cell consumes an API credit according to the
    provider's documentation. Check the current provider terms before
    deployment.
-   Some API errors may be encoded in a response body even when HTTP
    status is 200. Check both status and body.
-   OpenCellID is community-contributed. Sparse results do not prove
    that an area has no service.
-   Coordinates may be rounded, and reported range is an estimate. This
    affects the accuracy of small-radius distance calculations.

### API-key handling

-   The operator configures `OPENCELLID_API_KEY` in a server-side
    environment variable or local `.env`.
-   The key must never appear in frontend JavaScript, HTML, API
    responses, logs, or Git history.
-   Include `.env.example` with a placeholder only.
-   If the key is missing or the provider refuses access, show a clear
    setup/error state. Do not require ordinary users to paste the key
    into the UI.

### Attribution and license

OpenCellID data is licensed under CC BY-SA 4.0. Show visible attribution
near the map or data information panel:

> Cell tower data from OpenCellID, licensed under CC BY-SA 4.0.

Link to https://opencellid.org and
https://creativecommons.org/licenses/by-sa/4.0/. If sharing adapted
data, follow the applicable ShareAlike terms and retain required
notices.

## 6. Mathematical model

Let (G=(V,E)).

For each accepted cell record (i), define its reported/estimated range
as (r_i) metres. Let (d(i,j)) be the distance between two records in
metres. The initial simplified edge rule is:

\[ (i,j)`\in `{=tex}E `\quad `{=tex}`\text{if}`{=tex}
`\quad `{=tex}d(i,j)`\le `{=tex}r_i+r_j \]

This models overlap of estimated coverage circles. It is an
approximation, not a real RF propagation model.

The implementation must: - Use a suitable geodesic distance calculation
or projected coordinate system. - Never treat raw latitude/longitude
degrees as metres. - Define how records with missing or invalid range
are handled; do not silently invent ranges. - Test the spatial edge rule
against small, manually verifiable examples. - Avoid assuming that the
graph is planar.

A coloring (c) is valid if:

\[ `\forall `{=tex}(u,v)`\in `{=tex}E,`\quad `{=tex}c(u)`\ne `{=tex}c(v)
\]

The target is to minimize the number of distinct colors. DSatur and
Welsh--Powell are heuristics; report the best valid result among those
tested, not a proven minimum, unless a proof or exact solver establishes
it.

## 7. Main user journey

1.  **Open app:** request location permission and show the map.
2.  **Load records:** fetch available cell records for the default
    radius, using the backend and cache.
3.  **Explore:** change radius or move the map to another area.
4.  **Optimize:** click **Optimize Frequencies**.
5.  **Process:** show progress while the graph is built, both algorithms
    run, and validation occurs.
6.  **Inspect result:** color the cells using the selected algorithm and
    show counts/metrics.
7.  **Compare:** switch between DSatur and Welsh--Powell results.
8.  **Explain:** optionally display interference lines and inspect
    individual cells.

## 8. Non-functional requirements

-   **Correctness:** a result marked valid has zero edge-color conflicts
    and no missing assignments.
-   **Transparency:** distinguish provider observations, estimated
    ranges, model edges, and abstract frequency colors.
-   **Privacy:** do not persist the user's precise location unless a
    future explicit feature requires it and obtains consent.
-   **Resilience:** preserve cached data if a refresh fails; label
    cached/partial data.
-   **Security:** keep the API key server-side and redact it from logs.
-   **Usability:** provide clear loading, empty, partial-data, success,
    and error states.
-   **Performance target:** for a locally available graph of 1,000
    records, aim for graph construction plus both coloring algorithms to
    complete in under 3 seconds on documented hardware, excluding
    network fetch and map tiles. Benchmark before claiming this target
    is met.

## 9. Acceptance criteria

1.  The application requests location permission and centers the map
    when permission is granted.
2.  If permission is denied, the user can select the analysis center by
    moving the map.
3.  Nearby available cell records are loaded automatically without file
    import.
4.  The radius control changes the analysis area and record set.
5.  The Optimize Frequencies button triggers graph construction, both
    algorithms, and validation.
6.  The result map uses abstract colors and has a visible legend.
7.  DSatur and Welsh--Powell metrics are comparable on the same graph.
8.  The validator checks every edge; any invalid result is rejected.
9.  The interference-line toggle displays the graph edges when enabled.
10. The interface displays source attribution, data limitations, and
    partial/stale status where applicable.
11. Provider key and user coordinates are not exposed inappropriately.
12. Tests cover data normalization, graph edges, both algorithms,
    validation, and provider/cache failure cases.

## 10. Explicit exclusions

-   User dataset import/upload.
-   User accounts and database.
-   Real carrier equipment configuration.
-   Actual licensed-frequency or MHz recommendations.
-   Certified RF planning or propagation simulation.
-   ML prediction, terrain/building modeling, and advanced network
    engineering.
-   Claims that OpenCellID contains every nearby cell or physical tower.
-   Claims that heuristic coloring proves the graph's chromatic number.

## 11. Definition of done

SpectraMap is complete when a user can open the application, view their
location and available nearby cell records, adjust the radius, click
**Optimize Frequencies**, and receive a validated color-coded result
with DSatur/Welsh--Powell comparison, conflict metrics, and optional
interference lines---without importing a dataset.
