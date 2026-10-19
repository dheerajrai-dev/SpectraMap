# SpectraMap --- System Architecture

**Version:** 2.0\
**Architecture style:** Small modular monolith\
**Status:** Revised implementation baseline

## 1. Architecture principles

-   Preserve the existing working code and project structure where
    practical.
-   Use Python, FastAPI, NetworkX, HTML/CSS/vanilla JavaScript, and
    Leaflet.
-   Prefer a modular monolith over microservices.
-   Do not add a database, authentication, AI services, or a frontend
    framework.
-   Keep spatial modeling, graph construction, coloring, and validation
    separate.
-   Keep the graph definition consistent across every view and
    algorithm.
-   Treat all coverage/interference conclusions as model-based.

## 2. High-level architecture

``` text
┌──────────────────────────────────────────────────────────┐
│                    Browser / Frontend                    │
│                                                          │
│  HTML + CSS + Vanilla JS + Leaflet                       │
│  ┌─────────────┐ ┌────────────┐ ┌─────────────────────┐  │
│  │ Geographic  │ │ Graph      │ │ Results / Compare   │  │
│  │ Map         │ │ Explorer   │ │ Metrics / Validate  │  │
│  └─────────────┘ └────────────┘ └─────────────────────┘  │
└──────────────────────────┬───────────────────────────────┘
                           │ HTTP / JSON
┌──────────────────────────▼───────────────────────────────┐
│                    FastAPI Application                   │
│                                                          │
│  API / Request Validation                                │
│       │                                                  │
│       ▼                                                  │
│  Tower Data Service → Spatial Processing                │
│       │                    │                             │
│       └──────────────┬─────┘                             │
│                      ▼                                   │
│              Graph Builder                               │
│                      │                                   │
│           ┌──────────┴──────────┐                        │
│           ▼                     ▼                        │
│     DSatur Solver        Welsh–Powell Solver             │
│           └──────────┬──────────┘                        │
│                      ▼                                   │
│            Independent Validator                         │
│                      ▼                                   │
│              Metrics / Response                          │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
             Existing tower data source / local file
```

## 3. Backend modules

Keep these as logical modules; adapt names to the existing repository
rather than forcing a wholesale folder restructure.

### 3.1 API layer

Responsibilities: - Validate request parameters and request body. - Call
the appropriate service. - Return structured JSON responses. - Map
expected failures to appropriate HTTP status codes. - Avoid implementing
graph mathematics directly in route handlers.

### 3.2 Tower data service

Responsibilities: - Use the existing source and ingestion workflow. -
Filter towers by supported geographic bounds or region. - Normalize
stable IDs, coordinates, and range fields. - Reject or report malformed
records. - Include source and data-quality metadata in responses.

Do not claim automatic live location search or live data unless the
repository already implements and documents it.

### 3.3 Spatial processing

Responsibilities: - Convert coordinate/range data into consistent
units. - Calculate geographic distances correctly. - Find plausible
candidate pairs efficiently when necessary. - Apply the single
documented edge rule. - Handle boundary conditions consistently.

A spatial index may reduce candidate comparisons, but it must not alter
the final edge criterion. Delaunay or Voronoi methods are not required.

### 3.4 Graph builder

Responsibilities: - Create a NetworkX undirected graph. - Store stable
tower ID and relevant display attributes on nodes. - Add edges only when
the interference criterion is met. - Optionally store edge metadata such
as distance, summed radius, and the rule that created the edge. - Return
graph statistics and a serializable graph representation.

### 3.5 Coloring service

Responsibilities: - Run DSatur and Welsh--Powell using the same graph. -
Return a stable mapping from tower ID to integer color/frequency
index. - Measure runtime with a monotonic high-resolution timer. -
Define tie-breaking consistently. - Report the actual color count
used. - Never call a heuristic result the proven chromatic number.

### 3.6 Independent validation service

Responsibilities: - Accept a graph and color mapping. - Check every
edge. - Return total conflict count and conflicting edge IDs. - Check
that every vertex has an assignment. - Remain independent of the
algorithm implementation so it can catch solver defects.

### 3.7 Metrics/serialization service

Responsibilities: - Serialize nodes, edges, coordinates, assignments,
and metrics into JSON. - Keep field names consistent across endpoints. -
Avoid returning non-serializable NetworkX objects. - Report counts
derived from actual graph/result objects.

## 4. Suggested API contract

Adapt routes to the existing application; do not create duplicate
endpoints if equivalent ones already exist.

### `GET /api/health`

Example response:

``` json
{
  "status": "ok"
}
```

### `GET /api/towers?west=...&south=...&east=...&north=...`

Returns the selected tower records and source metadata.

Example response shape:

``` json
{
  "source": "configured tower dataset",
  "count": 2,
  "towers": [
    {
      "id": "tower-1",
      "lat": 28.61,
      "lon": 77.21,
      "range_m": 350
    }
  ],
  "warnings": []
}
```

### `POST /api/graph/build`

Request:

``` json
{
  "tower_ids": ["tower-1", "tower-2"],
  "radius_override_m": null
}
```

Response shape:

``` json
{
  "nodes": [
    {
      "id": "tower-1",
      "lat": 28.61,
      "lon": 77.21,
      "range_m": 350,
      "degree": 1
    }
  ],
  "edges": [
    {
      "source": "tower-1",
      "target": "tower-2",
      "distance_m": 420,
      "threshold_m": 700
    }
  ],
  "metrics": {
    "vertex_count": 2,
    "edge_count": 1
  },
  "assumptions": [
    "Edges represent modeled overlap of circular coverage areas."
  ]
}
```

### `POST /api/optimize`

Request:

``` json
{
  "graph_id": "optional-if-the-existing-app-uses-one",
  "algorithm": "dsatur"
}
```

If the current app does not retain graph IDs, pass a validated
graph/configuration reference using the simplest existing design. Do not
introduce persistent storage merely to support this endpoint.

Response shape:

``` json
{
  "algorithm": "dsatur",
  "assignments": {
    "tower-1": 0,
    "tower-2": 1
  },
  "metrics": {
    "color_count": 2,
    "runtime_ms": 0.42
  },
  "validation": {
    "is_valid": true,
    "conflict_count": 0,
    "conflicting_edges": []
  }
}
```

### `POST /api/compare`

Runs both algorithms against the same graph and returns each algorithm's
assignments, color count, runtime, and validation result. Avoid
duplicating graph construction between the two runs.

### API contract rules

-   Use Pydantic models if already used in the project.
-   Validate coordinate bounds, radius values, selected tower IDs, and
    algorithm names.
-   Return explicit error messages for empty or invalid graphs.
-   Do not return fake example values from real endpoints.
-   Use the actual project naming conventions if they differ from the
    illustrative examples above.

## 5. Data flow

1.  Frontend requests towers for a supported area.
2.  Data service loads and validates the records.
3.  Frontend displays towers on Leaflet.
4.  User requests graph construction or changes a supported model
    setting.
5.  Backend constructs the graph using the documented edge rule.
6.  Backend returns nodes, edges, and actual graph metrics.
7.  Frontend updates the map and graph explorer from the same graph
    response.
8.  User requests one algorithm or comparison.
9.  Coloring service calculates assignments and runtime.
10. Independent validator checks every edge.
11. Frontend renders assignments and validation results.

## 6. Frontend/backend data consistency

-   Use stable tower IDs everywhere.
-   Graph nodes must be a subset of the selected valid towers.
-   Every edge endpoint must refer to an existing node.
-   The map and graph explorer must consume the same graph payload.
-   Color assignments must refer to node IDs, never array positions.
-   After configuration changes, discard stale assignments or label them
    as stale until recomputation completes.
-   Never visually infer graph edges from proximity alone; render
    returned graph edges.

## 7. Error handling and observability

-   Log technical exceptions server-side without exposing stack traces
    to users.
-   Return a short user-facing message and a trace/request identifier if
    appropriate.
-   Report data warnings, invalid records, and source limitations.
-   Measure algorithm runtime separately from data loading and graph
    construction.
-   Avoid presenting total end-to-end time as algorithm runtime.

## 8. Testing strategy

### Spatial/graph tests

-   Two distant towers produce no edge.
-   Two towers whose modeled coverage areas overlap produce an edge.
-   Exact boundary follows the documented `<=` convention.
-   Latitude/longitude distance is measured correctly and in metres.
-   Missing or invalid range is handled by the documented policy.
-   No arbitrary maximum-degree cap deletes valid edges.

### Coloring/validation tests

-   Every graph vertex receives a color.
-   Every edge has differently colored endpoints for a valid result.
-   Validator detects a deliberately introduced conflict.
-   Empty graph, isolated vertices, path, triangle, disconnected graph,
    and larger fixture are tested.
-   Both algorithms receive the same graph.
-   Color count equals the number of distinct assigned color indices.

### API/UI integration tests

-   Invalid algorithm names return a clear error.
-   Empty selection is handled gracefully.
-   Map and graph use the same stable IDs and edges.
-   Reconfiguration rebuilds the graph and clears or recomputes old
    assignments.
-   Loading and error states are visible.

## 9. Deployment and local development

Keep the current simple run process. A typical local setup may use a
Python virtual environment, install the existing requirements, start the
FastAPI app with Uvicorn, and serve the frontend using the repository's
current method. Do not introduce Docker or additional infrastructure
unless the repository already depends on it.

## 10. Architecture decision summary

  Decision               Choice
  ---------------------- ------------------------------------------------
  Architecture           Modular monolith
  Backend                Python + FastAPI
  Graph representation   NetworkX
  Frontend               HTML + CSS + vanilla JavaScript
  Geographic map         Leaflet
  Persistence            Existing file/source approach; no new database
  Graph rule             Documented coverage-overlap rule
  Algorithms             DSatur and Welsh--Powell
  Verification           Independent edge-conflict validator
  Deployment             Existing simple local setup
