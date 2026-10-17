"""
app.py — SpectraMap FastAPI application

Serves the static frontend and exposes the JSON API.
API routes added per phase:
    GET  /api/status   — Phase 2 (this file)
    GET  /api/cells    — Phase 3
    POST /api/optimize — Phase 5
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="SpectraMap", version="1.0-dev")

# Serve static/ under the /static URL prefix.
# e.g. static/style.css → http://localhost:8000/static/style.css
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """Serve the frontend page."""
    return FileResponse("static/index.html")


@app.get("/api/status")
async def get_status():
    """
    Health check. Returns application readiness.
    Later phases will add cache state and data-source connectivity.
    """
    return {
        "status": "ok",
        "app": "SpectraMap",
        "version": "1.0-dev",
    }