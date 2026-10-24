import math
import httpx
import pytest
from data_service import (
    validate_cell_record,
    normalize_cell_record,
    normalize_radio_type,
    filter_records_by_radio,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    parse_opencellid_response,
    haversine_distance,
    calculate_bounding_box,
    filter_records_by_radius,
    fetch_opencellid_records,
    save_cache,
    load_cache,
    load_cache_fallback,
    RADIO_4G,
    RADIO_5G,
)
from schemas import (
    CellRecord,
    SiteEntity,
    AccountingMetadata,
    TowersResponse,
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
    assert normalized["tower_id"] == "4G_404_11_51005_204868614"
    assert normalized["id"] == "4G_404_11_51005_204868614"
    assert normalized["latitude"] == 28.63
    assert normalized["longitude"] == 77.22
    assert normalized["lat"] == 28.63
    assert normalized["lon"] == 77.22
    assert normalized["range_m"] == 1000.0
    assert normalized["radio"] == "4G"
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
        ("GSM", 800.0),
        ("gsm", 800.0),
        ("2G", 800.0),
        ("CDMA", 800.0),
        ("cdma", 800.0),
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


# ==============================================================================
# Milestone M1 Tests: Strict Radio Normalization & Exclusion
# ==============================================================================

@pytest.mark.parametrize(
    "raw_val, expected",
    [
        ("LTE", "4G"),
        ("lte", "4G"),
        ("4G", "4G"),
        ("4g", "4G"),
        ("4G LTE", "4G"),
        ("4g-lte", "4G"),
        ("4GLTE", "4G"),
        ("EUTRAN", "4G"),
        ("E-UTRAN", "4G"),
        ("LTE-M", "4G"),
        ("NR", "5G"),
        ("nr", "5G"),
        ("5G", "5G"),
        ("5g", "5G"),
        ("5G NR", "5G"),
        ("5g-nr", "5G"),
        ("5GNR", "5G"),
    ],
)
def test_normalize_radio_type_accepted(raw_val, expected):
    assert normalize_radio_type(raw_val) == expected


@pytest.mark.parametrize(
    "raw_val",
    [
        "GSM", "gsm", "2G", "CDMA", "cdma", "GPRS", "EDGE",
        "UMTS", "umts", "3G", "WCDMA", "wcdma", "HSPA",
        "SATELLITE", "satellite", "WIFI", "UNKNOWN", "", "   ", None,
    ],
)
def test_normalize_radio_type_rejected(raw_val):
    assert normalize_radio_type(raw_val) is None


def test_normalize_cell_record_strict_exclusion_raises():
    raw_gsm = {"lat": 28.63, "lon": 77.22, "cellid": 12345, "radio": "GSM"}
    with pytest.raises(ValueError, match="radio technology 'GSM' is excluded"):
        normalize_cell_record(raw_gsm, strict_radio=True)

    raw_umts = {"lat": 28.63, "lon": 77.22, "cellid": 12346, "radio": "UMTS"}
    with pytest.raises(ValueError, match="radio technology 'UMTS' is excluded"):
        normalize_cell_record(raw_umts, strict_radio=True)


def test_normalize_cell_record_strict_admission():
    raw_lte = {"lat": 28.63, "lon": 77.22, "cellid": 101, "radio": "LTE"}
    norm_4g = normalize_cell_record(raw_lte, strict_radio=True)
    assert norm_4g["radio"] == "4G"
    assert norm_4g["tower_id"].startswith("4G_")
    assert norm_4g["range_m"] == 800.0

    raw_nr = {"lat": 28.63, "lon": 77.22, "cellid": 202, "radio": "NR"}
    norm_5g = normalize_cell_record(raw_nr, strict_radio=True)
    assert norm_5g["radio"] == "5G"
    assert norm_5g["tower_id"].startswith("5G_")
    assert norm_5g["range_m"] == 500.0


def test_filter_records_by_radio():
    records = [
        {"tower_id": "T1", "radio": "4G"},
        {"tower_id": "T2", "radio": "5G"},
        {"tower_id": "T3", "radio": "4G"},
        {"tower_id": "T4", "radio": "GSM"},
    ]
    only_4g = filter_records_by_radio(records, ["4G"])
    assert [r["tower_id"] for r in only_4g] == ["T1", "T3"]

    only_5g = filter_records_by_radio(records, ["5G"])
    assert [r["tower_id"] for r in only_5g] == ["T2"]

    both = filter_records_by_radio(records, ["4G", "5G"])
    assert [r["tower_id"] for r in both] == ["T1", "T2", "T3"]


# ==============================================================================
# Milestone M1 Tests: Deterministic Farthest Point Sampling (FPS)
# ==============================================================================

def test_fps_empty_or_zero_limit():
    assert select_spatially_dispersed_records([], 28.6, 77.2, limit=50) == []
    recs = [{"tower_id": "T1", "latitude": 28.6, "longitude": 77.2}]
    assert select_spatially_dispersed_records(recs, 28.6, 77.2, limit=0) == []
    assert select_spatially_dispersed_records(recs, 28.6, 77.2, limit=-5) == []


def test_fps_n_less_than_or_equal_limit():
    recs = [
        {"tower_id": "T_far", "latitude": 28.7, "longitude": 77.3},
        {"tower_id": "T_close", "latitude": 28.601, "longitude": 77.201},
        {"tower_id": "T_mid", "latitude": 28.65, "longitude": 77.25},
    ]
    res = select_spatially_dispersed_records(recs, 28.6, 77.2, limit=10)
    assert len(res) == 3
    # Sorted by distance to center
    assert res[0]["tower_id"] == "T_close"
    assert res[1]["tower_id"] == "T_mid"
    assert res[2]["tower_id"] == "T_far"


def test_fps_all_colocated_degenerate_case():
    # 20 records at the exact same location
    recs = [
        {"tower_id": f"T_{i:02d}", "latitude": 28.63, "longitude": 77.22}
        for i in reversed(range(20))
    ]
    res = select_spatially_dispersed_records(recs, 28.63, 77.22, limit=5)
    assert len(res) == 5
    # Tied at d=0, secondary tie-breaker is tower_id ascending
    selected_ids = [r["tower_id"] for r in res]
    assert selected_ids == ["T_00", "T_01", "T_02", "T_03", "T_04"]


def test_fps_clustered_multi_sector_coverage():
    # 5 physical sites with 6 sectors each = 30 records
    recs = []
    coords = [
        (28.60, 77.20),
        (28.65, 77.20),
        (28.60, 77.25),
        (28.65, 77.25),
        (28.625, 77.225),
    ]
    for s_idx, (lat, lon) in enumerate(coords):
        for sec in range(6):
            recs.append({
                "tower_id": f"SITE_{s_idx}_SEC_{sec}",
                "latitude": lat,
                "longitude": lon,
            })

    # Limit = 5 -> FPS must select exactly 1 transceiver from each of the 5 distinct sites
    res = select_spatially_dispersed_records(recs, 28.625, 77.225, limit=5)
    assert len(res) == 5
    selected_locations = {(round(r["latitude"], 4), round(r["longitude"], 4)) for r in res}
    assert len(selected_locations) == 5


def test_fps_permutation_invariance():
    import random
    recs = [
        {"tower_id": f"T_{i:03d}", "latitude": 28.5 + (i * 0.01) % 0.2, "longitude": 77.1 + (i * 0.013) % 0.2}
        for i in range(40)
    ]
    res1 = select_spatially_dispersed_records(recs, 28.6, 77.2, limit=15)
    ids1 = [r["tower_id"] for r in res1]

    shuffled = recs.copy()
    random.seed(42)
    random.shuffle(shuffled)
    res2 = select_spatially_dispersed_records(shuffled, 28.6, 77.2, limit=15)
    ids2 = [r["tower_id"] for r in res2]

    assert ids1 == ids2


def test_fps_performance_benchmark():
    import time
    # 200 candidate records, limit=50 -> must run under 10 ms
    recs = [
        {"tower_id": f"T_{i:03d}", "latitude": 28.5 + (i * 0.003), "longitude": 77.1 + (i * 0.002)}
        for i in range(200)
    ]
    start = time.perf_counter()
    res = select_spatially_dispersed_records(recs, 28.6, 77.2, limit=50)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert len(res) == 50
    assert elapsed_ms < 10.0, f"FPS benchmark exceeded 10ms: {elapsed_ms:.2f}ms"


# ==============================================================================
# Milestone M1 Tests: Physical Site Identity Modeling & Grouping
# ==============================================================================

def test_group_cells_into_sites_empty():
    cells, sites = group_cells_into_sites([])
    assert cells == []
    assert sites == []


def test_group_cells_into_sites_single_cell():
    cell = {"tower_id": "4G_1", "latitude": 28.63, "longitude": 77.22, "radio": "4G"}
    cells, sites = group_cells_into_sites([cell])
    assert len(sites) == 1
    assert sites[0]["sector_count"] == 1
    assert sites[0]["sectors"] == ["4G_1"]
    assert sites[0]["radios"] == ["4G"]
    assert cells[0]["is_co_located"] is False
    assert cells[0]["site_id"].startswith("SITE_")


def test_group_cells_into_sites_colocated_sectors():
    # 3 sectors sharing identical coordinates
    cells = [
        {"tower_id": "4G_1", "latitude": 28.630001, "longitude": 77.220002, "radio": "4G"},
        {"tower_id": "4G_2", "latitude": 28.630003, "longitude": 77.220001, "radio": "4G"},
        {"tower_id": "5G_1", "latitude": 28.630000, "longitude": 77.220000, "radio": "5G"},
    ]
    updated_cells, sites = group_cells_into_sites(cells, precision=5)
    assert len(sites) == 1
    site = sites[0]
    assert site["sector_count"] == 3
    assert set(site["sectors"]) == {"4G_1", "4G_2", "5G_1"}
    assert set(site["radios"]) == {"4G", "5G"}
    for c in updated_cells:
        assert c["is_co_located"] is True
        assert c["site_id"] == site["site_id"]


# ==============================================================================
# Milestone M1 Tests: Pydantic Schemas & Accounting Invariants
# ==============================================================================

def test_accounting_metadata_valid_and_invariants():
    acc = AccountingMetadata(
        available_count=100,
        eligible_count=70,
        selected_count=50,
        excluded_count=50,
        excluded_radio_count=30,
        excluded_limit_count=20,
    )
    assert acc.available_count == 100
    assert acc.eligible_count == 70
    assert acc.selected_count == 50
    assert acc.excluded_count == 50
    assert acc.excluded_radio_count == 30
    assert acc.excluded_limit_count == 20
    assert acc.excluded_count == acc.excluded_radio_count + acc.excluded_limit_count


@pytest.mark.parametrize(
    "invalid_kwargs",
    [
        {"available_count": 50, "eligible_count": 60, "selected_count": 40, "excluded_count": 10, "excluded_radio_count": -10, "excluded_limit_count": 20},
        {"available_count": 100, "eligible_count": 40, "selected_count": 50, "excluded_count": 50, "excluded_radio_count": 60, "excluded_limit_count": -10},
        {"available_count": 100, "eligible_count": 70, "selected_count": 50, "excluded_count": 40, "excluded_radio_count": 30, "excluded_limit_count": 20},
    ],
)
def test_accounting_metadata_invariants_rejected(invalid_kwargs):
    with pytest.raises(Exception):
        AccountingMetadata(**invalid_kwargs)


def test_site_entity_validation():
    site = SiteEntity(
        site_id="SITE_28.52000_77.19000",
        latitude=28.52,
        longitude=77.19,
        sector_count=2,
        sectors=["4G_1", "5G_1"],
        radios=["4G", "5G"],
    )
    assert site.sector_count == 2

    # Mismatch between sector_count and len(sectors) must fail
    with pytest.raises(Exception):
        SiteEntity(
            site_id="SITE_28.52000_77.19000",
            latitude=28.52,
            longitude=77.19,
            sector_count=3,
            sectors=["4G_1", "5G_1"],
            radios=["4G", "5G"],
        )


def test_cell_record_validation():
    cr = CellRecord(
        tower_id="4G_404_11_123_456",
        cell_id=456,
        radio="LTE",
        latitude=28.63,
        longitude=77.22,
        range_m=800.0,
    )
    assert cr.radio == "4G"
    assert cr.id == "4G_404_11_123_456"
    assert cr.lat == 28.63
    assert cr.lon == 77.22
    assert cr.site_id.startswith("SITE_")

    with pytest.raises(Exception):
        CellRecord(
            tower_id="GSM_1",
            cell_id=1,
            radio="GSM",
            latitude=28.63,
            longitude=77.22,
        )


# ==============================================================================
# Milestone M1 Tests: FastAPI Endpoint Integration (Towers & Cells)
# ==============================================================================

def test_api_towers_filtering_and_accounting(monkeypatch):
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    async def mock_fetch(lat, lon, radius_m, api_key):
        # 10 records: 6 LTE (4G), 2 NR (5G), 2 GSM (2G)
        records = []
        for i in range(6):
            records.append({
                "tower_id": f"LTE_404_11_10_{i}",
                "latitude": lat + i * 0.001,
                "longitude": lon + i * 0.001,
                "range_m": 800.0,
                "radio": "LTE",
                "cell_id": 100 + i,
            })
        for i in range(2):
            records.append({
                "tower_id": f"NR_404_11_20_{i}",
                "latitude": lat + 0.01 + i * 0.001,
                "longitude": lon + 0.01 + i * 0.001,
                "range_m": 500.0,
                "radio": "NR",
                "cell_id": 200 + i,
            })
        for i in range(2):
            records.append({
                "tower_id": f"GSM_404_11_30_{i}",
                "latitude": lat + 0.02 + i * 0.001,
                "longitude": lon + 0.02 + i * 0.001,
                "range_m": 1000.0,
                "radio": "GSM",
                "cell_id": 300 + i,
            })
        return records, [], False

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    # 1. Default: both 4G and 5G, limit 50 -> GSM excluded, 8 selected
    res = client.get("/api/towers?lat=28.6&lon=77.2&radius_m=1500")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 8
    assert data["accounting"]["available_count"] == 10
    assert data["accounting"]["eligible_count"] == 8
    assert data["accounting"]["selected_count"] == 8
    assert data["accounting"]["excluded_radio_count"] == 2
    assert data["accounting"]["excluded_limit_count"] == 0
    assert data["accounting"]["excluded_count"] == 2
    assert data["tech_distribution"] == {"4G": 6, "5G": 2}
    assert len(data["sites"]) > 0

    # 2. Filter 4G only, limit 50 -> 6 selected
    res_4g = client.get("/api/towers?lat=28.6&lon=77.2&radios=4G")
    assert res_4g.status_code == 200
    d_4g = res_4g.json()
    assert d_4g["count"] == 6
    assert d_4g["tech_distribution"] == {"4G": 6, "5G": 0}
    assert d_4g["accounting"]["eligible_count"] == 6
    assert d_4g["accounting"]["excluded_radio_count"] == 4

    # 3. Filter 5G only, limit 50 -> 2 selected
    res_5g = client.get("/api/towers?lat=28.6&lon=77.2&radios=5G")
    assert res_5g.status_code == 200
    d_5g = res_5g.json()
    assert d_5g["count"] == 2
    assert d_5g["tech_distribution"] == {"4G": 0, "5G": 2}

    # 4. Limit validation: limit=5 (< 10) -> HTTP 422
    res_low = client.get("/api/towers?lat=28.6&lon=77.2&limit=5")
    assert res_low.status_code == 422

    # 5. Limit validation: limit=250 (> 200) -> HTTP 422
    res_high = client.get("/api/towers?lat=28.6&lon=77.2&limit=250")
    assert res_high.status_code == 422

    # 6. Invalid radio: radios=2G -> HTTP 400
    res_inv = client.get("/api/towers?lat=28.6&lon=77.2&radios=2G")
    assert res_inv.status_code == 400
    assert "Allowed values: 4G, 5G" in res_inv.json()["detail"]

    # 7. Empty radios param -> HTTP 400
    res_empty = client.get("/api/towers?lat=28.6&lon=77.2&radios=")
    assert res_empty.status_code == 400





