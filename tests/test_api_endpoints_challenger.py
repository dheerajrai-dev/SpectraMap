"""
Milestone M1 Challenger 2 Empirical Test Suite
FastAPI /api/towers and /api/cells Endpoints Verification

Tests:
1. Radio parameter handling (single 4G, single 5G, combinations, synonyms, defaults)
2. Invalid radio rejection with HTTP 400 (2G, GSM, 3G, UMTS, blank, mixed)
3. Limit boundary testing (10, 50, 200 pass; <10, >200 return HTTP 422)
4. Comprehensive accounting invariants verification across all permutations
5. Physical site entity resolution and co-location metadata
6. Bounding box vs lat/lon input validation
7. Edge cases (0 matching records, all 2G records, missing API key HTTP 503)
"""

import math
import random
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app import app
from schemas import AccountingMetadata, CellRecord, SiteEntity, TowersResponse


@pytest.fixture
def client():
    return TestClient(app)


def make_mock_cell(
    tower_id: str,
    lat: float,
    lon: float,
    radio: str,
    cell_id: int,
    range_m: float = 800.0,
) -> dict[str, Any]:
    return {
        "tower_id": tower_id,
        "latitude": lat,
        "longitude": lon,
        "lat": lat,
        "lon": lon,
        "range_m": range_m,
        "radio": radio,
        "cell_id": cell_id,
        "mcc": 404,
        "mnc": 11,
        "area": 51005,
        "source": "OpenCellID",
        "is_range_estimated": True,
        "range_is_fallback": True,
        "range_source": "fallback_default",
        "fallback_reason": None,
        "warnings": [],
    }


def generate_mixed_dataset(
    center_lat: float = 28.63,
    center_lon: float = 77.22,
    n_4g: int = 60,
    n_5g: int = 40,
    n_2g: int = 20,
    seed: int = 42,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records = []
    idx = 1

    # 4G LTE
    for i in range(n_4g):
        lat = center_lat + rng.uniform(-0.015, 0.015)
        lon = center_lon + rng.uniform(-0.015, 0.015)
        records.append(make_mock_cell(f"LTE_404_11_10_{idx}", lat, lon, "LTE", idx, 800.0))
        idx += 1

    # 5G NR
    for i in range(n_5g):
        lat = center_lat + rng.uniform(-0.015, 0.015)
        lon = center_lon + rng.uniform(-0.015, 0.015)
        records.append(make_mock_cell(f"NR_404_11_20_{idx}", lat, lon, "NR", idx, 500.0))
        idx += 1

    # 2G / GSM (legacy, excluded)
    for i in range(n_2g):
        lat = center_lat + rng.uniform(-0.015, 0.015)
        lon = center_lon + rng.uniform(-0.015, 0.015)
        records.append(make_mock_cell(f"GSM_404_11_30_{idx}", lat, lon, "GSM", idx, 1000.0))
        idx += 1

    return records


# ==============================================================================
# 1. Radio Parameter Filtering & Invariants on /api/towers and /api/cells
# ==============================================================================

@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_radio_filtering_4g_only(client, monkeypatch, endpoint):
    dataset = generate_mixed_dataset(n_4g=60, n_5g=40, n_2g=20)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&radios=4G&limit=50")
    assert response.status_code == 200
    data = response.json()

    # Schema Validation
    validated = TowersResponse.model_validate(data)
    assert validated.count == 50

    # Radio assertions
    assert data["tech_distribution"] == {"4G": 50, "5G": 0}
    assert all(t["radio"] == "4G" for t in data["towers"])
    assert not any(t["radio"] == "5G" for t in data["towers"])
    assert not any(t["radio"] == "GSM" for t in data["towers"])

    # Invariants
    acc = data["accounting"]
    assert acc["available_count"] == 120
    assert acc["eligible_count"] == 60
    assert acc["selected_count"] == 50
    assert acc["excluded_radio_count"] == 60  # 40 5G + 20 GSM
    assert acc["excluded_limit_count"] == 10  # 60 eligible - 50 selected
    assert acc["excluded_count"] == 70  # 120 available - 50 selected
    assert acc["available_count"] == acc["selected_count"] + acc["excluded_count"]
    assert acc["excluded_count"] == acc["excluded_radio_count"] + acc["excluded_limit_count"]
    assert acc["selected_count"] <= 50


@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_radio_filtering_5g_only(client, monkeypatch, endpoint):
    dataset = generate_mixed_dataset(n_4g=60, n_5g=40, n_2g=20)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&radios=5G&limit=50")
    assert response.status_code == 200
    data = response.json()

    validated = TowersResponse.model_validate(data)
    assert validated.count == 40  # only 40 5G towers available, limit is 50

    assert data["tech_distribution"] == {"4G": 0, "5G": 40}
    assert all(t["radio"] == "5G" for t in data["towers"])
    assert not any(t["radio"] == "4G" for t in data["towers"])

    acc = data["accounting"]
    assert acc["available_count"] == 120
    assert acc["eligible_count"] == 40
    assert acc["selected_count"] == 40
    assert acc["excluded_radio_count"] == 80  # 60 4G + 20 GSM
    assert acc["excluded_limit_count"] == 0  # 40 eligible <= 50 limit
    assert acc["excluded_count"] == 80
    assert acc["available_count"] == acc["selected_count"] + acc["excluded_count"]
    assert acc["excluded_count"] == acc["excluded_radio_count"] + acc["excluded_limit_count"]


@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_radio_filtering_both_4g_and_5g(client, monkeypatch, endpoint):
    dataset = generate_mixed_dataset(n_4g=60, n_5g=40, n_2g=20)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    # Repeated query params: ?radios=4G&radios=5G
    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&radios=4G&radios=5G&limit=50")
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 50
    assert data["tech_distribution"]["4G"] > 0
    assert data["tech_distribution"]["5G"] > 0
    assert data["tech_distribution"]["4G"] + data["tech_distribution"]["5G"] == 50

    acc = data["accounting"]
    assert acc["available_count"] == 120
    assert acc["eligible_count"] == 100  # 60 4G + 40 5G
    assert acc["selected_count"] == 50
    assert acc["excluded_radio_count"] == 20  # 20 GSM
    assert acc["excluded_limit_count"] == 50  # 100 eligible - 50 selected
    assert acc["excluded_count"] == 70


@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_radio_default_omitted(client, monkeypatch, endpoint):
    """When radios param is omitted, default must include both 4G and 5G and exclude legacy."""
    dataset = generate_mixed_dataset(n_4g=60, n_5g=40, n_2g=20)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&limit=50")
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 50
    assert data["tech_distribution"]["4G"] > 0
    assert data["tech_distribution"]["5G"] > 0
    assert data["accounting"]["eligible_count"] == 100
    assert data["accounting"]["excluded_radio_count"] == 20


@pytest.mark.parametrize(
    "radio_query, expected_techs",
    [
        ("4G,5G", {"4G", "5G"}),
        ("5G,4G", {"4G", "5G"}),
        ("lte", {"4G"}),
        ("nr", {"5G"}),
        ("LTE,NR", {"4G", "5G"}),
        ("5gnr", {"5G"}),
        ("4g", {"4G"}),
        ("5g", {"5G"}),
    ],
)
def test_endpoint_radio_synonyms_and_formats(client, monkeypatch, radio_query, expected_techs):
    dataset = generate_mixed_dataset(n_4g=30, n_5g=30, n_2g=10)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get(f"/api/towers?lat=28.63&lon=77.22&radios={radio_query}&limit=50")
    assert response.status_code == 200
    data = response.json()

    present_techs = {r for r, count in data["tech_distribution"].items() if count > 0}
    assert present_techs.issubset(expected_techs)


# ==============================================================================
# 2. Invalid Radio Rejections with HTTP 400
# ==============================================================================

@pytest.mark.parametrize(
    "invalid_radio",
    [
        "2G",
        "GSM",
        "gsm",
        "3G",
        "UMTS",
        "umts",
        "CDMA",
        "cdma",
        "EDGE",
        "GPRS",
        "satellite",
        "WIFI",
        "unknown",
        "xyz123",
        "",
        "   ",
        ",,",
    ],
)
@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_rejects_invalid_radios_with_400(client, endpoint, invalid_radio):
    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&radios={invalid_radio}")
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert ("Allowed values: 4G, 5G" in detail) or ("At least one radio technology" in detail)


@pytest.mark.parametrize(
    "mixed_radios",
    [
        "4G,2G",
        "GSM,5G",
        "LTE,UMTS",
        "4G,invalid_val",
    ],
)
@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
def test_endpoint_rejects_mixed_valid_and_invalid_radios(client, endpoint, mixed_radios):
    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&radios={mixed_radios}")
    assert response.status_code == 400
    assert "Allowed values: 4G, 5G" in response.json()["detail"]


def test_endpoint_repeated_mixed_radios_rejected(client):
    response = client.get("/api/towers?lat=28.63&lon=77.22&radios=4G&radios=2G")
    assert response.status_code == 400
    assert "Invalid radio technology '2G'" in response.json()["detail"]


# ==============================================================================
# 3. Limit Boundary Testing (10, 50, 200 vs 422 for <10 / >200 / malformed)
# ==============================================================================

@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
@pytest.mark.parametrize("valid_limit", [10, 50, 100, 200])
def test_endpoint_valid_limits_pass(client, monkeypatch, endpoint, valid_limit):
    dataset = generate_mixed_dataset(n_4g=150, n_5g=100, n_2g=0)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&limit={valid_limit}")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == valid_limit
    assert data["accounting"]["selected_count"] == valid_limit
    assert data["accounting"]["selected_count"] <= valid_limit


@pytest.mark.parametrize("endpoint", ["/api/towers", "/api/cells"])
@pytest.mark.parametrize("invalid_limit", [0, -1, -50, 5, 9, 201, 250, 500, "abc", 15.5])
def test_endpoint_invalid_limits_fail_with_422(client, endpoint, invalid_limit):
    response = client.get(f"{endpoint}?lat=28.63&lon=77.22&limit={invalid_limit}")
    assert response.status_code == 422
    err_body = response.json()
    assert "detail" in err_body
    # Ensure it's a validation error targeting the 'limit' query parameter
    assert any("limit" in str(loc) for err in err_body["detail"] for loc in err.get("loc", []))


# ==============================================================================
# 4. Exhaustive Accounting Invariant Grid
# ==============================================================================

@pytest.mark.parametrize(
    "n_4g, n_5g, n_2g, req_radios, limit",
    [
        (0, 0, 0, ["4G", "5G"], 50),       # Empty dataset
        (5, 0, 0, ["4G"], 10),              # Smaller than min limit
        (25, 0, 0, ["4G"], 10),             # Truncated by limit=10
        (0, 30, 10, ["5G"], 20),            # 5G only, partial truncation
        (10, 10, 50, ["4G", "5G"], 200),    # All eligible selected, none limit-excluded
        (150, 100, 50, ["4G"], 200),        # 4G only truncated at max limit
        (100, 100, 100, ["5G"], 50),        # 5G only truncated at 50
        (50, 50, 50, ["4G", "5G"], 50),     # Exactly 50 selected out of 100 eligible
    ],
)
def test_accounting_invariants_grid(client, monkeypatch, n_4g, n_5g, n_2g, req_radios, limit):
    dataset = generate_mixed_dataset(n_4g=n_4g, n_5g=n_5g, n_2g=n_2g)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    query_params = f"lat=28.63&lon=77.22&limit={limit}"
    for r in req_radios:
        query_params += f"&radios={r}"

    response = client.get(f"/api/towers?{query_params}")
    assert response.status_code == 200
    data = response.json()

    # 1. Pydantic validation of whole envelope
    envelope = TowersResponse.model_validate(data)
    acc = envelope.accounting

    # 2. Mathematical invariant assertions
    assert acc.available_count == n_4g + n_5g + n_2g
    assert acc.available_count >= acc.eligible_count >= acc.selected_count >= 0
    assert acc.excluded_radio_count == acc.available_count - acc.eligible_count
    assert acc.excluded_limit_count == acc.eligible_count - acc.selected_count
    assert acc.excluded_count == acc.available_count - acc.selected_count
    assert acc.excluded_count == acc.excluded_radio_count + acc.excluded_limit_count
    assert acc.selected_count <= limit

    # 3. Structural assertions
    assert data["count"] == acc.selected_count
    assert len(data["towers"]) == acc.selected_count
    assert len(data["cells"]) == acc.selected_count
    assert data["tech_distribution"]["4G"] + data["tech_distribution"]["5G"] == acc.selected_count

    # 4. Site sector count sum invariant
    total_site_sectors = sum(s["sector_count"] for s in data["sites"])
    assert total_site_sectors == acc.selected_count

    # 5. Site entity schema validation
    for site in data["sites"]:
        SiteEntity.model_validate(site)
        assert site["sector_count"] == len(site["sectors"])


# ==============================================================================
# 5. Physical Site Entity Resolution & Co-location
# ==============================================================================

def test_site_clustering_and_colocation_metadata(client, monkeypatch):
    """Verify co-located transceivers on the same mast are assigned identical site_id and flagged."""
    # 3 towers at Site A, 1 tower at Site B
    lat_a, lon_a = 28.63000, 77.22000
    lat_b, lon_b = 28.64000, 77.23000

    dataset = [
        make_mock_cell("4G_SITE_A_1", lat_a, lon_a, "LTE", 1),
        make_mock_cell("4G_SITE_A_2", lat_a, lon_a, "LTE", 2),
        make_mock_cell("5G_SITE_A_3", lat_a, lon_a, "NR", 3),
        make_mock_cell("4G_SITE_B_1", lat_b, lon_b, "LTE", 4),
    ]

    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    response = client.get("/api/towers?lat=28.63&lon=77.22&limit=50")
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 4
    assert len(data["sites"]) == 2

    site_a = next(s for s in data["sites"] if s["site_id"] == "SITE_28.63000_77.22000")
    site_b = next(s for s in data["sites"] if s["site_id"] == "SITE_28.64000_77.23000")

    assert site_a["sector_count"] == 3
    assert set(site_a["sectors"]) == {"4G_SITE_A_1", "4G_SITE_A_2", "5G_SITE_A_3"}
    assert site_a["radios"] == ["4G", "5G"]

    assert site_b["sector_count"] == 1
    assert site_b["sectors"] == ["4G_SITE_B_1"]
    assert site_b["radios"] == ["4G"]

    # Check is_co_located flags on individual towers
    towers_by_id = {t["tower_id"]: t for t in data["towers"]}
    assert towers_by_id["4G_SITE_A_1"]["is_co_located"] is True
    assert towers_by_id["4G_SITE_A_2"]["is_co_located"] is True
    assert towers_by_id["5G_SITE_A_3"]["is_co_located"] is True
    assert towers_by_id["4G_SITE_B_1"]["is_co_located"] is False


# ==============================================================================
# 6. Bounding Box Query Support & Coordinate Validation
# ==============================================================================

def test_api_towers_bounding_box_mode(client, monkeypatch):
    dataset = generate_mixed_dataset(n_4g=20, n_5g=20, n_2g=0)
    async def mock_fetch(lat, lon, r, key):
        return dataset, [], False
    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
    monkeypatch.setattr("app._get_api_key", lambda: "mock_key")

    # Bounding box around New Delhi: west=77.1, south=28.5, east=77.3, north=28.7
    response = client.get("/api/towers?west=77.1&south=28.5&east=77.3&north=28.7&radios=4G&limit=15")
    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 15
    assert data["tech_distribution"] == {"4G": 15, "5G": 0}
    assert math.isclose(data["center"]["latitude"], 28.6, abs_tol=1e-4)
    assert math.isclose(data["center"]["longitude"], 77.2, abs_tol=1e-4)


def test_api_towers_missing_coordinates_fails_400(client):
    # Missing all coordinates
    res1 = client.get("/api/towers")
    assert res1.status_code == 400
    assert "Must provide either (lat, lon) or bounding box" in res1.json()["detail"]

    # Partial bounding box (missing east, north)
    res2 = client.get("/api/towers?west=77.1&south=28.5")
    assert res2.status_code == 400
    assert "Must provide either (lat, lon) or bounding box" in res2.json()["detail"]


@pytest.mark.parametrize(
    "bad_url",
    [
        "/api/towers?lat=95.0&lon=77.2",       # lat > 90
        "/api/towers?lat=-95.0&lon=77.2",      # lat < -90
        "/api/towers?lat=28.6&lon=185.0",      # lon > 180
        "/api/towers?lat=28.6&lon=-185.0",     # lon < -180
        "/api/towers?lat=28.6&lon=77.2&radius_m=0",     # radius <= 0
        "/api/towers?lat=28.6&lon=77.2&radius_m=6000",  # radius > 5000
    ],
)
def test_coordinate_range_validation_422(client, bad_url):
    response = client.get(bad_url)
    assert response.status_code == 422


# ==============================================================================
# 7. Server-Side OpenCellID API Key Absence (503 Service Unavailable)
# ==============================================================================

def test_api_key_missing_returns_503(client, monkeypatch):
    monkeypatch.setattr("app._get_api_key", lambda: None)

    res_towers = client.get("/api/towers?lat=28.63&lon=77.22")
    assert res_towers.status_code == 503
    assert "OpenCellID API key is not configured" in res_towers.json()["detail"]

    res_cells = client.get("/api/cells?lat=28.63&lon=77.22")
    assert res_cells.status_code == 503
    assert "OpenCellID API key is not configured" in res_cells.json()["detail"]
