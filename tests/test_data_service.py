import pytest
from data_service import (
    validate_cell_record,
    normalize_cell_record,
    parse_opencellid_response,
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
