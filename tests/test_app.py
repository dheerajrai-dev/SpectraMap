import pytest
from fastapi.testclient import TestClient
from app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "SpectraMap"


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_cells_endpoint_validation_error(client):
    # Invalid latitude > 90
    response = client.get("/api/cells?lat=95.0&lon=77.2&radius_m=1000")
    assert response.status_code == 422

    # Missing parameters
    response = client.get("/api/cells")
    assert response.status_code == 422


def test_cells_endpoint_success(client, monkeypatch):
    # Mock data_service.fetch_opencellid_records so test is fast and offline
    async def mock_fetch(lat, lon, radius_m, api_key):
        return [
            {
                "tower_id": "LTE_404_11_51005_123",
                "latitude": lat,
                "longitude": lon,
                "range_m": 500.0,
                "radio": "LTE",
                "cell_id": 123,
                "source": "OpenCellID",
            }
        ], [], False

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)

    response = client.get("/api/cells?lat=28.63&lon=77.22&radius_m=1000")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["center"]["latitude"] == 28.63
    assert data["center"]["longitude"] == 77.22
    assert "OpenCellID" in data["attribution"]
    assert data["cells"][0]["cell_id"] == 123
    assert data["cached"] is False


def test_cells_endpoint_cached_flag(client, monkeypatch):
    async def mock_fetch(lat, lon, radius_m, api_key):
        return [], [], True

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)

    response = client.get("/api/cells?lat=28.63&lon=77.22&radius_m=1000")
    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is True


def test_optimize_endpoint_validation_error(client):
    # Missing center field
    response = client.post("/api/optimize", json={"radius_m": 1000})
    assert response.status_code == 422

    # Out of range latitude
    bad_payload = {
        "center": {"latitude": 95.0, "longitude": 77.22},
        "radius_m": 1000,
    }
    response = client.post("/api/optimize", json=bad_payload)
    assert response.status_code == 422


def test_optimize_endpoint_success(client, monkeypatch):
    # Mock two overlapping cells
    async def mock_fetch(lat, lon, radius_m, api_key):
        cells = [
            {
                "tower_id": "T1",
                "latitude": lat,
                "longitude": lon,
                "range_m": 500.0,
                "radio": "LTE",
                "cell_id": 1,
                "source": "OpenCellID",
            },
            {
                "tower_id": "T2",
                "latitude": lat + 0.003,
                "longitude": lon,
                "range_m": 500.0,
                "radio": "LTE",
                "cell_id": 2,
                "source": "OpenCellID",
            },
        ]
        return cells, [], True

    monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)

    payload = {
        "center": {"latitude": 28.63, "longitude": 77.22},
        "radius_m": 1000.0,
    }
    response = client.post("/api/optimize", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "result_id" in data
    assert data["radius_m"] == 1000.0
    assert data["cached"] is True
    assert data["metrics"]["node_count"] == 2
    assert data["metrics"]["edge_count"] == 1
    assert data["best_algorithm"] in ["DSatur", "Welsh-Powell"]
    assert data["dsatur"]["validation"]["is_valid"] is True
    assert data["welsh_powell"]["validation"]["is_valid"] is True
    assert len(data["edges"]) == 1


