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
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from data_service import (
    fetch_opencellid_records,
    haversine_distance,
    ATTRIBUTION_TEXT,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    validate_coloring,
    optimize_graph_frequencies,
    get_graph_metrics,
    get_interference_edges,
    serialize_graph_payload,
)
from schemas import (
    CenterCoordinates,
    GraphBuildRequest,
    OptimizeRequest,
    CompareRequest,
)

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="SpectraMap",
    version="2.0",
    description="Spatial Graph Coloring for Cellular Frequency Optimization",
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


@app.get("/api/towers")
async def get_towers(
    lat: float | None = Query(None, ge=-90.0, le=90.0, description="Center latitude in degrees"),
    lon: float | None = Query(None, ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_m: float = Query(1500.0, gt=0, le=5000.0, description="Search radius in metres"),
    west: float | None = Query(None, ge=-180.0, le=180.0, description="Bounding box west longitude"),
    south: float | None = Query(None, ge=-90.0, le=90.0, description="Bounding box south latitude"),
    east: float | None = Query(None, ge=-180.0, le=180.0, description="Bounding box east longitude"),
    north: float | None = Query(None, ge=-90.0, le=90.0, description="Bounding box north latitude"),
):
    """
    Fetch and validate tower records within the given radius or bounding box.
    Returns normalized tower records, source metadata, and data quality warnings.
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

    # 2. Retrieve server-side API key
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
        )

    # 3. Ingest and normalize records via data_service
    cells, warnings, is_cached = await fetch_opencellid_records(
        center_lat, center_lon, query_radius, api_key
    )

    # Standardize records to include both id and tower_id
    towers: list[dict[str, Any]] = []
    for c in cells:
        rec = dict(c)
        rec["id"] = rec.get("tower_id") or rec.get("id")
        rec["lat"] = rec.get("latitude")
        rec["lon"] = rec.get("longitude")
        towers.append(rec)

    return {
        "source": "OpenCellID",
        "count": len(towers),
        "towers": towers,
        "cells": towers,
        "center": {"latitude": center_lat, "longitude": center_lon},
        "radius_m": query_radius,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "cached": is_cached,
    }


@app.get("/api/cells")
async def get_cells(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Center latitude in degrees"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_m: float = Query(1000.0, gt=0, le=5000.0, description="Search radius in metres"),
):
    """
    Fetch nearby cell records from OpenCellID around (lat, lon) within radius_m.
    Maintains backward compatibility with original route.
    """
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
        )

    cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

    towers: list[dict[str, Any]] = []
    for c in cells:
        rec = dict(c)
        rec["id"] = rec.get("tower_id") or rec.get("id")
        rec["lat"] = rec.get("latitude")
        rec["lon"] = rec.get("longitude")
        towers.append(rec)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "radius_m": radius_m,
        "count": len(towers),
        "cells": towers,
        "towers": towers,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "cached": is_cached,
    }


@app.post("/api/graph/build")
async def build_graph_endpoint(request: GraphBuildRequest):
    """
    Construct undirected interference graph from tower records using documented overlap criterion:
        distance(u, v) <= radius(u) + radius(v)
    Returns serializable vertices, edges, and topological metrics.
    """
    raw_cells = request.cells or request.towers
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
            raw_cells, fetch_warnings, _ = await fetch_opencellid_records(
                request.center.latitude,
                request.center.longitude,
                request.radius_m,
                api_key,
            )
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

    return payload


@app.post("/api/optimize")
async def optimize_frequencies(request: OptimizeRequest):
    """
    Build interference graph and run DSatur and Welsh–Powell optimization.
    Validates assignments, compares metrics, and returns map-ready results.
    """
    lat = request.center.latitude
    lon = request.center.longitude
    radius_m = request.radius_m

    # 1. Use client-provided cell records if provided; otherwise fetch from OpenCellID
    raw_cells = request.cells or request.towers
    if raw_cells and len(raw_cells) > 0:
        cells = raw_cells
        warnings = ["Simulated / demo cell grid."]
        is_cached = False
    else:
        api_key = _get_api_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
            )
        cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

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
        "metrics": opt_results["metrics"],
        "diagnostics": opt_results["metrics"],
        "best_algorithm": opt_results["best_algorithm"],
        "dsatur": opt_results["dsatur"],
        "welsh_powell": opt_results["welsh_powell"],
        "exact": opt_results["exact"],
        "validation": validation,
        "edges": edges,
    }


@app.post("/api/compare")
async def compare_algorithms_endpoint(request: CompareRequest):
    """
    Run DSatur and Welsh–Powell on the exact same graph and return side-by-side comparison.
    """
    lat = request.center.latitude
    lon = request.center.longitude
    radius_m = request.radius_m

    raw_cells = request.cells or request.towers
    if raw_cells and len(raw_cells) > 0:
        cells = raw_cells
        warnings = ["Simulated / demo cell grid."]
        is_cached = False
    else:
        api_key = _get_api_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
            )
        cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

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
        "comparison": {
            "colors_difference": color_diff,
            "faster_heuristic": "Welsh-Powell" if wp_res["runtime_ms"] < dsatur_res["runtime_ms"] else "DSatur",
            "fewer_colors_heuristic": "DSatur" if color_diff <= 0 else "Welsh-Powell",
            "summary": summary,
        },
        "edges": get_interference_edges(graph),
        "warnings": warnings,
    }