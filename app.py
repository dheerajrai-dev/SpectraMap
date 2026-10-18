"""
app.py — SpectraMap FastAPI application

Serves the static frontend and exposes the JSON API.
API routes:
    GET  /api/status   — Application readiness
    GET  /api/cells    — Nearby cell records for given lat/lon and radius
    POST /api/optimize — Run graph coloring algorithms (Phase 5)
"""

import os
import time
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from data_service import fetch_opencellid_records, ATTRIBUTION_TEXT
from graph_engine import (
    build_interference_graph,
    optimize_graph_frequencies,
    get_interference_edges,
)
from schemas import OptimizeRequest

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="SpectraMap", version="1.0-dev")

# Serve frontend static assets under the /static URL prefix
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """Serve the frontend HTML page."""
    return FileResponse("static/index.html")


@app.get("/api/status")
async def get_status():
    """Health check endpoint returning application readiness."""
    return {
        "status": "ok",
        "app": "SpectraMap",
        "version": "1.0-dev",
    }


@app.get("/api/cells")
async def get_cells(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Center latitude in degrees"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_m: float = Query(1000.0, gt=0, le=5000.0, description="Search radius in metres"),
):
    """
    Fetch nearby cell records from OpenCellID around (lat, lon) within radius_m.
    Validates input parameters, checks API credentials, and returns normalized cells.
    """
    # 1. Retrieve the server-side API key from environment variables
    api_key = os.getenv("OPENCELLID_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
        )

    # 2. Fetch and filter records via data_service (with caching and fallback)
    cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

    # 3. Return standardized API response
    return {
        "center": {"latitude": lat, "longitude": lon},
        "radius_m": radius_m,
        "count": len(cells),
        "cells": cells,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "cached": is_cached,
    }


@app.post("/api/optimize")
async def optimize_frequencies(request: OptimizeRequest):
    """
    Build interference graph and run DSatur and Welsh–Powell optimization.
    Validates assignments, compares metrics, and returns map-ready results.
    """
    lat = request.center.latitude
    lon = request.center.longitude
    radius_m = request.radius_m

    # 1. Use client-provided cell records if provided (e.g. demo grid); otherwise fetch from OpenCellID
    if request.cells and len(request.cells) > 0:
        cells = request.cells
        warnings = ["Simulated / demo cell grid."]
        is_cached = False
    else:
        api_key = os.getenv("OPENCELLID_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OpenCellID API key is not configured on the server. Please set OPENCELLID_API_KEY in .env.",
            )
        cells, warnings, is_cached = await fetch_opencellid_records(lat, lon, radius_m, api_key)

    # 2. Build the interference graph and measure build time
    t0 = time.perf_counter()
    graph = build_interference_graph(cells)
    graph_build_ms = round((time.perf_counter() - t0) * 1000, 3)

    # 3. Run dual-algorithm frequency allocation and validation
    opt_results = optimize_graph_frequencies(graph)

    # 4. Extract edge lines for visual map overlay
    edges = get_interference_edges(graph)

    result_id = uuid.uuid4().hex[:12]

    return {
        "result_id": result_id,
        "center": {"latitude": lat, "longitude": lon},
        "radius_m": radius_m,
        "cached": is_cached,
        "warnings": warnings,
        "attribution": ATTRIBUTION_TEXT,
        "graph_build_runtime_ms": graph_build_ms,
        "metrics": opt_results["metrics"],
        "best_algorithm": opt_results["best_algorithm"],
        "dsatur": opt_results["dsatur"],
        "welsh_powell": opt_results["welsh_powell"],
        "exact": opt_results["exact"],
        "edges": edges,
    }