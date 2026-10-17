import pytest
from data_service import (
    validate_cell_record,
    normalize_cell_record,
    parse_opencellid_response,
    haversine_distance,
    calculate_bounding_box,
    filter_records_by_radius,
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
        {"lon": 181.0},
        {"lon": -185.0},
        {"range": 0},
        {"range": -100},
        {"range": "not_a_number"},
        {"cellid": None},
    ],
)
def test_validate_invalid_records(valid_raw_cell, invalid_update):
    record = valid_raw_cell.copy()
    record.update(invalid_update)
    assert validate_cell_record(record) is False


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


def test_normalize_invalid_record_raises():
    with pytest.raises(ValueError, match="Cannot normalize invalid"):
        normalize_cell_record({"lat": "invalid"})


def test_parse_opencellid_response_success(valid_raw_cell):
    invalid_cell = valid_raw_cell.copy()
    invalid_cell["range"] = 0

    payload = {
        "count": 2,
        "cells": [valid_raw_cell, invalid_cell],
    }
    records, warnings = parse_opencellid_response(payload)
    assert len(records) == 1
    assert records[0]["cell_id"] == 204868614
    assert len(warnings) == 1
    assert "Rejected invalid cell record" in warnings[0]


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

