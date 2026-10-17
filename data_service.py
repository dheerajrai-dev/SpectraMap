"""
data_service.py — OpenCellID data fetching, normalization, and cache
"""

from datetime import datetime, timezone
from typing import Any


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

        if not (-90.0 <= lat <= 90.0):
            return False
        if not (-180.0 <= lon <= 180.0):
            return False
        if rng <= 0:
            return False

        return True
    except (KeyError, TypeError, ValueError):
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

    if payload.get("status") == "error":
        msg = payload.get("message", "Unknown error from OpenCellID.")
        return [], [f"OpenCellID error: {msg}"]

    raw_cells = payload.get("cells", [])
    if not isinstance(raw_cells, list):
        return [], ["Invalid response format: 'cells' must be a list."]

    retrieved_at = datetime.now(timezone.utc).isoformat()
    for raw in raw_cells:
        if validate_cell_record(raw):
            records.append(normalize_cell_record(raw, retrieved_at=retrieved_at))
        else:
            warnings.append(f"Rejected invalid cell record: cellid={raw.get('cellid')}")

    return records, warnings
