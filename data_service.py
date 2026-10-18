"""
data_service.py — OpenCellID data fetching, normalization, and cache
"""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any
import httpx

# Mean radius of Earth in metres used for great-circle distance calculations
EARTH_RADIUS_METRES = 6_371_000.0
OPENCELLID_AREA_URL = "https://opencellid.org/cell/getInArea"
ATTRIBUTION_TEXT = "Cell tower data from OpenCellID, licensed under CC BY-SA 4.0."


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


def split_bounding_box(
    latmin: float,
    lonmin: float,
    latmax: float,
    lonmax: float,
    max_tile_span_m: float = 1900.0,
) -> list[tuple[float, float, float, float]]:
    """
    Subdivide a bounding box into safe sub-tiles if its dimensions exceed max_tile_span_m.
    Ensures that each tile's area is strictly under OpenCellID's 4,000,000 sq. metre limit.
    """
    mid_lat = (latmin + latmax) / 2.0
    lat_span_m = (latmax - latmin) * 111_139.0
    lon_span_m = (lonmax - lonmin) * 111_139.0 * math.cos(math.radians(mid_lat))

    num_lat = max(1, math.ceil(lat_span_m / max_tile_span_m))
    num_lon = max(1, math.ceil(lon_span_m / max_tile_span_m))

    if num_lat == 1 and num_lon == 1:
        return [(latmin, lonmin, latmax, lonmax)]

    tiles = []
    d_lat = (latmax - latmin) / num_lat
    d_lon = (lonmax - lonmin) / num_lon

    for i in range(num_lat):
        t_latmin = round(latmin + i * d_lat, 4)
        t_latmax = round(latmin + (i + 1) * d_lat, 4)
        for j in range(num_lon):
            t_lonmin = round(lonmin + j * d_lon, 4)
            t_lonmax = round(lonmin + (j + 1) * d_lon, 4)
            tiles.append((t_latmin, t_lonmin, t_latmax, t_lonmax))

    return tiles


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


def get_cache_filepath(bbox_str: str, cache_dir: Path | str = "data") -> Path:
    """Return local cache file path for a given bounding box string."""
    safe_name = f"cache_{bbox_str.replace(',', '_')}.json"
    return Path(cache_dir) / safe_name


def save_cache(
    bbox_str: str,
    records: list[dict[str, Any]],
    is_partial: bool = False,
    cache_dir: Path | str = "data",
) -> Path | None:
    """Save normalized records and area metadata to disk."""
    try:
        dir_path = Path(cache_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = get_cache_filepath(bbox_str, cache_dir=dir_path)

        data = {
            "bbox": bbox_str,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "OpenCellID",
            "record_count": len(records),
            "is_partial": is_partial,
            "records": records,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return file_path
    except OSError:
        return None


def load_cache(
    bbox_str: str,
    max_age_seconds: float | None = 86400,
    cache_dir: Path | str = "data",
) -> dict[str, Any] | None:
    """
    Load cached records if file exists and is within max_age_seconds.
    Returns parsed dictionary or None.
    """
    file_path = get_cache_filepath(bbox_str, cache_dir=cache_dir)
    if not file_path.exists():
        return None

    try:
        # Check cache age if max_age_seconds is specified
        if max_age_seconds is not None:
            age = datetime.now().timestamp() - file_path.stat().st_mtime
            if age > max_age_seconds:
                return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_cache_fallback(
    bbox_str: str,
    cache_dir: Path | str = "data",
) -> dict[str, Any] | None:
    """Load cached records regardless of file age as a resilient fallback."""
    return load_cache(bbox_str, max_age_seconds=None, cache_dir=cache_dir)


async def fetch_opencellid_records(
    center_lat: float,
    center_lon: float,
    radius_m: float,
    api_key: str,
    client: httpx.AsyncClient | None = None,
    cache_dir: str = "data",
    cache_ttl_seconds: float = 86400.0,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """
    Fetch, parse, and radius-filter cell records from OpenCellID around a geographic center.
    Uses sub-grid tiling to avoid OpenCellID's 4 km² limit for larger radii, with caching and fallback.
    Returns (records, warnings, is_cached).
    """
    # 1. Calculate bounding box for the requested radius
    latmin, lonmin, latmax, lonmax = calculate_bounding_box(center_lat, center_lon, radius_m)
    bbox_str = f"{latmin:.4f},{lonmin:.4f},{latmax:.4f},{lonmax:.4f}"

    # 2. Check for fresh cached data before hitting the network
    cached_payload = load_cache(bbox_str, max_age_seconds=cache_ttl_seconds, cache_dir=cache_dir)
    if cached_payload and "records" in cached_payload:
        records = cached_payload["records"]
        filtered = filter_records_by_radius(records, center_lat, center_lon, radius_m)
        result = filtered if filtered else records
        warnings: list[str] = []
        if cached_payload.get("is_partial"):
            warnings.append("Cached records represent a partial area query.")
        return result, warnings, True

    # 3. For radius <= 1000m, use a safe single tile; for larger radii, subdivide into tiles
    if radius_m <= 1000.0:
        # Clamp slightly to 985m so 4-decimal rounding never exceeds 4,000,000 sq m
        s_latmin, s_lonmin, s_latmax, s_lonmax = calculate_bounding_box(center_lat, center_lon, min(radius_m, 985.0))
        tiles = [(round(s_latmin, 4), round(s_lonmin, 4), round(s_latmax, 4), round(s_lonmax, 4))]
    else:
        tiles = split_bounding_box(latmin, lonmin, latmax, lonmax, max_tile_span_m=1900.0)

    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        should_close = True

    warnings: list[str] = []
    merged_records: dict[str, dict[str, Any]] = {}
    is_partial = False
    any_fresh = False

    try:
        for t_latmin, t_lonmin, t_latmax, t_lonmax in tiles:
            tile_bbox = f"{t_latmin:.4f},{t_lonmin:.4f},{t_latmax:.4f},{t_lonmax:.4f}"

            # Check individual tile cache first
            tile_cached = load_cache(tile_bbox, max_age_seconds=cache_ttl_seconds, cache_dir=cache_dir)
            if tile_cached and "records" in tile_cached:
                for r in tile_cached["records"]:
                    merged_records[r["tower_id"]] = r
                if tile_cached.get("is_partial"):
                    is_partial = True
                continue

            # Query OpenCellID for this tile
            any_fresh = True
            params = {
                "key": api_key,
                "BBOX": tile_bbox,
                "format": "json",
            }
            try:
                response = await client.get(OPENCELLID_AREA_URL, params=params)
                if response.status_code == 200:
                    payload = response.json()
                    tile_recs, tile_warns = parse_opencellid_response(payload)
                    warnings.extend(tile_warns)

                    tile_partial = len(payload.get("cells", [])) >= 50
                    if tile_partial:
                        is_partial = True

                    save_cache(tile_bbox, tile_recs, is_partial=tile_partial, cache_dir=cache_dir)
                    for r in tile_recs:
                        merged_records[r["tower_id"]] = r
                else:
                    error_msg = f"OpenCellID HTTP {response.status_code}: {response.text}"
                    fb = load_cache_fallback(tile_bbox, cache_dir=cache_dir)
                    if fb and "records" in fb:
                        for r in fb["records"]:
                            merged_records[r["tower_id"]] = r
                    else:
                        warnings.append(error_msg)
            except (httpx.RequestError, ValueError) as exc:
                error_msg = f"OpenCellID connection error: {str(exc)}"
                fb = load_cache_fallback(tile_bbox, cache_dir=cache_dir)
                if fb and "records" in fb:
                    for r in fb["records"]:
                        merged_records[r["tower_id"]] = r
                else:
                    warnings.append(error_msg)

        all_records = list(merged_records.values())

        # If network calls failed and no records gathered, try full bounding box fallback
        if not all_records:
            fallback = load_cache_fallback(bbox_str, cache_dir=cache_dir)
            if fallback and "records" in fallback:
                filtered = filter_records_by_radius(fallback["records"], center_lat, center_lon, radius_m)
                time_str = fallback.get("retrieved_at", "unknown date")
                return filtered, [f"Serving cached fallback from {time_str}."], True
            return [], warnings, False

        if is_partial and "Reached OpenCellID 50-record limit for area query; results may be partial." not in warnings:
            warnings.append("Reached OpenCellID 50-record limit for area query; results may be partial.")

        # Save merged bounding box cache
        save_cache(bbox_str, all_records, is_partial=is_partial, cache_dir=cache_dir)

        # Filter strictly within search radius
        filtered = filter_records_by_radius(all_records, center_lat, center_lon, radius_m)

        # Fallback: if radius filter yields 0 but towers exist in the bounding box, show all towers!
        if not filtered and all_records:
            warnings.append(f"No towers strictly inside {radius_m}m radius; displaying {len(all_records)} nearby towers in the query area.")
            return all_records, warnings, not any_fresh

        return filtered, warnings, not any_fresh
    finally:
        if should_close:
            await client.aclose()



