"""
schemas.py — Pydantic models for API request validation

These classes define the expected shape of incoming JSON requests.
FastAPI uses them to automatically validate data types and geographic bounds.
"""

from typing import Any
from pydantic import BaseModel, Field


class CenterCoordinates(BaseModel):
    """Geographic center point (latitude and longitude)."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in degrees (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in degrees (-180 to 180)")


class OptimizeRequest(BaseModel):
    """Request body sent by the frontend when clicking 'Optimize Frequencies'."""
    center: CenterCoordinates
    radius_m: float = Field(1000.0, gt=0, le=5000.0, description="Search radius in metres (max 5000m)")
    cells: list[dict[str, Any]] | None = Field(default=None, description="Optional cell records list (for demo or pre-filtered grid)")
