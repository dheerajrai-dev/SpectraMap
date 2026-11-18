"""
app.py — SpectraMap FastAPI application

Serves the static frontend and exposes the JSON API:
    GET  /api/health       — Health status check (v2 specification)
    GET  /api/status       — Health and readiness check (backward-compatible)
    GET  /api/towers       — Tower records for coordinate radius or bounding box
    GET  /api/cells        — Nearby cell records (backward-compatible alias)
    POST /api/graph/build  — Construct interference graph from tower records
    POST /api/optimize     — Frequency allocation via DSatur / Welsh-Powell
    POST /api/compare      — Dual algorithm benchmark on identical graph
"""

import os
import time
import uuid
import logging
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from data_service import (
    fetch_opencellid_records,
    haversine_distance,
    ATTRIBUTION_TEXT,
    normalize_radio_type,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    aggregate_towers_within_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    optimize_graph_frequencies,
    get_graph_metrics,
    get_interference_edges,
    serialize_graph_payload,
)
from schemas import (
    GraphBuildRequest,
    OptimizeRequest,
    CompareRequest,
    AccountingMetadata,
    EDUCATIONAL_DISCLAIMER_DEFAULT,
)

# Load environment variables from .env file
load_dotenv()

# Configure production-ready logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("spectramap")

app = FastAPI(
    title="SpectraMap",
    version="2.0",
    description="Spatial Graph Coloring for Cellular Frequency Optimization",
)

# CORS configuration
raw_cors = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in raw_cors.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_credentials=True if cors_origins != ["*"] else False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add defensive HTTP security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Graceful error handler preventing unhandled internal stack traces from leaking."""
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred while processing the request."},
    )

# Serve frontend static assets under the /static URL prefix
app.mount("/static", StaticFiles(directory="static"), name="static")


def _get_api_key() -> str | None:
    """Retrieve OpenCellID API key supporting both casing conventions."""
    return os.getenv("OPENCELLID_API_KEY") or os.getenv("OpenCelliD_api_key")


@app.get("/")
async def root():
    """Serve the frontend HTML workspace."""
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health_check():
    """Health check endpoint specified in SpectraMap System Architecture v2."""
    return {
        "status": "ok",
        "app": "SpectraMap",
        "version": "2.0",
    }


@app.get("/api/status")
async def status_check():
    """Backward-compatible application status endpoint."""
    return {
        "status": "ok",
        "app": "SpectraMap",
        "version": "2.0",
    }


def parse_radio_query(radios: list[str] | str | None) -> list[str]:
    """
    Parse and validate the radios query parameter.
    Supports:
      - None / omitted -> defaults to ['4G', '5G']
      - Repeated params: ?radios=4G&radios=5G -> ['4G', '5G']
      - Comma-delimited strings: ?radios=4G,5G -> ['4G', '5G']
      - Case-insensitivity & aliases: 'lte' -> '4G', 'nr' -> '5G'
    Raises:
      HTTPException(400) on invalid or empty radio selections.
    """
    if radios is None:
        return ["4G", "5G"]

    raw_items: list[str] = []
    if isinstance(radios, str):
        raw_items = [s.strip() for s in radios.split(",") if s.strip()]
    elif isinstance(radios, list):
        for item in radios:
            for part in str(item).split(","):
                cleaned = part.strip()
                if cleaned:
                    raw_items.append(cleaned)

    if not raw_items:
        raise HTTPException(
            status_code=400,
            detail="At least one radio technology ('4G', '5G') must be selected.",
        )

    normalized_set: set[str] = set()
    for item in raw_items:
        canonical = normalize_radio_type(item)
        if canonical is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid radio technology '{item}'. Allowed values: 4G, 5G.",
            )
        normalized_set.add(canonical)

    return sorted(list(normalized_set))


def _process_tower_records(
    cells: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
    query_radius: float,
    active_radios: list[str],
    limit: int,
    warnings: list[str],
    is_cached: bool,
    aggregate_2m: bool = False,
) -> dict[str, Any]:
    available_count = len(cells)

    eligible_records: list[dict[str, Any]] = []
    for c in cells:
        canonical = normalize_radio_type(c.get("radio"))
        if canonical and canonical in active_radios:
            rec = dict(c)
            rec["radio"] = canonical
            tid = str(rec.get("tower_id") or rec.get("id") or "")
            if tid.startswith("LTE_"):
                rec["tower_id"] = "4G_" + tid[4:]
            elif tid.startswith("NR_"):
                rec["tower_id"] = "5G_" + tid[3:]
            rec["id"] = rec.get("tower_id") or rec.get("id")
            eligible_records.append(rec)
    eligible_count = len(eligible_records)

    if aggregate_2m:
        records_to_sample = aggregate_towers_within_distance(eligible_records, 2.0)
    else:
        records_to_sample = eligible_records

    selected_records = select_spatially_dispersed_records(
        records_to_sample, center_lat, center_lon, limit=limit
    )

    selected_count = len(selected_records)

    selected_records, sites = group_cells_into_sites(selected_records)

    tech_dist = {
        "4G": sum(1 for r in selected_records if r.get("radio") == "4G"),
        "5G": sum(1 for r in selected_records if r.get("radio") == "5G"),
    }

    accounting = AccountingMetadata(
        available_count=available_count,
        eligible_count=eligible_count,
        selected_count=selected_count,
        excluded_count=available_count - selected_count,
        excluded_radio_count=available_count - eligible_count,
        excluded_limit_count=eligible_count - selected_count,
    )

    formatted_towers: list[dict[str, Any]] = []
    for r in selected_records:
        rec = dict(r)
        rec["id"] = rec.get("tower_id") or rec.get("id")
        rec["lat"] = rec.get("latitude")
        rec["lon"] = rec.get("longitude")
        formatted_towers.append(rec)

    return {
        "source": "OpenCellID",
        "count": selected_count,
        "accounting": accounting.model_dump(),
        "towers": formatted_towers,
        "cells": formatted_towers,
        "sites": sites,
        "tech_distribution": tech_dist,
        "center": {"latitude": center_lat, "longitude": center_lon},
        "radius_m": query_radius,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "cached": is_cached,
    }


@app.get("/api/towers")
async def get_towers(
    lat: float | None = Query(None, ge=-90.0, le=90.0, description="Center latitude in degrees"),
    lon: float | None = Query(None, ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_m: float = Query(1500.0, gt=0, le=5000.0, description="Search radius in metres"),
    west: float | None = Query(None, ge=-180.0, le=180.0, description="Bounding box west longitude"),
    south: float | None = Query(None, ge=-90.0, le=90.0, description="Bounding box south latitude"),
    east: float | None = Query(None, ge=-180.0, le=180.0, description="Bounding box east longitude"),
    north: float | None = Query(None, ge=-90.0, le=90.0, description="Bounding box north latitude"),
    radios: list[str] | None = Query(None, description="Radio technologies to include ('4G', '5G')"),
    limit: int = Query(50, ge=10, le=200, description="Maximum number of towers to select (10-200)"),
    aggregate_2m: bool = Query(False, description="Treat towers within 2 metre range as 1 tower"),
):
    """
    Fetch and validate tower records within the given radius or bounding box.
    Returns normalized tower records, accounting metadata, physical site entities, and data quality warnings.
    """
    # 1. Resolve geographic center and search radius
    if west is not None and south is not None and east is not None and north is not None:
        center_lat = (south + north) / 2.0
        center_lon = (west + east) / 2.0
        # Compute half diagonal as radius
        half_diag_m = haversine_distance(south, west, north, east) / 2.0
        query_radius = min(5000.0, max(500.0, half_diag_m))
    elif lat is not None and lon is not None:
        center_lat = lat
        center_lon = lon
        query_radius = radius_m
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either (lat, lon) or bounding box (west, south, east, north).",
        )

    # 2. Parse & validate radio filter
    active_radios = parse_radio_query(radios)

    # 3. Retrieve server-side API key
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
        )

    # 4. Ingest records via data_service
    cells, warnings, is_cached = await fetch_opencellid_records(
        center_lat, center_lon, query_radius, api_key
    )

    # 5. Process filtering, FPS sampling, site grouping, and accounting
    return _process_tower_records(
        cells=cells,
        center_lat=center_lat,
        center_lon=center_lon,
        query_radius=query_radius,
        active_radios=active_radios,
        limit=limit,
        warnings=warnings,
        is_cached=is_cached,
        aggregate_2m=aggregate_2m,
    )


@app.get("/api/cells")
async def get_cells(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Center latitude in degrees"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_m: float = Query(1000.0, gt=0, le=5000.0, description="Search radius in metres"),
    radios: list[str] | None = Query(None, description="Radio technologies to include ('4G', '5G')"),
    limit: int = Query(50, ge=10, le=200, description="Maximum number of towers to select (10-200)"),
    aggregate_2m: bool = Query(False, description="Treat towers within 2 metre range as 1 tower"),
):
    """
    Fetch nearby cell records from OpenCellID around (lat, lon) within radius_m.
    Maintains backward compatibility with original route while returning full accounting and sites.
    """
    active_radios = parse_radio_query(radios)

    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
        )

    cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

    return _process_tower_records(
        cells=cells,
        center_lat=lat,
        center_lon=lon,
        query_radius=radius_m,
        active_radios=active_radios,
        limit=limit,
        warnings=warnings,
        is_cached=is_cached,
        aggregate_2m=aggregate_2m,
    )


def _normalize_cell_inputs(cells_input: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize a list of CellRecord instances or dictionaries into uniform dictionaries."""
    if not cells_input:
        return []
    normalized: list[dict[str, Any]] = []
    for c in cells_input:
        if hasattr(c, "model_dump"):
            d = c.model_dump()
        elif isinstance(c, dict):
            d = dict(c)
        else:
            d = dict(c)
        tid = d.get("tower_id") or d.get("id")
        d["tower_id"] = str(tid) if tid else ""
        d["id"] = d["tower_id"]
        lat = d.get("latitude") if "latitude" in d else d.get("lat")
        lon = d.get("longitude") if "longitude" in d else d.get("lon")
        d["latitude"] = float(lat) if lat is not None else 0.0
        d["longitude"] = float(lon) if lon is not None else 0.0
        d["lat"] = d["latitude"]
        d["lon"] = d["longitude"]
        normalized.append(d)
    return normalized


@app.post("/api/graph/build")
async def build_graph_endpoint(request: GraphBuildRequest):
    """
    Construct undirected interference graph from tower records using documented overlap criterion:
        distance(u, v) <= radius(u) + radius(v)
    Returns serializable vertices, edges, and topological metrics.
    """
    raw_cells = _normalize_cell_inputs(request.cells or request.towers)
    warnings: list[str] = []

    # If cells are not directly provided, fetch using coordinates
    if not raw_cells or len(raw_cells) == 0:
        if request.center:
            api_key = _get_api_key()
            if not api_key:
                raise HTTPException(
                    status_code=503,
                    detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
                )
            fetched_cells, fetch_warnings, _ = await fetch_opencellid_records(
                request.center.latitude,
                request.center.longitude,
                request.radius_m,
                api_key,
            )
            raw_cells = _normalize_cell_inputs(fetched_cells)
            raw_cells = [c for c in raw_cells if normalize_radio_type(c.get("radio")) in ("4G", "5G")]
            warnings.extend(fetch_warnings)
        else:
            raise HTTPException(
                status_code=400,
                detail="No tower records or center coordinates provided to build graph.",
            )

    # Filter by specific tower IDs if requested
    if request.tower_ids:
        id_set = set(request.tower_ids)
        raw_cells = [c for c in raw_cells if (c.get("tower_id") in id_set or c.get("id") in id_set)]

    if getattr(request, "aggregate_2m", False):
        raw_cells = aggregate_towers_within_distance(raw_cells, 2.0)

    if not raw_cells:
        raise HTTPException(
            status_code=400,
            detail="Zero valid tower records available for graph construction.",
        )

    t0 = time.perf_counter()
    if request.radius_override_m is not None:
        graph = build_interference_graph(raw_cells, radius_override_m=request.radius_override_m)
    else:
        graph = build_interference_graph(raw_cells)
    build_time_ms = round((time.perf_counter() - t0) * 1000, 3)

    payload = serialize_graph_payload(graph)
    payload["build_runtime_ms"] = build_time_ms
    if payload.get("metrics", {}).get("data_unsuitable_reason"):
        warnings.append(payload["metrics"]["data_unsuitable_reason"])
    payload["warnings"] = warnings
    payload["diagnostics"] = payload.get("metrics")
    payload["educational_disclaimer"] = dict(EDUCATIONAL_DISCLAIMER_DEFAULT)

    return payload


@app.post("/api/optimize")
async def optimize_frequencies(request: OptimizeRequest):
    """
    Build interference graph and run DSatur and Welsh–Powell optimization.
    Validates assignments, compares metrics, and returns map-ready results.
    """
    raw_cells = _normalize_cell_inputs(request.cells or request.towers)
    radius_m = request.radius_m

    # 1. Use client-provided cell records if provided; otherwise fetch from OpenCellID
    if raw_cells and len(raw_cells) > 0:
        cells = raw_cells
        warnings = ["Simulated / demo cell grid."]
        is_cached = False
        if request.center:
            lat = request.center.latitude
            lon = request.center.longitude
        else:
            lat = cells[0]["latitude"]
            lon = cells[0]["longitude"]
    else:
        if not request.center:
            raise HTTPException(status_code=422, detail="Center coordinates required when cells are not provided.")
        lat = request.center.latitude
        lon = request.center.longitude
        api_key = _get_api_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
            )
        fetched, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)
        cells = _normalize_cell_inputs(fetched)
        cells = [c for c in cells if normalize_radio_type(c.get("radio")) in ("4G", "5G")]

    if getattr(request, "aggregate_2m", False):
        cells = aggregate_towers_within_distance(cells, 2.0)

    # 2. Build the interference graph and measure build time
    t0 = time.perf_counter()
    if request.radius_override_m is not None:
        graph = build_interference_graph(cells, radius_override_m=request.radius_override_m)
    else:
        graph = build_interference_graph(cells)
    graph_build_ms = round((time.perf_counter() - t0) * 1000, 3)

    # 3. Run frequency allocation and validation
    algo = (request.algorithm or "both").lower()

    if algo == "dsatur":
        dsatur_res = color_dsatur(graph)
        assignments = dsatur_res["coloring"]
        color_count = dsatur_res["color_count"]
        runtime_ms = dsatur_res["runtime_ms"]
        validation = dsatur_res["validation"]
        opt_results = {
            "metrics": get_graph_metrics(graph),
            "best_algorithm": "DSatur",
            "dsatur": dsatur_res,
            "welsh_powell": None,
            "exact": None,
        }
    elif algo in ("welsh_powell", "welsh-powell"):
        wp_res = color_welsh_powell(graph)
        assignments = wp_res["coloring"]
        color_count = wp_res["color_count"]
        runtime_ms = wp_res["runtime_ms"]
        validation = wp_res["validation"]
        opt_results = {
            "metrics": get_graph_metrics(graph),
            "best_algorithm": "Welsh-Powell",
            "dsatur": None,
            "welsh_powell": wp_res,
            "exact": None,
        }
    elif algo == "exact":
        exact_res = color_exact_dsatur_bnb(graph)
        assignments = exact_res["coloring"]
        color_count = exact_res["color_count"]
        runtime_ms = exact_res["runtime_ms"]
        validation = exact_res["validation"]
        opt_results = {
            "metrics": get_graph_metrics(graph),
            "best_algorithm": "Exact (B&B)",
            "dsatur": None,
            "welsh_powell": None,
            "exact": exact_res,
        }
    else:  # "both"
        opt_results = optimize_graph_frequencies(graph)
        # Default active assignments to DSatur
        assignments = opt_results["dsatur"]["coloring"]
        color_count = opt_results["dsatur"]["color_count"]
        runtime_ms = opt_results["dsatur"]["runtime_ms"]
        validation = opt_results["dsatur"]["validation"]

    # 4. Extract edge lines for visual map overlay
    edges = get_interference_edges(graph)
    result_id = uuid.uuid4().hex[:12]
    if opt_results["metrics"].get("data_unsuitable_reason"):
        warnings.append(opt_results["metrics"]["data_unsuitable_reason"])

    solver_diag = {}
    best_key = opt_results["best_algorithm"].lower().replace("-", "_").replace(" ", "_")
    if isinstance(opt_results.get(best_key), dict):
        solver_diag = opt_results[best_key].get("solver_diagnostics", {})

    return {
        "result_id": result_id,
        "center": {"latitude": lat, "longitude": lon},
        "radius_m": radius_m,
        "cached": is_cached,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "graph_build_runtime_ms": graph_build_ms,
        "algorithm": request.algorithm,
        "assignments": assignments,
        "colors_used": color_count,
        "chi_heuristic": color_count,
        "runtime_ms": runtime_ms,
        "metrics": opt_results["metrics"],
        "diagnostics": opt_results["metrics"],
        "best_algorithm": opt_results["best_algorithm"],
        "solver_diagnostics": solver_diag,
        "dsatur": opt_results["dsatur"],
        "welsh_powell": opt_results["welsh_powell"],
        "exact": opt_results["exact"],
        "validation": validation,
        "edges": edges,
        "educational_disclaimer": dict(EDUCATIONAL_DISCLAIMER_DEFAULT),
    }


@app.post("/api/compare")
async def compare_algorithms_endpoint(request: CompareRequest):
    """
    Run DSatur and Welsh–Powell on the exact same graph and return side-by-side comparison.
    """
    radius_m = request.radius_m

    raw_cells = _normalize_cell_inputs(request.cells or request.towers)
    if raw_cells and len(raw_cells) > 0:
        cells = raw_cells
        warnings = ["Simulated / demo cell grid."]
        is_cached = False
        if request.center:
            lat = request.center.latitude
            lon = request.center.longitude
        else:
            lat = cells[0]["latitude"]
            lon = cells[0]["longitude"]
    else:
        if not request.center:
            raise HTTPException(status_code=422, detail="Center coordinates required when cells are not provided.")
        lat = request.center.latitude
        lon = request.center.longitude
        api_key = _get_api_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
            )
        fetched, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)
        cells = _normalize_cell_inputs(fetched)
        cells = [c for c in cells if normalize_radio_type(c.get("radio")) in ("4G", "5G")]

    if getattr(request, "aggregate_2m", False):
        cells = aggregate_towers_within_distance(cells, 2.0)

    # Build the single graph shared by both algorithms
    if request.radius_override_m is not None:
        graph = build_interference_graph(cells, radius_override_m=request.radius_override_m)
    else:
        graph = build_interference_graph(cells)
    metrics = get_graph_metrics(graph)

    dsatur_res = color_dsatur(graph)
    wp_res = color_welsh_powell(graph)

    exact_res = None
    if graph.number_of_nodes() <= 25:
        exact_res = color_exact_dsatur_bnb(graph)

    # Comparative analysis
    color_diff = dsatur_res["color_count"] - wp_res["color_count"]
    if color_diff < 0:
        summary = f"DSatur used {-color_diff} fewer frequency channel(s) than Welsh–Powell by dynamically prioritizing saturated vertices."
    elif color_diff > 0:
        summary = f"Welsh–Powell used {color_diff} fewer frequency channel(s) than DSatur on this specific topology."
    else:
        summary = f"Both DSatur and Welsh–Powell achieved the identical color count ({dsatur_res['color_count']} channels)."

    if metrics.get("data_unsuitable_reason"):
        warnings.append(metrics["data_unsuitable_reason"])

    return {
        "metrics": metrics,
        "diagnostics": metrics,
        "dsatur": dsatur_res,
        "welsh_powell": wp_res,
        "exact": exact_res,
        "agreement": (dsatur_res["color_count"] == wp_res["color_count"]),
        "comparison": {
            "colors_difference": color_diff,
            "faster_heuristic": "Welsh-Powell" if wp_res["runtime_ms"] < dsatur_res["runtime_ms"] else "DSatur",
            "fewer_colors_heuristic": "DSatur" if color_diff <= 0 else "Welsh-Powell",
            "summary": summary,
        },
        "edges": get_interference_edges(graph),
        "warnings": warnings,
        "educational_disclaimer": dict(EDUCATIONAL_DISCLAIMER_DEFAULT),
    }