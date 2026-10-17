"""
app.py — SpectraMap FastAPI application

Responsibilities:
- Serves the static frontend (HTML, CSS, JS) from the /static directory.
- Exposes the JSON API endpoints:
    GET  /api/status   — readiness and cache state
    GET  /api/cells    — fetch nearby cell records for a given center + radius
    POST /api/optimize — build interference graph, run both algorithms, validate

Implementation: Phase 2 (backend fundamentals) and onwards.
"""
