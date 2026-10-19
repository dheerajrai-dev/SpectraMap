"""
schemas.py — Pydantic models for API request and response validation

Defines the expected shape of incoming JSON requests for:
- Coordinates
- Tower fetching
- Graph construction
- Frequency optimization & comparison
"""

from typing import Any
from pydantic import BaseModel, Field


class CenterCoordinates(BaseModel):
    """Geographic center point (latitude and longitude)."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in degrees (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in degrees (-180 to 180)")


class GraphBuildRequest(BaseModel):
    """Request payload for POST /api/graph/build."""
    center: CenterCoordinates | None = Field(default=None, description="Center coordinate")
    radius_m: float = Field(default=1500.0, gt=0, le=10000.0, description="Search radius in metres")
    cells: list[dict[str, Any]] | None = Field(default=None, description="Cell/tower records")
    towers: list[dict[str, Any]] | None = Field(default=None, description="Alias for cells")
    tower_ids: list[str] | None = Field(default=None, description="Optional subset of tower IDs to include")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")


class OptimizeRequest(BaseModel):
    """Request payload for POST /api/optimize."""
    center: CenterCoordinates = Field(..., description="Geographic center point")
    radius_m: float = Field(default=1000.0, gt=0, le=5000.0, description="Search radius in metres (max 5000m)")
    cells: list[dict[str, Any]] | None = Field(default=None, description="Optional cell records list (for demo or pre-filtered grid)")
    towers: list[dict[str, Any]] | None = Field(default=None, description="Alias for cells")
    algorithm: str = Field(default="both", description="Coloring algorithm: dsatur, welsh_powell, both, exact")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")


class CompareRequest(BaseModel):
    """Request payload for POST /api/compare."""
    center: CenterCoordinates = Field(..., description="Geographic center point")
    radius_m: float = Field(default=1000.0, gt=0, le=5000.0, description="Search radius in metres (max 5000m)")
    cells: list[dict[str, Any]] | None = Field(default=None, description="Optional cell records list (for demo or pre-filtered grid)")
    towers: list[dict[str, Any]] | None = Field(default=None, description="Alias for cells")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")
