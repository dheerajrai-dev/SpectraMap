# SpectraMap --- Final System Architecture

**Product:** SpectraMap --- Graph Coloring for Cellular Frequency
Optimization\
**Version:** 1.0 --- aligned with the finalized PRD\
**Architecture style:** Small FastAPI application serving a static
JavaScript frontend

## 1. Architecture decisions

Use the smallest stack that supports the final agreed experience:

-   Python + FastAPI for backend routes and processing.
-   NetworkX for graph representation.
-   HTML + CSS + vanilla JavaScript for the frontend.
-   Leaflet for the interactive map.
-   OpenCellID area API for available cell records.
-   Local cache files for reducing repeat requests.
-   pytest for automated tests.

FastAPI serves both the static frontend and JSON API. No separate
frontend build tool, database, authentication system, or task queue is
required for the intended student deployment.

## 2. Simple folder structure

``` text
SpectraMap/
├── app.py                    # FastAPI, static frontend, API routes
├── data_service.py           # OpenCellID requests, normalization, cache
├── graph_engine.py           # Graph, DSatur, Welsh–Powell, validation
├── requirements.txt
├── data/                     # App-managed cache; never commit private data
├── static/
│   ├── index.html            # Page structure
│   ├── style.css             # Dashboard and glassmorphism styles
│   └── app.js                # Geolocation, map, API calls, controls
├── tests/
│   └── test_graph_engine.py
├── docs/
│   ├── SpectraMap_Final_PRD.md
│   └── SpectraMap_Final_System_Architecture.md
├── .env.example
├── .gitignore
└── README.md
```

Keep each file focused but avoid creating many tiny modules. Split files
only if actual complexity warrants it.

## 3. Component diagram

``` mermaid
flowchart TD
    U[User opens SpectraMap] --> FE[HTML / CSS / JavaScript + Leaflet]
    FE --> GEO[Browser geolocation permission]
    GEO --> CENTER[Selected map center + radius]
    FE --> API[FastAPI]
    CENTER --> API
    API --> DATA[data_service.py]
    DATA --> CACHE[Local managed cache]
    DATA --> OC[OpenCellID area API]
    OC --> DATA
    DATA --> RECORDS[Validated nearby cell records]
    RECORDS --> FE
    FE -->|Click Optimize Frequencies| API
    API --> GE[graph_engine.py]
    GE --> GRAPH[Build interference graph]
    GRAPH --> DS[DSatur]
    GRAPH --> WP[Welsh-Powell]
    DS --> VALID[Independent conflict validator]
    WP --> VALID
    VALID --> RESULT[Validated assignments + metrics]
    RESULT --> API
    API --> FE
    FE --> MAP[Colored Leaflet map + optional edges]
```

## 4. User location and privacy

1.  `static/app.js` calls the browser Geolocation API after the page
    opens, with a clear permission explanation.
2.  If permission succeeds, the frontend centers the map and sends the
    selected center and radius to FastAPI when requesting cell records.
3.  If permission is denied, the user can pan the map and use the
    current map center.
4.  The backend uses the supplied center/radius only to determine the
    requested geographic area and should not persist the user's exact
    location in the cell-data cache.
5.  The API key is held only by the backend.

Geolocation requires a secure context in normal browser use (HTTPS, or
localhost during development). Do not attempt to bypass browser
permission.

## 5. OpenCellID data service

### Endpoint

Use the documented endpoint:

`GET https://opencellid.org/cell/getInArea`

Required parameters: - `key`: server-side API key - `BBOX`:
`latmin,lonmin,latmax,lonmax` - `format=json`

Optional filters such as radio technology or mobile country code can be
applied if useful, but do not filter by default in a way that hides
relevant cell records without explaining the choice.

Official references: - API overview:
https://docs.opencellid.org/docs/api/overview - List cells in an area:
https://docs.opencellid.org/docs/api/cells-in-area - Access and limits:
https://docs.opencellid.org/docs/getting-started/access-and-limits -
Attribution: https://docs.opencellid.org/docs/attribution

### Important provider constraints

Current documentation states: - API access requires a key. - 1,000 API
request credits per user per day. - At most 50 cell records per area
request. - Maximum bounding-box area of 4,000,000 square metres. - Each
returned cell consumes a credit. - Some error responses may use HTTP
200, so the response body must also be checked.

These limits make a naive "one API call for any radius" approach
incorrect. A 2 km-radius circle has a bounding square much larger than 4
km². For larger areas, the service must tile the bounding box into
permitted subareas, paginate where applicable, deduplicate overlapping
results, and stop or mark the result partial if quota/request budgets
are reached. The current limits and terms must be checked again before
release.

For each request: 1. Validate center and radius. 2. Calculate a bounding
box around the center and radius. 3. Split it into boxes within the
documented limit where necessary. 4. Request data with explicit JSON
format and reasonable timeouts. 5. Check HTTP status and provider
response body. 6. Validate and normalize the returned records. 7.
Deduplicate records from overlapping tiles. 8. Filter records to the
intended radius using a correct distance calculation. 9. Store accepted
results in cache with source and retrieval metadata. 10. Return the data
and any partial-result warning to the frontend.

Do not call the provider on every render or for every marker. Cache by
region/tile and freshness policy. Do not exceed request/credit limits
through automatic retries.

### Data model

Normalize records to a consistent internal shape, retaining source
identifiers and optional fields:

``` json
{
  "tower_id": "stable-source-or-generated-id",
  "latitude": 28.6,
  "longitude": 77.2,
  "range_m": 500,
  "radio": "LTE",
  "mcc": 404,
  "mnc": 10,
  "area": 123,
  "cell_id": 45678,
  "source": "OpenCellID",
  "retrieved_at": "ISO-8601 timestamp"
}
```

Example values are illustrative only. Use actual response fields and
preserve optional fields when present. Do not invent missing range or
identifier data.

### Attribution

OpenCellID data is licensed under CC BY-SA 4.0. Show this visible credit
beside the map or data information panel:

"Cell tower data from OpenCellID, licensed under CC BY-SA 4.0."

Link to https://opencellid.org and
https://creativecommons.org/licenses/by-sa/4.0/. Follow ShareAlike
requirements when distributing adapted data.

## 6. Cache and failure handling

Use simple local cache files and metadata; no database is needed.

Cache metadata should include: - Cache key/area tile. - Retrieval
timestamp. - Source. - Number of records. - Whether the result is
complete or partial. - Data/schema version where relevant.

Rules: - A failed refresh must not overwrite a valid cache. - Clearly
mark cached results and show their age. - If the provider is unavailable
but cache exists, use the cache and disclose its age. - If there is no
cache and the API key is missing or the provider fails, show an
actionable error. - Never generate fake records or claim a partial
result is complete. - Avoid persisting the user's precise geolocation in
the data cache.

## 7. Graph model and edge construction

For each accepted cell record, create one graph vertex. For each pair
(i,j), compute distance (d(i,j)) in metres. Add an undirected edge when:

\[ d(i,j) `\le `{=tex}r_i+r_j \]

where (r_i,r_j) are accepted estimated ranges. This is the project's
simplified coverage-circle overlap model.

Implementation requirements: - Use a geodesic calculation or suitable
projected coordinate system. - Never use raw latitude/longitude degree
differences as metres. - Handle missing or invalid ranges according to
an explicit policy. - For small local datasets, begin with an
understandable all-pairs implementation if performance is acceptable. -
If necessary, add spatial-index candidate generation, then perform the
same exact distance/range check. - Test optimized graph output against
brute-force pairs on small test data. - Do not assume the graph is
planar.

**Important limitation:** OpenCellID cell records are
community-contributed logical cell observations, not a complete list of
physical tower structures. Multiple records can share a physical site.
Coordinates and ranges may be approximate or rounded, so a 500 m
analysis radius can be less reliable than the UI may visually suggest.
Disclose this limitation.

## 8. Graph-coloring engine

### Welsh--Powell

1.  Sort vertices by descending degree.
2.  Assign a color to the first uncolored vertex.
3.  Assign that same color to as many remaining uncolored vertices as
    possible, skipping any vertex adjacent to one already assigned that
    color.
4.  Repeat with the next color until all vertices are colored.

### DSatur

1.  Choose an uncolored vertex with the highest saturation degree
    (number of distinct colors among its colored neighbors).
2.  Break ties by total graph degree and then a stable identifier.
3.  Assign the lowest available color not used by its colored neighbors.
4.  Repeat until all vertices are colored.

Use deterministic tie-breaking so repeated runs on the same graph are
reproducible.

### Independent validation

For each algorithm's output, iterate over every edge: - Both endpoints
must have a color. - Endpoints must have different colors. - Count
conflicts and missing assignments.

A result is valid only if conflict count is zero and missing-assignment
count is zero. Reject invalid results.

### Default algorithm selection

Run both algorithms on the same graph. Among valid outputs, display the
one with fewer colors by default. If color counts tie, use a documented
deterministic tie-break, such as lower measured runtime. Let users
switch between both outputs.

Do not label a heuristic result as the proven chromatic number. Use
wording such as "best result among tested algorithms."

## 9. API design

Keep the API small.

### `GET /api/status`

Returns readiness, source/cache state, and whether data loading or
optimization is running.

### `GET /api/cells?lat=...&lon=...&radius_m=...`

Loads or retrieves cached cell records for the selected center and
radius. The API returns normalized records, source attribution,
retrieval time, and any partial-data warning.

### `POST /api/optimize`

Example request:

``` json
{
  "center": {"latitude": 28.6, "longitude": 77.2},
  "radius_m": 2000
}
```

The backend reuses the appropriate managed data, builds the graph, runs
both algorithms, validates the outputs, and returns assignments and
metrics. Example values are illustrative only.

### `GET /api/results/{result_id}`

Returns algorithm metrics, validation status, provenance, and assignment
data for a previous result still in the local result cache.

The initial application can keep these routes in `app.py`; split them
only if it becomes genuinely hard to maintain.

## 10. API response content

The cell response should include: - Normalized cell records. - Data
source and attribution. - Retrieval timestamp/cache status. -
Partial-result flag and warnings.

The optimization response should include: - Result ID. - Selected center
and radius. - Vertex and edge counts. - DSatur color count, runtime, and
validation. - Welsh--Powell color count, runtime, and validation. -
Selected default algorithm. - Color assignment for each cell. - Optional
edge list or endpoint pairs for the interference overlay. - Graph-build
runtime. - Source/cache provenance and warnings.

Avoid sending unnecessary duplicate geometry. If edge count is large,
return edges only when requested or within the current map viewport.

## 11. Frontend behavior

### On application open

1.  Render the page and map.
2.  Request geolocation permission.
3.  Center on the user when permitted; otherwise use a default map
    center and allow panning.
4.  Request nearby records through `GET /api/cells`.
5.  Display cell markers, range controls, data status, and OpenCellID
    attribution.

### When radius or map center changes

-   Debounce rapid map movement so the API is not called for every
    frame.
-   Load the corresponding cell records from cache or provider.
-   Show loading, partial-data, and error states clearly.
-   Do not run graph coloring automatically on every map movement.

### When Optimize Frequencies is clicked

1.  Disable the button and show progress.
2.  Call `POST /api/optimize`.
3.  Receive both validated assignments.
4.  Color markers/circles using the selected algorithm.
5.  Show color count, edge count, conflict count, runtimes, and
    algorithm comparison.
6.  Enable algorithm switching and the optional interference-line
    toggle.

### Map controls

-   Radius: 500 m, 1 km, 2 km, 5 km, subject to supported
    processing/provider constraints.
-   Algorithm display: best valid result, DSatur, Welsh--Powell.
-   Interference edges: hidden by default; show on request.
-   Marker selection: show available cell details and assigned color.

## 12. Minimal test plan

Use pytest for backend logic.

-   Validate and normalize API response records.
-   Reject invalid coordinates and invalid ranges.
-   Deduplicate overlapping area-query results.
-   Verify the distance/range edge rule with hand-calculated examples.
-   Test paths, cycles, cliques, isolated vertices, and disconnected
    graphs.
-   Test DSatur and Welsh--Powell assignments.
-   Introduce a deliberately invalid coloring and ensure the validator
    detects it.
-   Mock provider success, quota exhaustion, missing key, timeout,
    malformed body, and HTTP-200 error body.
-   Confirm cached data remains usable after refresh failure.
-   Confirm partial-data warnings propagate to the frontend.
-   If spatial indexing is used, compare results with brute force on
    small datasets.

## 13. Implementation order

1.  Confirm OpenCellID API key access and current limits.
2.  Create the simple folder structure and FastAPI static serving.
3.  Implement `data_service.py`: API request, parsing, normalization,
    cache, and failure handling.
4.  Implement `graph_engine.py`: graph construction, DSatur,
    Welsh--Powell, validator, metrics.
5.  Add `/api/status`, `/api/cells`, and `/api/optimize`.
6.  Build the Leaflet map and location/radius controls.
7.  Connect the Optimize Frequencies button and color-coded result
    rendering.
8.  Add algorithm comparison and optional interference lines.
9.  Add attribution, limitations, tests, and documentation.
10. Benchmark the pipeline and tune only where measurement shows a need.

These are development steps toward one final product, not separate
product versions.

## 14. Definition of done

A user can open SpectraMap, view their location and available nearby
cell records, choose a radius, click **Optimize Frequencies**, and see
validated color-coded results with DSatur/Welsh--Powell comparison,
metrics, and optional interference lines. The app needs no dataset
import, keeps API credentials server-side, handles provider limits
honestly, and clearly labels the results as a simplified educational
model.
