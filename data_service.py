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

# Canonical Radio Technologies
RADIO_4G = "4G"
RADIO_5G = "5G"
VALID_RADIOS: set[str] = {RADIO_4G, RADIO_5G}

# Robust mapping table from raw cellular identifiers to canonical technologies
RADIO_SYNONYM_MAP: dict[str, str] = {
    # 4G LTE variants
    "LTE": RADIO_4G,
    "4G": RADIO_4G,
    "4G LTE": RADIO_4G,
    "4G-LTE": RADIO_4G,
    "4GLTE": RADIO_4G,
    "EUTRAN": RADIO_4G,
    "E-UTRAN": RADIO_4G,
    "E UTRAN": RADIO_4G,
    "LTE-M": RADIO_4G,
    # 5G NR variants
    "NR": RADIO_5G,
    "5G": RADIO_5G,
    "5G NR": RADIO_5G,
    "5G-NR": RADIO_5G,
    "5GNR": RADIO_5G,
}

# 4-tier coverage radii fallback hierarchy (survey_math_spec §3, decision.md Decision 6)
RADIO_FALLBACK_RADII: dict[str, float] = {
    RADIO_4G: 800.0,
    RADIO_5G: 500.0,
    "LTE": 800.0,
    "NR": 500.0,
}
DEFAULT_FALLBACK_RADIUS: float = 800.0
MIN_VALID_RANGE_M: float = 50.0
MAX_VALID_RANGE_M: float = 10_000.0


def normalize_radio_type(raw_radio: Any) -> str | None:
    """
    Normalize raw radio technology string to canonical '4G' or '5G'.

    Accepts:
        - 4G variants: LTE, 4G, 4G LTE, 4G-LTE, EUTRAN, E-UTRAN, LTE-M
        - 5G variants: NR, 5G, 5G NR, 5G-NR, 5GNR
    Rejects:
        - 2G variants: GSM, 2G, CDMA, GPRS, EDGE
        - 3G variants: UMTS, 3G, WCDMA, HSPA
        - Other: satellite, wifi, unknown, whitespace, empty, None

    Returns:
        '4G', '5G', or None if rejected/unrecognized.
    """
    if raw_radio is None:
        return None
    val = str(raw_radio).strip().upper()
    if not val:
        return None

    # 1. Direct dictionary match
    if val in RADIO_SYNONYM_MAP:
        return RADIO_SYNONYM_MAP[val]

    # 2. Normalized whitespace & punctuation match
    cleaned = val.replace("-", " ")
    cleaned = " ".join(cleaned.split())
    if cleaned in RADIO_SYNONYM_MAP:
        return RADIO_SYNONYM_MAP[cleaned]

    return None


def filter_records_by_radio(
    records: list[dict[str, Any]],
    allowed_radios: set[str] | list[str],
) -> list[dict[str, Any]]:
    """
    Filter a list of cell records to those matching the allowed canonical technologies.
    """
    allowed_set = {str(r).strip().upper() for r in allowed_radios}
    normalized_allowed = {normalize_radio_type(r) or r for r in allowed_set}
    return [
        r for r in records
        if (normalize_radio_type(r.get("radio")) or str(r.get("radio")).upper()) in normalized_allowed
    ]



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

    # Polar singularity protection: when approaching poles (|lat| >= 89.9 deg or |cos_lat| <= 1e-6),
    # meridian convergence causes longitude span to cover the entire globe [-180.0, 180.0].
    if abs(cos_lat) > 1e-6 and abs(center_lat) < 89.9:
        delta_lon = radius_m / (111_139.0 * cos_lat)
        lonmin = max(-180.0, center_lon - delta_lon)
        lonmax = min(180.0, center_lon + delta_lon)
    else:
        lonmin = -180.0
        lonmax = 180.0

    # Build the rectangular boundary box
    latmin = max(-90.0, center_lat - delta_lat)
    latmax = min(90.0, center_lat + delta_lat)

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
    Validate that a raw OpenCellID cell record contains valid geographic coordinates and identifier.

    Explicit policy (Phase 1 / survey_math_spec §3):
    - Must be a dictionary.
    - Must have numeric 'lat' in [-90.0, 90.0].
    - Must have numeric 'lon' in [-180.0, 180.0].
    - Must have a valid 'cellid' (not None, convertible to int).
    - Missing, zero, negative, or non-numeric 'range' is ALLOWED here so that
      normalize_cell_record can apply the deterministic 4-tier fallback hierarchy
      rather than dropping physically valid transmitter locations.
    """
    if not isinstance(raw, dict):
        return False

    try:
        cell_id = raw.get("cellid")
        if cell_id is None:
            return False
        # Ensure cellid can be converted to int
        int(cell_id)

        lat = float(raw["lat"])
        lon = float(raw["lon"])

        if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
            return False

        # Reject out-of-bounds GPS coordinates
        if not (-90.0 <= lat <= 90.0):
            return False
        if not (-180.0 <= lon <= 180.0):
            return False

        return True
    except (KeyError, TypeError, ValueError):
        # Return False cleanly if types cannot be cast to numbers
        return False


def normalize_cell_record(
    raw: dict[str, Any],
    retrieved_at: str | None = None,
    strict_radio: bool = False,
) -> dict[str, Any]:
    """
    Transform a raw OpenCellID record into SpectraMap's standard internal schema,
    strictly normalizing radio technology to '4G' or '5G' and applying the
    coverage radii fallback hierarchy.

    Args:
        raw: Raw OpenCellID cell dictionary.
        retrieved_at: Optional ISO timestamp.
        strict_radio: When True, raises ValueError if radio is not modern 4G or 5G.

    Raises:
        ValueError: If record fails basic validation or radio is not modern 4G/5G under strict_radio=True.
    """
    if not validate_cell_record(raw):
        raise ValueError(f"Cannot normalize invalid cell record: {raw}")

    raw_radio = raw.get("radio")
    canonical_radio = normalize_radio_type(raw_radio)

    if canonical_radio is None:
        if strict_radio:
            raise ValueError(
                f"Cannot normalize cell record: radio technology '{raw_radio}' is excluded. "
                "SpectraMap strictly admits modern 4G (LTE) and 5G (NR) technologies."
            )
        radio = str(raw_radio or "UNKNOWN").strip().upper() or "UNKNOWN"
    else:
        radio = canonical_radio

    mcc = int(raw["mcc"]) if raw.get("mcc") is not None else None
    mnc = int(raw["mnc"]) if raw.get("mnc") is not None else None
    area = int(raw.get("lac") or raw.get("tac") or 0)
    cell_id = int(raw["cellid"])

    # Combine network parameters into a globally unique vertex identifier
    tower_id = f"{radio}_{mcc}_{mnc}_{area}_{cell_id}"
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()

    # Determine range and apply 4-tier fallback hierarchy
    raw_range = raw.get("range")
    cell_warnings: list[str] = []

    parsed_range: float | None = None
    reason: str | None = None

    if "range" not in raw:
        reason = "missing"
    elif raw_range is None:
        reason = "null"
    else:
        try:
            val = float(raw_range)
            if math.isnan(val) or math.isinf(val):
                reason = "non_numeric"
            elif val == 0:
                reason = "zero"
            elif val < 0:
                reason = "negative"
            else:
                parsed_range = val
        except (ValueError, TypeError):
            reason = "non_numeric"

    if parsed_range is not None:
        if parsed_range > MAX_VALID_RANGE_M:
            range_m = MAX_VALID_RANGE_M
            is_range_estimated = True
            range_source = "fallback_clamped"
            fallback_reason = "outlier"
            msg = f"Cell {tower_id} ({radio}) had outlier range ({raw_range}m); clamped to {range_m}m."
            cell_warnings.append(msg)
        elif parsed_range < MIN_VALID_RANGE_M:
            range_m = MIN_VALID_RANGE_M
            is_range_estimated = True
            range_source = "fallback_clamped"
            fallback_reason = "outlier"
            msg = f"Cell {tower_id} ({radio}) had outlier range ({raw_range}m); clamped to {range_m}m."
            cell_warnings.append(msg)
        else:
            range_m = float(parsed_range)
            is_range_estimated = False
            range_source = "reported"
            fallback_reason = None
    else:
        fallback_radius = RADIO_FALLBACK_RADII.get(radio, DEFAULT_FALLBACK_RADIUS)
        range_m = float(fallback_radius)
        is_range_estimated = True
        range_source = "fallback_default"
        fallback_reason = reason or "missing"
        msg = f"Cell {tower_id} ({radio}) lacked valid reported range ({raw_range}); applied default estimate of {range_m}m."
        cell_warnings.append(msg)

    return {
        "tower_id": tower_id,
        "id": tower_id,
        "latitude": float(raw["lat"]),
        "longitude": float(raw["lon"]),
        "lat": float(raw["lat"]),
        "lon": float(raw["lon"]),
        "range_m": range_m,
        "radio": radio,
        "mcc": mcc,
        "mnc": mnc,
        "area": area,
        "cell_id": cell_id,
        "source": "OpenCellID",
        "retrieved_at": timestamp,
        "is_range_estimated": is_range_estimated,
        "range_is_fallback": is_range_estimated,
        "range_source": range_source,
        "fallback_reason": fallback_reason,
        "raw_range": raw_range,
        "warnings": cell_warnings,
    }


def parse_opencellid_response(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse an OpenCellID response payload, returning (normalized_records, warnings).
    Handles empty responses, error messages, and skips malformed records while
    applying coverage fallback with informative warnings for unestimated cells.
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
            norm = normalize_cell_record(raw, retrieved_at=retrieved_at)
            records.append(norm)
            if norm.get("warnings"):
                warnings.extend(norm["warnings"])
        else:
            warnings.append(f"Rejected invalid cell record: cellid={raw.get('cellid')}")

    return records, warnings


def get_cache_filepath(bbox_str: str, cache_dir: Path | str = "data") -> Path:
    """Return local cache file path for a given bounding box string with traversal protection."""
    safe_bbox = "".join(c for c in bbox_str.replace(",", "_") if c.isalnum() or c in "._-")
    safe_name = f"cache_{safe_bbox}.json"
    base = Path(cache_dir).resolve()
    target = (base / safe_name).resolve()
    # Guard against directory traversal
    if not str(target).startswith(str(base)):
        raise ValueError(f"Invalid bounding box cache path: {bbox_str}")
    return target


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


def select_spatially_dispersed_records(
    records: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Select up to `limit` records using Deterministic Farthest Point Sampling (FPS).

    Properties:
    - Anchors the first seed to the candidate closest to (center_lat, center_lon).
    - Iteratively selects the candidate that maximizes the minimum distance to the selected set.
    - Resolves all distance ties deterministically using ascending lexicographical tower_id.
    - Handles degenerate cases (e.g. all records co-located at d=0) cleanly via tie-breaking.
    - Employs monotonic Haversine a-value optimization to achieve < 10ms runtime for N=200, k=50.
    """
    if not records or limit <= 0:
        return []

    n = len(records)

    # Precompute radians and cosines for all records once (O(N))
    c_lat_rad = math.radians(center_lat)
    c_lon_rad = math.radians(center_lon)
    c_cos_lat = math.cos(c_lat_rad)

    rads = [
        (
            math.radians(float(r["latitude"] if "latitude" in r else r["lat"])),
            math.radians(float(r["longitude"] if "longitude" in r else r["lon"])),
        )
        for r in records
    ]
    cos_phi = [math.cos(phi) for phi, _ in rads]
    tids = [str(r.get("tower_id") or r.get("id") or "") for r in records]

    def _hav_a(phi1: float, lam1: float, cos1: float, phi2: float, lam2: float, cos2: float) -> float:
        dphi = (phi2 - phi1) * 0.5
        dlam = (lam2 - lam1) * 0.5
        sphi = math.sin(dphi)
        slam = math.sin(dlam)
        a = sphi * sphi + cos1 * cos2 * slam * slam
        if a > 1.0:
            return 1.0
        if a < 0.0:
            return 0.0
        return a

    # If candidate count is within limit, sort deterministically by center proximity and return
    if n <= limit:
        indexed_candidates = list(range(n))
        indexed_candidates.sort(
            key=lambda i: (
                _hav_a(c_lat_rad, c_lon_rad, c_cos_lat, rads[i][0], rads[i][1], cos_phi[i]),
                tids[i],
            )
        )
        return [records[i] for i in indexed_candidates]

    # Step 1: Deterministic Seed Selection (closest to center, tie-break by tower_id)
    seed_idx = 0
    best_dist = _hav_a(c_lat_rad, c_lon_rad, c_cos_lat, rads[0][0], rads[0][1], cos_phi[0])
    best_tid = tids[0]

    for i in range(1, n):
        d = _hav_a(c_lat_rad, c_lon_rad, c_cos_lat, rads[i][0], rads[i][1], cos_phi[i])
        tid = tids[i]
        if d < best_dist - 1e-12:
            best_dist = d
            best_tid = tid
            seed_idx = i
        elif abs(d - best_dist) <= 1e-12 and tid < best_tid:
            best_dist = d
            best_tid = tid
            seed_idx = i

    selected_indices: list[int] = [seed_idx]
    in_selected: list[bool] = [False] * n
    in_selected[seed_idx] = True

    # Step 2: Initialize min_dist array from seed point
    s_phi, s_lam = rads[seed_idx]
    s_cos = cos_phi[seed_idx]
    min_dist = [
        _hav_a(s_phi, s_lam, s_cos, rads[i][0], rads[i][1], cos_phi[i])
        for i in range(n)
    ]
    min_dist[seed_idx] = -1.0

    # Step 3: Greedy Farthest Point Sampling iterations
    for _ in range(1, limit):
        max_d = -1.0
        chosen_tid: str | None = None
        chosen_idx = -1

        for i in range(n):
            if in_selected[i]:
                continue
            d = min_dist[i]
            tid = tids[i]
            if d > max_d + 1e-12:
                max_d = d
                chosen_tid = tid
                chosen_idx = i
            elif abs(d - max_d) <= 1e-12:
                # Deterministic tie-breaking on tower_id ascending
                if chosen_tid is None or tid < chosen_tid:
                    max_d = d
                    chosen_tid = tid
                    chosen_idx = i

        in_selected[chosen_idx] = True
        selected_indices.append(chosen_idx)

        # Update min_dist with respect to newly selected candidate
        c_phi, c_lam = rads[chosen_idx]
        c_cos = cos_phi[chosen_idx]
        for i in range(n):
            if not in_selected[i]:
                new_d = _hav_a(c_phi, c_lam, c_cos, rads[i][0], rads[i][1], cos_phi[i])
                if new_d < min_dist[i]:
                    min_dist[i] = new_d

    return [records[i] for i in selected_indices]


def group_cells_into_sites(
    cells: list[dict[str, Any]],
    precision: int = 5,
    distance_threshold_m: float = 2.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Group normalized cell transceiver records sharing physical coordinates or within
    distance_threshold_m (default: 2.0m) into SiteEntity structures.

    If there are N number of towers/transceivers within a 2 metre range, they are treated
    as belonging to 1 physical site.

    Args:
        cells: List of normalized cell record dictionaries.
        precision: Decimal place precision for coordinate grouping (default: 5, ~1.1m precision).
        distance_threshold_m: Distance threshold in metres to cluster co-located towers (default: 2.0m).

    Returns:
        (updated_cells, sites):
          - updated_cells: Cell dicts updated with 'site_id' and 'is_co_located'.
          - sites: List of SiteEntity dicts deterministically sorted by site_id.
    """
    if not cells:
        return [], []

    n = len(cells)
    parent = list(range(n))

    def find(i: int) -> int:
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for node in path:
            parent[node] = i
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            # Deterministic: attach higher index root to lower index root
            if root_i < root_j:
                parent[root_j] = root_i
            else:
                parent[root_i] = root_j

    coords: list[tuple[float, float]] = []
    for cell in cells:
        lat = float(cell["latitude"] if "latitude" in cell else cell["lat"])
        lon = float(cell["longitude"] if "longitude" in cell else cell["lon"])
        coords.append((lat, lon))

    # Fast clustering: pair cells within distance_threshold_m (<= 2.0m)
    # Bounding box filter for 2m is ~0.0001 degrees
    for i in range(n):
        lat_i, lon_i = coords[i]
        for j in range(i + 1, n):
            lat_j, lon_j = coords[j]
            # Exact coordinate match or within bounding box
            if (lat_i == lat_j and lon_i == lon_j):
                union(i, j)
            elif abs(lat_i - lat_j) <= 0.0001 and abs(lon_i - lon_j) <= 0.0001:
                dist = haversine_distance(lat_i, lon_i, lat_j, lon_j)
                if dist <= distance_threshold_m:
                    union(i, j)

    # Group cells by disjoint set root
    clusters: dict[int, list[dict[str, Any]]] = {}
    for i in range(n):
        root = find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(cells[i])

    sites: list[dict[str, Any]] = []

    for root in sorted(clusters.keys()):
        bucket = clusters[root]
        # Use representative coordinates (from primary cell), rounded to precision
        rep_lat = float(bucket[0]["latitude"] if "latitude" in bucket[0] else bucket[0]["lat"])
        rep_lon = float(bucket[0]["longitude"] if "longitude" in bucket[0] else bucket[0]["lon"])
        lat = round(rep_lat, precision)
        lon = round(rep_lon, precision)
        site_id = f"SITE_{lat:.5f}_{lon:.5f}"

        sector_ids = sorted([c.get("tower_id") or str(c.get("id")) for c in bucket])
        sector_count = len(bucket)
        is_co_located = sector_count > 1
        radios = sorted(list({c.get("radio", "4G") for c in bucket}))

        for c in bucket:
            c["site_id"] = site_id
            c["is_co_located"] = is_co_located

        sites.append({
            "site_id": site_id,
            "latitude": lat,
            "longitude": lon,
            "sector_count": sector_count,
            "sectors": sector_ids,
            "radios": radios,
        })

    sites.sort(key=lambda s: s["site_id"])
    return cells, sites


def aggregate_towers_within_distance(
    cells: list[dict[str, Any]],
    distance_threshold_m: float = 2.0,
    precision: int = 5,
) -> list[dict[str, Any]]:
    """
    If there are N number of towers within distance_threshold_m (default 2.0 metres),
    treat those towers as 1 tower.

    Merges co-located transceivers/sectors sharing a physical mast into a single
    consolidated tower entity for map display and graph construction.

    Args:
        cells: List of cell/tower records.
        distance_threshold_m: Co-location distance threshold in metres (default 2.0m).
        precision: Coordinate rounding precision for site identification.

    Returns:
        List of consolidated tower entities, exactly 1 entity per physical mast site.
    """
    if not cells:
        return []

    updated_cells, sites = group_cells_into_sites(
        cells, precision=precision, distance_threshold_m=distance_threshold_m
    )

    by_site: dict[str, list[dict[str, Any]]] = {}
    for c in updated_cells:
        sid = c.get("site_id") or "UNKNOWN"
        if sid not in by_site:
            by_site[sid] = []
        by_site[sid].append(c)

    aggregated: list[dict[str, Any]] = []
    for site in sites:
        sid = site["site_id"]
        cluster = by_site.get(sid, [])
        if not cluster:
            continue

        primary = cluster[0]
        max_sector = max(cluster, key=lambda c: float(c.get("range_m", 800.0) or 800.0))
        max_range = float(max_sector.get("range_m", 800.0) or 800.0)
        distinct_radios = sorted(list({c.get("radio", "4G") for c in cluster}))
        rep_radio = "5G" if "5G" in distinct_radios else "4G"

        tower_id = sid if len(cluster) > 1 else (primary.get("tower_id") or primary.get("id"))
        merged_tower = dict(primary)
        merged_tower["tower_id"] = tower_id
        merged_tower["id"] = tower_id
        merged_tower["site_id"] = sid
        merged_tower["latitude"] = site["latitude"]
        merged_tower["longitude"] = site["longitude"]
        merged_tower["lat"] = site["latitude"]
        merged_tower["lon"] = site["longitude"]
        merged_tower["range_m"] = max_range
        merged_tower["range_source"] = max_sector.get("range_source", "reported")
        merged_tower["fallback_reason"] = max_sector.get("fallback_reason")
        merged_tower["radio"] = rep_radio
        merged_tower["radios"] = distinct_radios
        merged_tower["sector_count"] = len(cluster)
        merged_tower["sectors"] = [c.get("tower_id") or str(c.get("id")) for c in cluster]
        merged_tower["is_co_located"] = len(cluster) > 1
        merged_tower["is_range_estimated"] = any(c.get("is_range_estimated") for c in cluster)

        aggregated.append(merged_tower)

    # Re-assign deterministic alphabetic labels A, B, C... if labels were present
    if any("label" in t for t in aggregated):
        for idx, t in enumerate(aggregated):
            t["label"] = chr(65 + idx) if idx < 26 else f"T{idx + 1}"

    return aggregated




