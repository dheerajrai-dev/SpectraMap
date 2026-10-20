"""
Milestone M2 Challenger 2 Empirical Test Suite
FastAPI /api/graph/build, /api/optimize, and /api/compare Endpoints Verification

Tests:
1. M1 Payload Integration: Passing M1 output (with cells, sites, accounting) into /api/graph/build, /api/optimize, /api/compare
2. Technology Distribution Verification: {"4G": int, "5G": int} sum == vertex_count
3. Co-located Pairs Accounting: Precise combinatorics on clustered antenna masts
4. Dual Solver Execution & Invariance: DSatur and Welsh-Powell results, independent validation on 100% of edges
5. Edge Cases & Stress: Single cell, complete cliques, zero-edge sparse graphs, radius overrides, alias harmonization, N > 25 exact solver cutoff
"""

import math
import random
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app import app
from schemas import (
    CellRecord,
    CompareRequest,
    CompareResponse,
    GraphBuildRequest,
    GraphBuildResponse,
    OptimizeRequest,
    OptimizeResponse,
    SiteEntity,
    TowersResponse,
)


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
    site_id: str | None = None,
    is_co_located: bool = False,
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
        "site_id": site_id or f"SITE_{lat:.5f}_{lon:.5f}",
        "is_co_located": is_co_located,
    }


def generate_m1_towers_payload(
    n_4g: int = 30,
    n_5g: int = 20,
    n_co_located_sites: int = 3,
    sectors_per_site: int = 3,
    center_lat: float = 28.63,
    center_lon: float = 77.22,
    seed: int = 12345,
) -> dict[str, Any]:
    """Generate a realistic M1 /api/towers response payload."""
    rng = random.Random(seed)
    cells: list[dict[str, Any]] = []
    sites: list[dict[str, Any]] = []
    idx = 1

    # 1. Generate co-located sites (each site has multiple transceivers at identical lat/lon)
    for s_idx in range(n_co_located_sites):
        s_lat = center_lat + rng.uniform(-0.01, 0.01)
        s_lon = center_lon + rng.uniform(-0.01, 0.01)
        site_id = f"SITE_{s_lat:.5f}_{s_lon:.5f}"
        site_sectors: list[str] = []
        site_radios: set[str] = set()

        for k in range(sectors_per_site):
            # Alternate or mix 4G and 5G
            radio = "4G" if (idx % 2 == 1) else "5G"
            tid = f"{radio}_404_11_SITE_{s_idx}_{idx}"
            site_sectors.append(tid)
            site_radios.add(radio)
            cells.append(
                make_mock_cell(
                    tower_id=tid,
                    lat=s_lat,
                    lon=s_lon,
                    radio=radio,
                    cell_id=idx,
                    range_m=800.0 if radio == "4G" else 500.0,
                    site_id=site_id,
                    is_co_located=True,
                )
            )
            idx += 1

        sites.append({
            "site_id": site_id,
            "latitude": s_lat,
            "longitude": s_lon,
            "sector_count": len(site_sectors),
            "sectors": site_sectors,
            "radios": sorted(list(site_radios)),
        })

    # 2. Add isolated 4G cells
    for _ in range(n_4g):
        lat = center_lat + rng.uniform(-0.02, 0.02)
        lon = center_lon + rng.uniform(-0.02, 0.02)
        tid = f"4G_404_11_SOLO_{idx}"
        site_id = f"SITE_{lat:.5f}_{lon:.5f}"
        cells.append(
            make_mock_cell(
                tower_id=tid,
                lat=lat,
                lon=lon,
                radio="4G",
                cell_id=idx,
                range_m=800.0,
                site_id=site_id,
                is_co_located=False,
            )
        )
        sites.append({
            "site_id": site_id,
            "latitude": lat,
            "longitude": lon,
            "sector_count": 1,
            "sectors": [tid],
            "radios": ["4G"],
        })
        idx += 1

    # 3. Add isolated 5G cells
    for _ in range(n_5g):
        lat = center_lat + rng.uniform(-0.02, 0.02)
        lon = center_lon + rng.uniform(-0.02, 0.02)
        tid = f"5G_404_11_SOLO_{idx}"
        site_id = f"SITE_{lat:.5f}_{lon:.5f}"
        cells.append(
            make_mock_cell(
                tower_id=tid,
                lat=lat,
                lon=lon,
                radio="5G",
                cell_id=idx,
                range_m=500.0,
                site_id=site_id,
                is_co_located=False,
            )
        )
        sites.append({
            "site_id": site_id,
            "latitude": lat,
            "longitude": lon,
            "sector_count": 1,
            "sectors": [tid],
            "radios": ["5G"],
        })
        idx += 1

    total_cells = len(cells)
    tech_dist = {
        "4G": sum(1 for c in cells if c["radio"] == "4G"),
        "5G": sum(1 for c in cells if c["radio"] == "5G"),
    }

    return {
        "source": "OpenCellID",
        "count": total_cells,
        "accounting": {
            "available_count": total_cells + 15,
            "eligible_count": total_cells,
            "selected_count": total_cells,
            "excluded_count": 15,
            "excluded_radio_count": 15,
            "excluded_limit_count": 0,
        },
        "towers": cells,
        "cells": cells,
        "sites": sites,
        "tech_distribution": tech_dist,
        "center": {"latitude": center_lat, "longitude": center_lon},
        "radius_m": 2500.0,
        "warnings": [],
        "attribution": "Cell tower data from OpenCellID, licensed under CC BY-SA 4.0.",
        "cached": False,
    }


def independent_edge_coloring_oracle(edges: list[dict[str, Any]], coloring: dict[str, int]) -> tuple[bool, int, list[tuple[str, str]]]:
    """
    Adversarial challenger oracle: directly inspects the edges and color map
    to guarantee that color(u) != color(v) for 100% of edges.
    """
    conflicts: list[tuple[str, str]] = []
    for edge in edges:
        u = edge.get("source") or edge.get("u")
        v = edge.get("target") or edge.get("v")
        if u is not None and v is not None and str(u) in coloring and str(v) in coloring:
            if coloring[str(u)] == coloring[str(v)]:
                conflicts.append((str(u), str(v)))
    return len(conflicts) == 0, len(conflicts), conflicts


# ==============================================================================
# Suite 1: Full M1 Payload Ingestion into /api/graph/build
# ==============================================================================

class TestGraphBuildEndpoint:
    def test_graph_build_with_m1_envelope(self, client):
        """Pass full M1 envelope into /api/graph/build and verify structural response."""
        m1_data = generate_m1_towers_payload(n_4g=20, n_5g=15, n_co_located_sites=2, sectors_per_site=3)
        expected_total = m1_data["count"]  # 20 + 15 + 6 = 41
        expected_4g = m1_data["tech_distribution"]["4G"]
        expected_5g = m1_data["tech_distribution"]["5G"]

        payload = {
            "cells": m1_data["cells"],
            "sites": m1_data["sites"],
            "center": m1_data["center"],
            "radius_m": m1_data["radius_m"],
        }

        response = client.post("/api/graph/build", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # 1. Pydantic schema validation
        validated = GraphBuildResponse.model_validate(data)
        metrics = validated.metrics

        # 2. Technology distribution invariant
        assert metrics.vertex_count == expected_total
        assert metrics.node_count == expected_total
        assert metrics.technology_distribution == {"4G": expected_4g, "5G": expected_5g}
        assert metrics.tech_distribution == {"4G": expected_4g, "5G": expected_5g}
        assert metrics.technology_distribution["4G"] + metrics.technology_distribution["5G"] == metrics.vertex_count

        # 3. Co-located pairs invariant
        # 2 sites each with 3 sectors => 2 * binom(3, 2) = 2 * 3 = 6 co-located pairs
        assert metrics.co_located_pairs_count == 6

        # 4. Topological consistency
        assert len(validated.nodes) == expected_total
        assert metrics.edge_count == len(validated.edges)
        assert metrics.candidate_pairs_examined == (expected_total * (expected_total - 1)) // 2
        assert metrics.edges_accepted == metrics.edge_count
        assert metrics.edges_rejected == metrics.candidate_pairs_examined - metrics.edges_accepted

        # 5. Serialized node integrity
        for node in validated.nodes:
            assert node["radio"] in ("4G", "5G")
            assert node["radio"] != "LTE" and node["radio"] != "NR"
            assert "site_id" in node
            assert "is_co_located" in node
            assert "latitude" in node and "longitude" in node

    def test_graph_build_with_towers_alias(self, client):
        """Pass 'towers' instead of 'cells' to test bidirectional schema harmonization."""
        m1_data = generate_m1_towers_payload(n_4g=10, n_5g=5, n_co_located_sites=0)
        payload = {
            "towers": m1_data["towers"],
            "radius_m": 1500.0,
        }

        response = client.post("/api/graph/build", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"]["vertex_count"] == 15
        assert data["metrics"]["technology_distribution"] == {"4G": 10, "5G": 5}

    def test_graph_build_with_raw_synonym_radios(self, client):
        """Verify raw radio strings ('LTE', 'NR', 'lte', 'nr') correctly map to 4G and 5G."""
        cells = [
            make_mock_cell("C1", 28.630, 77.220, "LTE", 1),
            make_mock_cell("C2", 28.631, 77.220, "NR", 2),
            make_mock_cell("C3", 28.632, 77.220, "lte", 3),
            make_mock_cell("C4", 28.633, 77.220, "nr", 4),
            make_mock_cell("C5", 28.634, 77.220, "5G", 5),
            make_mock_cell("C6", 28.635, 77.220, "4G", 6),
        ]
        response = client.post("/api/graph/build", json={"cells": cells})
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"]["technology_distribution"] == {"4G": 3, "5G": 3}


# ==============================================================================
# Suite 2: Full M1 Payload Ingestion into /api/optimize
# ==============================================================================

class TestOptimizeEndpoint:
    @pytest.mark.parametrize("algorithm", ["both", "dsatur", "welsh_powell", "exact"])
    def test_optimize_algorithms_and_validation(self, client, algorithm):
        """Test each algorithm mode and verify independent validation and technology distribution."""
        m1_data = generate_m1_towers_payload(n_4g=12, n_5g=8, n_co_located_sites=1, sectors_per_site=3)
        expected_total = m1_data["count"]  # 12 + 8 + 3 = 23 (<= 25 so exact also works)
        expected_4g = m1_data["tech_distribution"]["4G"]
        expected_5g = m1_data["tech_distribution"]["5G"]

        payload = {
            "cells": m1_data["cells"],
            "sites": m1_data["sites"],
            "center": m1_data["center"],
            "algorithm": algorithm,
            "radius_m": 2000.0,
        }

        response = client.post("/api/optimize", json=payload)
        assert response.status_code == 200, f"Expected 200 for algo={algorithm}, got {response.status_code}: {response.text}"
        data = response.json()

        # Schema validation
        validated = OptimizeResponse.model_validate(data)
        metrics = validated.metrics

        # Technology distribution
        assert metrics.vertex_count == expected_total
        assert metrics.technology_distribution == {"4G": expected_4g, "5G": expected_5g}
        assert metrics.technology_distribution["4G"] + metrics.technology_distribution["5G"] == metrics.vertex_count
        assert metrics.co_located_pairs_count == 3  # 1 site with 3 sectors => binom(3,2) = 3

        # Validation of active assignments
        assert validated.validation.is_valid is True
        assert validated.validation.conflict_count == 0
        assert validated.validation.missing_count == 0
        assert len(validated.assignments) == expected_total

        # Challenger oracle check on returned assignments
        is_valid, conflicts, conflict_list = independent_edge_coloring_oracle(validated.edges, validated.assignments)
        assert is_valid, f"Oracle detected conflicts in {algorithm}: {conflict_list}"
        assert conflicts == 0

        # Detailed algorithm checks
        if algorithm == "both":
            assert validated.dsatur is not None
            assert validated.welsh_powell is not None
            assert validated.dsatur.validation.is_valid is True
            assert validated.welsh_powell.validation.is_valid is True
            assert validated.best_algorithm in ("DSatur", "Welsh-Powell")

            # Check DSatur coloring with oracle
            ok_ds, c_ds, _ = independent_edge_coloring_oracle(validated.edges, validated.dsatur.coloring)
            assert ok_ds and c_ds == 0

            # Check Welsh-Powell coloring with oracle
            ok_wp, c_wp, _ = independent_edge_coloring_oracle(validated.edges, validated.welsh_powell.coloring)
            assert ok_wp and c_wp == 0

        elif algorithm == "dsatur":
            assert validated.dsatur is not None
            assert validated.best_algorithm == "DSatur"
            assert validated.dsatur.validation.is_valid is True

        elif algorithm == "welsh_powell":
            assert validated.welsh_powell is not None
            assert validated.best_algorithm == "Welsh-Powell"
            assert validated.welsh_powell.validation.is_valid is True

        elif algorithm == "exact":
            assert validated.exact is not None
            assert validated.best_algorithm == "Exact (B&B)"
            assert validated.exact.validation.is_valid is True
            assert validated.exact.proven_optimal is True

    def test_optimize_without_center_infers_from_cells(self, client):
        """When cells are provided without center, coordinates must be inferred without error."""
        cells = [
            make_mock_cell("T1", 28.50, 77.10, "4G", 1),
            make_mock_cell("T2", 28.51, 77.11, "5G", 2),
        ]
        response = client.post("/api/optimize", json={"cells": cells})
        assert response.status_code == 200
        data = response.json()
        assert data["center"]["latitude"] == 28.50
        assert data["center"]["longitude"] == 77.10


# ==============================================================================
# Suite 3: Full M1 Payload Ingestion into /api/compare
# ==============================================================================

class TestCompareEndpoint:
    def test_compare_endpoint_with_m1_envelope(self, client):
        """POST /api/compare with full M1 envelope: verifies metrics, dsatur, welsh_powell, exact, and comparison."""
        m1_data = generate_m1_towers_payload(n_4g=15, n_5g=8, n_co_located_sites=1, sectors_per_site=2)
        expected_total = m1_data["count"]  # 15 + 8 + 2 = 25 (<= 25 so exact runs)
        expected_4g = m1_data["tech_distribution"]["4G"]
        expected_5g = m1_data["tech_distribution"]["5G"]

        payload = {
            "cells": m1_data["cells"],
            "sites": m1_data["sites"],
            "center": m1_data["center"],
            "radius_m": 2500.0,
        }

        response = client.post("/api/compare", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # Schema validation
        validated = CompareResponse.model_validate(data)
        metrics = validated.metrics

        # Technology distribution & co-location
        assert metrics.vertex_count == expected_total
        assert metrics.technology_distribution == {"4G": expected_4g, "5G": expected_5g}
        assert metrics.technology_distribution["4G"] + metrics.technology_distribution["5G"] == metrics.vertex_count
        assert metrics.co_located_pairs_count == 1  # 1 site with 2 sectors => binom(2,2) = 1

        # DSatur & Welsh-Powell assertions
        assert validated.dsatur.validation.is_valid is True
        assert validated.dsatur.validation.conflict_count == 0
        assert validated.welsh_powell.validation.is_valid is True
        assert validated.welsh_powell.validation.conflict_count == 0

        # Exact solver for N <= 25
        assert validated.exact is not None
        assert validated.exact.validation.is_valid is True
        assert validated.exact.color_count <= validated.dsatur.color_count
        assert validated.exact.color_count <= validated.welsh_powell.color_count

        # Independent oracle check
        ok_ds, _, _ = independent_edge_coloring_oracle(validated.edges, validated.dsatur.coloring)
        ok_wp, _, _ = independent_edge_coloring_oracle(validated.edges, validated.welsh_powell.coloring)
        ok_ex, _, _ = independent_edge_coloring_oracle(validated.edges, validated.exact.coloring)
        assert ok_ds and ok_wp and ok_ex

        # Comparison summary metrics
        comp = validated.comparison
        assert "colors_difference" in comp
        assert "faster_heuristic" in comp
        assert "fewer_colors_heuristic" in comp
        assert "summary" in comp

    def test_compare_endpoint_exact_solver_cutoff_above_25(self, client):
        """When N > 25, the exact branch-and-bound solver must NOT run (exact is None)."""
        m1_data = generate_m1_towers_payload(n_4g=16, n_5g=12, n_co_located_sites=0)
        assert m1_data["count"] == 28  # > 25

        response = client.post("/api/compare", json={"cells": m1_data["cells"]})
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"]["vertex_count"] == 28
        assert data["exact"] is None
        assert data["dsatur"] is not None
        assert data["welsh_powell"] is not None


# ==============================================================================
# Suite 4: Technology Distribution & Co-location Combinatorics
# ==============================================================================

class TestTechnologyDistributionAndColocationEdgeCases:
    def test_homogeneous_4g_payload(self, client):
        """Homogeneous 4G payload returns 100% 4G distribution across all endpoints."""
        cells = [make_mock_cell(f"4G_{i}", 28.60 + i * 0.001, 77.20, "4G", i) for i in range(10)]
        for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            res = client.post(endpoint, json={"cells": cells})
            assert res.status_code == 200
            metrics = res.json()["metrics"]
            assert metrics["technology_distribution"] == {"4G": 10, "5G": 0}
            assert metrics["vertex_count"] == 10

    def test_homogeneous_5g_payload(self, client):
        """Homogeneous 5G payload returns 100% 5G distribution across all endpoints."""
        cells = [make_mock_cell(f"5G_{i}", 28.60 + i * 0.001, 77.20, "5G", i) for i in range(12)]
        for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            res = client.post(endpoint, json={"cells": cells})
            assert res.status_code == 200
            metrics = res.json()["metrics"]
            assert metrics["technology_distribution"] == {"4G": 0, "5G": 12}
            assert metrics["vertex_count"] == 12

    def test_exact_co_located_pairs_combinatorics(self, client):
        """
        Create 3 physical masts:
        - Mast A: 3 sectors -> binom(3,2) = 3 co-located pairs
        - Mast B: 4 sectors -> binom(4,2) = 6 co-located pairs
        - Mast C: 1 sector  -> binom(1,2) = 0 co-located pairs
        Total expected co_located_pairs_count = 3 + 6 + 0 = 9.
        """
        cells = []
        # Mast A: 2 4G, 1 5G at (28.6000, 77.2000)
        cells.append(make_mock_cell("A1", 28.6000, 77.2000, "4G", 1))
        cells.append(make_mock_cell("A2", 28.6000, 77.2000, "4G", 2))
        cells.append(make_mock_cell("A3", 28.6000, 77.2000, "5G", 3))

        # Mast B: 2 4G, 2 5G at (28.7000, 77.3000)
        cells.append(make_mock_cell("B1", 28.7000, 77.3000, "4G", 4))
        cells.append(make_mock_cell("B2", 28.7000, 77.3000, "4G", 5))
        cells.append(make_mock_cell("B3", 28.7000, 77.3000, "5G", 6))
        cells.append(make_mock_cell("B4", 28.7000, 77.3000, "5G", 7))

        # Mast C: 1 4G at (28.8000, 77.4000)
        cells.append(make_mock_cell("C1", 28.8000, 77.4000, "4G", 8))

        for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            res = client.post(endpoint, json={"cells": cells})
            assert res.status_code == 200
            data = res.json()
            metrics = data["metrics"]
            assert metrics["vertex_count"] == 8
            assert metrics["co_located_pairs_count"] == 9
            assert metrics["technology_distribution"] == {"4G": 5, "5G": 3}
            assert metrics["unique_coordinates_count"] == 3

    def test_single_point_complete_clique_unsuitable_flag(self, client):
        """When all nodes are at the identical coordinate, data_unsuitable warning must be triggered."""
        cells = [
            make_mock_cell(f"T_{i}", 28.6000, 77.2000, "4G" if i % 2 == 0 else "5G", i)
            for i in range(6)
        ]
        # 6 nodes at exact same point => K_6 complete clique => binom(6,2) = 15 edges and 15 co-located pairs
        for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            res = client.post(endpoint, json={"cells": cells})
            assert res.status_code == 200
            data = res.json()
            metrics = data["metrics"]
            assert metrics["data_unsuitable"] is True
            assert metrics["data_unsuitable_reason"] is not None
            assert metrics["co_located_pairs_count"] == 15
            assert metrics["edge_count"] == 15
            assert metrics["density"] == 1.0


# ==============================================================================
# Suite 5: Stress, Boundary Conditions & Adversarial Edge Cases
# ==============================================================================

class TestAdversarialStressAndBoundaries:
    def test_single_cell_graph(self, client):
        """Single cell graph (N=1, E=0) must be handled gracefully without divisions by zero."""
        cells = [make_mock_cell("SOLO_1", 28.60, 77.20, "5G", 1)]
        for endpoint in ["/api/graph/build", "/api/optimize", "/api/compare"]:
            res = client.post(endpoint, json={"cells": cells})
            assert res.status_code == 200
            data = res.json()
            metrics = data["metrics"]
            assert metrics["vertex_count"] == 1
            assert metrics["edge_count"] == 0
            assert metrics["density"] == 0.0
            assert metrics["technology_distribution"] == {"4G": 0, "5G": 1}

    def test_disconnected_pairs_frequency_reuse(self, client):
        """Two towers 10km apart have 0 edges and can share the same frequency channel (color 0)."""
        cells = [
            make_mock_cell("DELHI_1", 28.6000, 77.2000, "4G", 1, range_m=500.0),
            make_mock_cell("DELHI_2", 28.7000, 77.2000, "4G", 2, range_m=500.0),  # ~11km away
        ]
        res = client.post("/api/optimize", json={"cells": cells})
        assert res.status_code == 200
        data = res.json()
        assert data["metrics"]["edge_count"] == 0
        # Both towers should be colored with 0
        assert data["assignments"]["DELHI_1"] == 0
        assert data["assignments"]["DELHI_2"] == 0
        assert data["dsatur"]["color_count"] == 1

    def test_uniform_radius_override(self, client):
        """radius_override_m dynamically forces overlap or isolation."""
        # 2 towers 600m apart. Default ranges: 200m each => sum=400m < 600m => 0 edges.
        # With radius_override_m=400m => sum=800m >= 600m => 1 edge.
        cells = [
            make_mock_cell("T1", 28.6000, 77.2000, "4G", 1, range_m=200.0),
            make_mock_cell("T2", 28.6054, 77.2000, "4G", 2, range_m=200.0),  # ~600m away
        ]

        # Without override: 0 edges
        res1 = client.post("/api/graph/build", json={"cells": cells})
        assert res1.status_code == 200
        assert res1.json()["metrics"]["edge_count"] == 0

        # With override 400m: 1 edge
        res2 = client.post("/api/graph/build", json={"cells": cells, "radius_override_m": 400.0})
        assert res2.status_code == 200
        assert res2.json()["metrics"]["edge_count"] == 1

    def test_pydantic_cellrecord_interoperability_in_python_code(self):
        """Verify GraphBuildRequest and OptimizeRequest accept CellRecord instances directly in Python."""
        cell_rec = CellRecord(
            tower_id="4G_TEST_1",
            latitude=28.60,
            longitude=77.20,
            range_m=800.0,
            radio="4G",
            cell_id=1,
            mcc=404,
            mnc=11,
            area=51005,
            source="OpenCellID",
            is_range_estimated=True,
            range_is_fallback=True,
            range_source="fallback_default",
            site_id="SITE_28.60000_77.20000",
            is_co_located=False,
        )
        req = GraphBuildRequest(cells=[cell_rec])
        assert len(req.cells) == 1
        assert req.towers is not None
        assert len(req.towers) == 1

        opt_req = OptimizeRequest(cells=[cell_rec])
        assert len(opt_req.cells) == 1

        comp_req = CompareRequest(cells=[cell_rec])
        assert len(comp_req.cells) == 1

    def test_empty_cells_rejection_without_center(self, client):
        """Posting empty cells without center must return HTTP 400 or 422, never 500."""
        res_build = client.post("/api/graph/build", json={"cells": []})
        assert res_build.status_code in (400, 422)

        res_opt = client.post("/api/optimize", json={"cells": []})
        assert res_opt.status_code in (400, 422)

        res_comp = client.post("/api/compare", json={"cells": []})
        assert res_comp.status_code in (400, 422)

    def test_large_dense_graph_performance(self, client):
        """Stress-test with 50 towers: verify solver execution time, validation, and tech distribution."""
        m1_data = generate_m1_towers_payload(n_4g=30, n_5g=20, n_co_located_sites=3, sectors_per_site=3)
        assert m1_data["count"] == 59

        res = client.post("/api/optimize", json={"cells": m1_data["cells"], "algorithm": "both"})
        assert res.status_code == 200
        data = res.json()
        assert data["metrics"]["vertex_count"] == 59
        assert data["metrics"]["technology_distribution"]["4G"] + data["metrics"]["technology_distribution"]["5G"] == 59
        assert data["dsatur"]["validation"]["is_valid"] is True
        assert data["welsh_powell"]["validation"]["is_valid"] is True
        assert data["dsatur"]["runtime_ms"] < 2000.0
        assert data["welsh_powell"]["runtime_ms"] < 2000.0

    def test_adversarial_oracle_catches_tampered_conflict(self):
        """Verify the test suite's adversarial oracle is sensitive and catches any invalid coloring."""
        edges = [{"source": "T1", "target": "T2"}]
        valid_coloring = {"T1": 0, "T2": 1}
        ok, count, _ = independent_edge_coloring_oracle(edges, valid_coloring)
        assert ok is True and count == 0

        # Tampered conflict: adjacent nodes given identical color 0
        tampered_coloring = {"T1": 0, "T2": 0}
        ok, count, conflicts = independent_edge_coloring_oracle(edges, tampered_coloring)
        assert ok is False
        assert count == 1
        assert ("T1", "T2") in conflicts
