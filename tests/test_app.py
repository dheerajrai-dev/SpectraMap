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

