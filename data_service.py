"""
data_service.py — OpenCellID data fetching, normalization, and cache
"""

from datetime import datetime, timezone
import math
from typing import Any

# Mean radius of Earth in metres used for great-circle distance calculations
EARTH_RADIUS_METRES = 6_371_000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two coordinates in metres.
    Uses the Haversine formula on a spherical Earth (radius 6,371,000 m).
    """
    # Convert latitude and longitude from decimal degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Compute angular separation using the Haversine formula
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Clamp to [0.0, 1.0] to protect against floating-point precision errors in sqrt
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    # Multiply angular distance by Earth's radius to get metres
    return EARTH_RADIUS_METRES * c


def calculate_bounding_box(
    center_lat: float, center_lon: float, radius_m: float
) -> tuple[float, float, float, float]:
    """
    Compute bounding box (latmin, lonmin, latmax, lonmax) encompassing radius_m.
    Accounts for meridian convergence (longitude degree length = 111,139 * cos(lat)).
    """
    # 1 deg latitude ≈ 111,139m everywhere; longitude degree width scales with cos(lat)
    delta_lat = radius_m / 111_139.0
    lat_rad = math.radians(center_lat)
    cos_lat = math.cos(lat_rad)
    delta_lon = radius_m / (111_139.0 * cos_lat) if abs(cos_lat) > 1e-6 else radius_m / 111_139.0

    # Build the rectangular boundary box
    latmin = max(-90.0, center_lat - delta_lat)
    latmax = min(90.0, center_lat + delta_lat)
    lonmin = max(-180.0, center_lon - delta_lon)
    lonmax = min(180.0, center_lon + delta_lon)

    return latmin, lonmin, latmax, lonmax


def filter_records_by_radius(
    records: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> list[dict[str, Any]]:
    """
    Filter normalized records to those within radius_m of (center_lat, center_lon).
    """
    # Keep only records whose true great-circle distance is within the search circle
    return [
        r for r in records
        if haversine_distance(center_lat, center_lon, r["latitude"], r["longitude"]) <= radius_m
    ]


def validate_cell_record(raw: dict[str, Any]) -> bool:
    """
    Validate that a raw OpenCellID cell record contains necessary, valid data.

    Explicit policy:
    - Must have numeric 'lat' in [-90, 90].
    - Must have numeric 'lon' in [-180, 180].
    - Must have positive numeric 'range' (in metres). Records with missing, zero,
      or negative range are rejected to prevent invented propagation models.
    - Must have a valid 'cellid'.
    """
    if not isinstance(raw, dict):
        return False

    try:
        lat = float(raw["lat"])
        lon = float(raw["lon"])
        rng = float(raw["range"])
        cell_id = raw.get("cellid")

        if cell_id is None:
            return False

        # Reject out-of-bounds GPS coordinates or non-positive radio ranges
        if not (-90.0 <= lat <= 90.0):
            return False
        if not (-180.0 <= lon <= 180.0):
            return False
        if rng <= 0:
            return False

        return True
    except (KeyError, TypeError, ValueError):
        # Return False cleanly if types cannot be cast to numbers
        return False


def normalize_cell_record(raw: dict[str, Any], retrieved_at: str | None = None) -> dict[str, Any]:
    """
    Transform a raw OpenCellID record into SpectraMap's standard internal schema.
    """
    if not validate_cell_record(raw):
        raise ValueError(f"Cannot normalize invalid cell record: {raw}")

    radio = str(raw.get("radio", "UNKNOWN")).upper()
    mcc = int(raw["mcc"]) if raw.get("mcc") is not None else None
    mnc = int(raw["mnc"]) if raw.get("mnc") is not None else None
    area = int(raw.get("lac") or raw.get("tac") or 0)
    cell_id = int(raw["cellid"])

    # Combine network parameters into a globally unique vertex identifier
    tower_id = f"{radio}_{mcc}_{mnc}_{area}_{cell_id}"
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()

    return {
        "tower_id": tower_id,
        "latitude": float(raw["lat"]),
        "longitude": float(raw["lon"]),
        "range_m": float(raw["range"]),
        "radio": radio,
        "mcc": mcc,
        "mnc": mnc,
        "area": area,
        "cell_id": cell_id,
        "source": "OpenCellID",
        "retrieved_at": timestamp,
    }


def parse_opencellid_response(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse an OpenCellID response payload, returning (normalized_records, warnings).
    Handles empty responses, error messages, and skips malformed records.
    """
    warnings: list[str] = []
    records: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return [], ["Invalid response format: payload must be a JSON object."]

    # Check for provider-level error messages (such as quota exhaustion)
    if payload.get("status") == "error":
        msg = payload.get("message", "Unknown error from OpenCellID.")
        return [], [f"OpenCellID error: {msg}"]

    raw_cells = payload.get("cells", [])
    if not isinstance(raw_cells, list):
        return [], ["Invalid response format: 'cells' must be a list."]

    retrieved_at = datetime.now(timezone.utc).isoformat()
    # Normalize valid cells; log warnings for malformed or rejected records
    for raw in raw_cells:
        if validate_cell_record(raw):
            records.append(normalize_cell_record(raw, retrieved_at=retrieved_at))
        else:
            warnings.append(f"Rejected invalid cell record: cellid={raw.get('cellid')}")

    return records, warnings
