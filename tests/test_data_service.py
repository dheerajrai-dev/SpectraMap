import math
import httpx
import pytest
from data_service import (
    validate_cell_record,
    normalize_cell_record,
    parse_opencellid_response,
    haversine_distance,
    calculate_bounding_box,
    filter_records_by_radius,
    fetch_opencellid_records,
    save_cache,
    load_cache,
    load_cache_fallback,
)


@pytest.fixture
def valid_raw_cell():
    return {
        "lat": 28.63,
        "lon": 77.22,
        "mcc": 404,
        "mnc": 11,
        "lac": 51005,
        "cellid": 204868614,
        "range": 1000,
        "radio": "LTE",
    }


def test_validate_valid_record(valid_raw_cell):
    assert validate_cell_record(valid_raw_cell) is True


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"lat": 95.0},
        {"lat": -91.0},
        {"lat": "not_a_number"},
        {"lon": 181.0},
        {"lon": -185.0},
        {"lon": "not_a_number"},
        {"cellid": None},
        {"cellid": "not_an_int"},
    ],
)
def test_validate_invalid_records(valid_raw_cell, invalid_update):
    record = valid_raw_cell.copy()
    record.update(invalid_update)
    assert validate_cell_record(record) is False


def test_validate_missing_lat_or_lon(valid_raw_cell):
    r1 = valid_raw_cell.copy()
    del r1["lat"]
    assert validate_cell_record(r1) is False

    r2 = valid_raw_cell.copy()
    del r2["lon"]
    assert validate_cell_record(r2) is False


@pytest.mark.parametrize(
    "range_update",
    [
        {"range": 0},
        {"range": -100},
        {"range": "not_a_number"},
        {"range": None},
    ],
)
def test_validate_record_accepts_non_positive_or_missing_range(valid_raw_cell, range_update):
    record = valid_raw_cell.copy()
    record.update(range_update)
    assert validate_cell_record(record) is True

    # Also verify that missing range key is accepted
    record_no_range = valid_raw_cell.copy()
    del record_no_range["range"]
    assert validate_cell_record(record_no_range) is True


def test_normalize_cell_record(valid_raw_cell):
    normalized = normalize_cell_record(valid_raw_cell, retrieved_at="2026-10-17T00:00:00Z")
    assert normalized["tower_id"] == "LTE_404_11_51005_204868614"
    assert normalized["latitude"] == 28.63
    assert normalized["longitude"] == 77.22
    assert normalized["range_m"] == 1000.0
    assert normalized["radio"] == "LTE"
    assert normalized["mcc"] == 404
    assert normalized["mnc"] == 11
    assert normalized["area"] == 51005
    assert normalized["cell_id"] == 204868614
    assert normalized["source"] == "OpenCellID"
    assert normalized["retrieved_at"] == "2026-10-17T00:00:00Z"
    assert normalized["is_range_estimated"] is False
    assert normalized["range_is_fallback"] is False
    assert normalized["range_source"] == "reported"
    assert normalized["fallback_reason"] is None
    assert normalized["raw_range"] == 1000
    assert normalized["warnings"] == []


def test_normalize_invalid_record_raises():
    with pytest.raises(ValueError, match="Cannot normalize invalid"):
        normalize_cell_record({"lat": "invalid"})


def test_parse_opencellid_response_success(valid_raw_cell):
    invalid_cell = valid_raw_cell.copy()
    invalid_cell["lat"] = 95.0

    payload = {
        "count": 2,
        "cells": [valid_raw_cell, invalid_cell],
    }
    records, warnings = parse_opencellid_response(payload)
    assert len(records) == 1
    assert records[0]["cell_id"] == 204868614
    assert len(warnings) == 1
    assert "Rejected invalid cell record" in warnings[0]


def test_parse_opencellid_response_with_fallback(valid_raw_cell):
    cell_zero_range = valid_raw_cell.copy()
    cell_zero_range["range"] = 0
    cell_zero_range["cellid"] = 999999

    payload = {
        "count": 2,
        "cells": [valid_raw_cell, cell_zero_range],
    }
    records, warnings = parse_opencellid_response(payload)
    assert len(records) == 2
    assert records[0]["is_range_estimated"] is False
    assert records[1]["is_range_estimated"] is True
    assert records[1]["range_source"] == "fallback_default"
    assert records[1]["range_m"] == 800.0  # LTE default
    assert len(warnings) == 1
    assert "applied default estimate of 800.0m" in warnings[0]


def test_parse_opencellid_response_error_payload():
    payload = {
        "status": "error",
        "message": "Daily request limit exceeded",
    }
    records, warnings = parse_opencellid_response(payload)
    assert records == []
    assert len(warnings) == 1
    assert "Daily request limit exceeded" in warnings[0]


def test_parse_opencellid_response_malformed():
    records, warnings = parse_opencellid_response("not a dict")
    assert records == []
    assert "Invalid response format" in warnings[0]


def test_haversine_distance_same_point():
    assert haversine_distance(28.6139, 77.2090, 28.6139, 77.2090) == 0.0


def test_haversine_distance_known_landmarks():
    # London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ~ 343.5 km
    dist_london_paris = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340_000 < dist_london_paris < 350_000

    # New Delhi (28.6139, 77.2090) to Mumbai (19.0760, 72.8777) ~ 1148 km
    dist_delhi_mumbai = haversine_distance(28.6139, 77.2090, 19.0760, 72.8777)
    assert 1_140_000 < dist_delhi_mumbai < 1_160_000


def test_haversine_meridian_convergence():
    # 1 deg lon at equator vs 1 deg lon at 60 deg lat
    dist_equator = haversine_distance(0.0, 0.0, 0.0, 1.0)
    dist_60deg = haversine_distance(60.0, 0.0, 60.0, 1.0)
    # At 60 degrees latitude, cos(60 deg) = 0.5, so distance should be roughly half
    assert 110_000 < dist_equator < 112_000
    assert 55_000 < dist_60deg < 56_500
    assert abs(dist_60deg - (dist_equator * 0.5)) < 1000


def test_calculate_bounding_box():
    lat, lon = 28.6139, 77.2090
    radius = 1000.0  # 1 km
    latmin, lonmin, latmax, lonmax = calculate_bounding_box(lat, lon, radius)

    assert latmin < lat < latmax
    assert lonmin < lon < lonmax

    # North point (latmax, lon) should be approximately 1 km away
    d_north = haversine_distance(lat, lon, latmax, lon)
    assert abs(d_north - radius) < 15.0

    # East point (lat, lonmax) should be approximately 1 km away
    d_east = haversine_distance(lat, lon, lat, lonmax)
    assert abs(d_east - radius) < 15.0


def test_filter_records_by_radius():
    center_lat, center_lon = 28.6139, 77.2090
    # ~0.003 degrees is ~333 metres (inside 500m)
    inside_record = {"latitude": center_lat + 0.003, "longitude": center_lon, "cell_id": 1}
    # ~0.009 degrees is ~1000 metres (outside 500m)
    outside_record = {"latitude": center_lat + 0.009, "longitude": center_lon, "cell_id": 2}

    records = [inside_record, outside_record]
    filtered = filter_records_by_radius(records, center_lat, center_lon, radius_m=500.0)

    assert len(filtered) == 1
    assert filtered[0]["cell_id"] == 1


@pytest.mark.anyio
async def test_fetch_opencellid_records_mock_success(valid_raw_cell, tmp_path):
    def mock_handler(request: httpx.Request):
        assert "key=test_key" in str(request.url)
        return httpx.Response(200, json={"count": 1, "cells": [valid_raw_cell]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    cells, warnings, is_cached = await fetch_opencellid_records(
        center_lat=28.63,
        center_lon=77.22,
        radius_m=1000.0,
        api_key="test_key",
        client=client,
        cache_dir=str(tmp_path),
    )
    assert len(cells) == 1
    assert cells[0]["cell_id"] == 204868614
    assert warnings == []
    assert is_cached is False


@pytest.mark.anyio
async def test_fetch_opencellid_records_mock_http_error(tmp_path):
    def mock_handler(request: httpx.Request):
        return httpx.Response(403, text="Invalid API key")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    cells, warnings, is_cached = await fetch_opencellid_records(
        center_lat=28.63,
        center_lon=77.22,
        radius_m=1000.0,
        api_key="bad_key",
        client=client,
        cache_dir=str(tmp_path),
    )
    assert cells == []
    assert len(warnings) == 1
    assert "OpenCellID HTTP 403" in warnings[0]
    assert is_cached is False


def test_cache_save_and_load(tmp_path):
    bbox = "28.6000_77.2000_28.6100_77.2100"
    records = [{"tower_id": "test_1", "latitude": 28.605, "longitude": 77.205}]

    file_path = save_cache(bbox, records, is_partial=False, cache_dir=tmp_path)
    assert file_path is not None
    assert file_path.exists()

    loaded = load_cache(bbox, max_age_seconds=60, cache_dir=tmp_path)
    assert loaded is not None
    assert loaded["bbox"] == bbox
    assert loaded["record_count"] == 1
    assert loaded["records"] == records


def test_cache_expiration(tmp_path):
    bbox = "28.6000_77.2000_28.6100_77.2100"
    save_cache(bbox, [], is_partial=False, cache_dir=tmp_path)

    # With max_age_seconds = 0, cache is treated as expired
    loaded = load_cache(bbox, max_age_seconds=0, cache_dir=tmp_path)
    assert loaded is None

    # Fallback loader ignores expiration
    fallback = load_cache_fallback(bbox, cache_dir=tmp_path)
    assert fallback is not None


@pytest.mark.anyio
async def test_fetch_opencellid_records_cache_hit(valid_raw_cell, tmp_path):
    call_count = 0

    def mock_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"count": 1, "cells": [valid_raw_cell]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # First fetch: calls network, saves cache, returns is_cached=False
    cells1, _, is_cached1 = await fetch_opencellid_records(
        28.63, 77.22, 1000.0, "key", client=client, cache_dir=str(tmp_path)
    )
    assert len(cells1) == 1
    assert is_cached1 is False
    assert call_count == 1

    # Second fetch: serves from cache, does NOT call network again
    cells2, _, is_cached2 = await fetch_opencellid_records(
        28.63, 77.22, 1000.0, "key", client=client, cache_dir=str(tmp_path)
    )
    assert len(cells2) == 1
    assert is_cached2 is True
    assert call_count == 1  # Network handler was not called a second time


@pytest.mark.anyio
async def test_fetch_opencellid_records_fallback_on_network_failure(valid_raw_cell, tmp_path):
    # Pre-populate cache
    latmin, lonmin, latmax, lonmax = calculate_bounding_box(28.63, 77.22, 1000.0)
    bbox_str = f"{latmin:.4f},{lonmin:.4f},{latmax:.4f},{lonmax:.4f}"
    normalized = normalize_cell_record(valid_raw_cell)
    save_cache(bbox_str, [normalized], cache_dir=str(tmp_path))

    # Network client that fails with 500
    def mock_handler(request: httpx.Request):
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # Request with cache_ttl_seconds=0 forces network call, which fails, triggering fallback
    cells, warnings, is_cached = await fetch_opencellid_records(
        28.63, 77.22, 1000.0, "key", client=client, cache_dir=str(tmp_path), cache_ttl_seconds=0
    )
    assert len(cells) == 1
    assert is_cached is True
    assert any("Serving cached fallback" in w for w in warnings)


@pytest.mark.parametrize(
    "radio, expected_radius",
    [
        ("GSM", 1000.0),
        ("gsm", 1000.0),
        ("2G", 1000.0),
        ("CDMA", 1000.0),
        ("cdma", 1000.0),
        ("UMTS", 800.0),
        ("umts", 800.0),
        ("3G", 800.0),
        ("LTE", 800.0),
        ("lte", 800.0),
        ("4G", 800.0),
        ("NR", 500.0),
        ("nr", 500.0),
        ("5G", 500.0),
        ("UNKNOWN", 800.0),
        ("SATELLITE", 800.0),
        ("", 800.0),
        (None, 800.0),
    ],
)
def test_fallback_radii_by_technology(valid_raw_cell, radio, expected_radius):
    record = valid_raw_cell.copy()
    if radio is None:
        del record["radio"]
    else:
        record["radio"] = radio
    del record["range"]

    normalized = normalize_cell_record(record)
    assert normalized["range_m"] == expected_radius
    assert normalized["is_range_estimated"] is True
    assert normalized["range_is_fallback"] is True
    assert normalized["range_source"] == "fallback_default"
    assert normalized["fallback_reason"] == "missing"
    assert len(normalized["warnings"]) == 1
    assert "applied default estimate" in normalized["warnings"][0]


@pytest.mark.parametrize(
    "range_val, expected_reason",
    [
        (0, "zero"),
        (-50, "negative"),
        ("abc", "non_numeric"),
        (None, "null"),
    ],
)
def test_fallback_reasons(valid_raw_cell, range_val, expected_reason):
    record = valid_raw_cell.copy()
    record["range"] = range_val
    normalized = normalize_cell_record(record)
    assert normalized["is_range_estimated"] is True
    assert normalized["range_is_fallback"] is True
    assert normalized["range_source"] == "fallback_default"
    assert normalized["fallback_reason"] == expected_reason
    assert normalized["raw_range"] == range_val
    assert len(normalized["warnings"]) == 1
    assert "applied default estimate" in normalized["warnings"][0]


def test_fallback_outlier_high_clamped(valid_raw_cell):
    record = valid_raw_cell.copy()
    record["range"] = 50_000.0
    normalized = normalize_cell_record(record)
    assert normalized["range_m"] == 10_000.0
    assert normalized["is_range_estimated"] is True
    assert normalized["range_is_fallback"] is True
    assert normalized["range_source"] == "fallback_clamped"
    assert normalized["fallback_reason"] == "outlier"
    assert len(normalized["warnings"]) == 1
    assert "clamped to 10000.0m" in normalized["warnings"][0]


def test_fallback_outlier_low_clamped(valid_raw_cell):
    record = valid_raw_cell.copy()
    record["range"] = 25.0
    normalized = normalize_cell_record(record)
    assert normalized["range_m"] == 50.0
    assert normalized["is_range_estimated"] is True
    assert normalized["range_is_fallback"] is True
    assert normalized["range_source"] == "fallback_clamped"
    assert normalized["fallback_reason"] == "outlier"
    assert len(normalized["warnings"]) == 1
    assert "clamped to 50.0m" in normalized["warnings"][0]


@pytest.mark.parametrize("valid_range", [50.0, 500.0, 1000.0, 10000.0])
def test_valid_reported_range_boundaries(valid_raw_cell, valid_range):
    record = valid_raw_cell.copy()
    record["range"] = valid_range
    normalized = normalize_cell_record(record)
    assert normalized["range_m"] == float(valid_range)
    assert normalized["is_range_estimated"] is False
    assert normalized["range_is_fallback"] is False
    assert normalized["range_source"] == "reported"
    assert normalized["fallback_reason"] is None
    assert normalized["warnings"] == []


def test_haversine_antipodal_points():
    dist = haversine_distance(0.0, 0.0, 0.0, 180.0)
    expected = math.pi * 6_371_000.0
    assert abs(dist - expected) < 1.0


def test_haversine_antimeridian_crossing():
    dist = haversine_distance(0.0, 179.999, 0.0, -179.999)
    expected = math.radians(0.002) * 6_371_000.0
    assert abs(dist - expected) < 1.0


def test_bounding_box_polar_protection():
    latmin, lonmin, latmax, lonmax = calculate_bounding_box(90.0, 0.0, 1000.0)
    assert latmax == 90.0
    assert lonmin == -180.0
    assert lonmax == 180.0

    latmin_s, lonmin_s, latmax_s, lonmax_s = calculate_bounding_box(-90.0, 0.0, 1000.0)
    assert latmin_s == -90.0
    assert lonmin_s == -180.0
    assert lonmax_s == 180.0




