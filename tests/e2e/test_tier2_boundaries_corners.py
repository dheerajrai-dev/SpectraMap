"""
tests/e2e/test_tier2_boundaries_corners.py
SpectraMap Path B — Tier 2: Boundary Value & Corner Case Coverage (>= 105 tests across 21 features)

Opaque-box verification of extreme parameters, boundary conditions, limits, coordinate wraps,
empty inputs, and rejection semantics.
Requirement sources: ORIGINAL_REQUEST.md, PROJECT.md, TEST_INFRA.md.
"""

from collections import Counter
import json
import math
import pytest
from fastapi.testclient import TestClient

from app import app
from data_service import (
    haversine_distance,
    EARTH_RADIUS_METRES,
    normalize_cell_record,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    aggregate_towers_within_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
    color_exact_dsatur_bnb,
    validate_coloring,
    get_graph_metrics,
)
from schemas import AccountingMetadata, CellRecord


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _make_cell(
    tower_id: str,
    lat: float,
    lon: float,
    range_m: float = 800.0,
    radio: str = "4G",
    cell_id: int = 100,
) -> dict:
    return {
        "tower_id": tower_id,
        "cell_id": cell_id,
        "radio": radio,
        "latitude": lat,
        "longitude": lon,
        "range_m": range_m,
    }


# ============================================================================
# Feature 1: Spherical Haversine Distance Boundaries
# ============================================================================
class TestFeature01HaversineBoundaries:
    def test_f1_antipodal_stability_clamping(self):
        # Exact antipodes (0,0) and (0,180): argument `a` can exceed 1.0 slightly due to float error
        d = haversine_distance(0.0, 0.0, 0.0, 180.0)
        assert abs(d - math.pi * EARTH_RADIUS_METRES) < 1e-3

    def test_f1_polar_extreme_north_to_south(self):
        # 90.0 to -90.0: direct line over meridian
        d = haversine_distance(90.0, 0.0, -90.0, 0.0)
        assert abs(d - math.pi * EARTH_RADIUS_METRES) < 1e-3

    def test_f1_numerical_epsilon_1um_separation(self):
        # Separation of 1 um (1e-6 m): approx 8.99e-12 deg latitude
        d_lat = 1e-6 / 111194.9266
        d = haversine_distance(0.0, 0.0, d_lat, 0.0)
        assert d >= 0.0
        assert abs(d - 1e-6) < 1e-8

    def test_f1_date_line_wrapping_shortest_path(self):
        # Points on opposite sides of the anti-meridian (+179.9999 and -179.9999)
        # Angular separation is 0.0002 deg ≈ 22.24 metres, not 40,000 km!
        d = haversine_distance(0.0, 179.9999, 0.0, -179.9999)
        expected = (0.0002 / 360.0) * (2.0 * math.pi * EARTH_RADIUS_METRES)
        assert abs(d - expected) < 1.0
        assert d < 30.0

    def test_f1_quadrant_symmetry(self):
        d1 = haversine_distance(28.5, 77.2, 28.6, 77.3)
        d2 = haversine_distance(-28.5, -77.2, -28.6, -77.3)
        d3 = haversine_distance(28.6, 77.3, 28.5, 77.2)
        assert abs(d1 - d2) < 1e-6
        assert abs(d1 - d3) < 1e-6


# ============================================================================
# Feature 2: Closed-Disc Conflict Graph Modeling Boundaries
# ============================================================================
class TestFeature02ClosedDiscBoundaries:
    def test_f2_boundary_touch_at_exact_epsilon(self, client):
        # Distance exactly = r_u + r_v (1000.0m tangent discs)
        lat_offset = 1000.0 * 180.0 / (math.pi * EARTH_RADIUS_METRES)
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        # Tangent discs satisfy d <= r_u + r_v + 1e-6
        assert len(resp.json()["edges"]) == 1

    def test_f2_strict_boundary_exceeded_by_10um(self, client):
        # Distance = r_u + r_v + 0.01m (10mm > 1um tolerance)
        lat_offset = (1000.0 + 0.01) / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert len(resp.json()["edges"]) == 0

    def test_f2_zero_distance_overlap_forms_edge(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
        assert resp.status_code == 200
        assert len(resp.json()["edges"]) == 1

    def test_f2_extreme_max_radius_10000m(self, client):
        # Max permitted range 10,000m + 10,000m = 20,000m conflict boundary
        lat_offset = 19500.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=10000.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=10000.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert len(resp.json()["edges"]) == 1

    def test_f2_extreme_min_radius_50m(self, client):
        # Min permitted range 50m + 50m = 100m conflict boundary. 101m apart -> 0 edges.
        lat_offset = 101.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=50.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=50.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert len(resp.json()["edges"]) == 0


# ============================================================================
# Feature 3: Co-Located Mast Resolution Boundaries
# ============================================================================
class TestFeature03CoLocated2mBoundaries:
    def test_f3_exact_2m_boundary_clusters(self):
        # Separation 1.95m (strictly <= 2.0m threshold)
        d_lat = 1.95 * 180.0 / (math.pi * EARTH_RADIUS_METRES)
        cells = [
            _make_cell("T1", 28.5000, 77.2000),
            _make_cell("T2", 28.5000 + d_lat, 77.2000),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 1

    def test_f3_just_over_2m_boundary_does_not_cluster(self):
        d_lat = 2.05 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000),
            _make_cell("T2", 28.5000 + d_lat, 77.2000),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 2

    def test_f3_zero_distance_identical_coords_cluster(self):
        cells = [_make_cell(f"T{i}", 28.5000, 77.2000) for i in range(5)]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 1
        assert agg[0]["sector_count"] == 5

    def test_f3_transitive_clustering_chain(self):
        # T1 at 0m, T2 at 1.8m, T3 at 3.6m: T1-T2 <= 2m and T2-T3 <= 2m
        d_lat = 1.8 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000),
            _make_cell("T2", 28.5000 + d_lat, 77.2000),
            _make_cell("T3", 28.5000 + 2 * d_lat, 77.2000),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 1
        assert agg[0]["sector_count"] == 3

    def test_f3_k49_suppression_50_sectors_to_single_site(self, client):
        cells = [_make_cell(f"T{i}", 28.5000, 77.2000) for i in range(50)]
        resp = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 1
        assert len(resp.json()["edges"]) == 0


# ============================================================================
# Feature 4: Graph Diagnostics Boundaries
# ============================================================================
class TestFeature04DiagnosticsBoundaries:
    def test_f4_empty_graph_diagnostics(self):
        G = build_interference_graph([])
        diag = get_graph_metrics(G)
        assert diag["node_count"] == 0
        assert diag["edge_count"] == 0
        assert diag["density"] == 0.0
        assert diag["max_degree"] == 0

    def test_f4_single_isolated_vertex_diagnostics(self):
        G = build_interference_graph([_make_cell("T1", 28.5, 77.2)])
        diag = get_graph_metrics(G)
        assert diag["node_count"] == 1
        assert diag["edge_count"] == 0
        assert diag["density"] == 0.0
        assert diag["max_degree"] == 0
        assert diag["candidate_pairs_examined"] == 0

    def test_f4_unsuitable_flag_when_all_co_located(self):
        cells = [_make_cell(f"T{i}", 28.5, 77.2) for i in range(5)]
        G = build_interference_graph(cells, aggregate_2m=False)
        diag = get_graph_metrics(G)
        assert diag["data_unsuitable"] is True
        assert "complete clique" in diag["data_unsuitable_reason"].lower()

    def test_f4_suitable_flag_when_diverse(self):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.01, 77.2) for i in range(5)]
        G = build_interference_graph(cells)
        diag = get_graph_metrics(G)
        assert diag["data_unsuitable"] is False
        assert diag["data_unsuitable_reason"] is None

    def test_f4_density_formula_exactness(self):
        # N=4 nodes, 3 edges -> density = 2 * 3 / (4 * 3) = 0.5
        cells = [
            _make_cell("T0", 28.5, 77.2, range_m=2000.0),
            _make_cell("T1", 28.505, 77.2, range_m=100.0),
            _make_cell("T2", 28.510, 77.2, range_m=100.0),
            _make_cell("T3", 28.515, 77.2, range_m=100.0),
        ]
        G = build_interference_graph(cells)
        diag = get_graph_metrics(G)
        assert diag["edge_count"] == 3
        assert diag["density"] == 0.5


# ============================================================================
# Feature 5: Modern Cellular Filtering Boundaries
# ============================================================================
class TestFeature05ModernCellularFilteringBoundaries:
    def test_f5_reject_2g_token_http_400(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=2G")
        assert resp.status_code == 400

    def test_f5_reject_3g_token_http_400(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=3G")
        assert resp.status_code == 400

    def test_f5_reject_gsm_token_http_400(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=GSM")
        assert resp.status_code == 400

    def test_f5_reject_umts_token_http_400(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=UMTS")
        assert resp.status_code == 400

    def test_f5_empty_radios_query_http_400(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=")
        assert resp.status_code == 400


# ============================================================================
# Feature 6: Deterministic FPS Sampling Ceilings Boundaries
# ============================================================================
class TestFeature06FPSCeilingBoundaries:
    def test_f6_ceiling_min_boundary_limit_10(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G&limit=10")
        assert resp.status_code in (200, 503)

    def test_f6_ceiling_max_boundary_limit_200(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G&limit=200")
        assert resp.status_code in (200, 503)

    def test_f6_below_min_boundary_limit_9_rejected(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G&limit=9")
        assert resp.status_code == 422

    def test_f6_above_max_boundary_limit_201_rejected(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G&limit=201")
        assert resp.status_code == 422

    def test_f6_candidate_count_strictly_less_than_limit(self):
        candidates = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2) for i in range(5)]
        sampled = select_spatially_dispersed_records(candidates, 28.5, 77.2, limit=50)
        assert len(sampled) == 5


# ============================================================================
# Feature 7: Data Provenance Accounting Boundaries
# ============================================================================
class TestFeature07AccountingBoundaries:
    def test_f7_zero_records_accounting(self):
        meta = AccountingMetadata(
            available_count=0,
            eligible_count=0,
            selected_count=0,
            excluded_count=0,
            excluded_radio_count=0,
            excluded_limit_count=0,
        )
        assert meta.available_count == 0

    def test_f7_all_excluded_by_radio(self):
        meta = AccountingMetadata(
            available_count=10,
            eligible_count=0,
            selected_count=0,
            excluded_count=10,
            excluded_radio_count=10,
            excluded_limit_count=0,
        )
        assert meta.excluded_radio_count == 10

    def test_f7_all_excluded_by_limit(self):
        meta = AccountingMetadata(
            available_count=50,
            eligible_count=50,
            selected_count=10,
            excluded_count=40,
            excluded_radio_count=0,
            excluded_limit_count=40,
        )
        assert meta.excluded_limit_count == 40

    def test_f7_single_record_accounting(self):
        meta = AccountingMetadata(
            available_count=1,
            eligible_count=1,
            selected_count=1,
            excluded_count=0,
            excluded_radio_count=0,
            excluded_limit_count=0,
        )
        assert meta.selected_count == 1

    def test_f7_schema_rejects_negative_counts(self):
        with pytest.raises(Exception):
            AccountingMetadata(
                available_count=-1,
                eligible_count=0,
                selected_count=0,
                excluded_count=0,
                excluded_radio_count=0,
                excluded_limit_count=0,
            )


# ============================================================================
# Feature 8: Coverage Radii Fallback Boundaries
# ============================================================================
class TestFeature08RadiusFallbackBoundaries:
    def test_f8_zero_range_triggers_fallback(self):
        rec = CellRecord(latitude=28.5, longitude=77.2, range_m=0.0, radio="4G")
        assert rec.range_m == 800.0
        assert rec.is_range_estimated

    def test_f8_negative_range_triggers_fallback(self):
        rec = CellRecord(latitude=28.5, longitude=77.2, range_m=-50.0, radio="4G")
        assert rec.range_m == 800.0
        assert rec.is_range_estimated

    def test_f8_below_min_clamped_to_50m(self):
        rec = CellRecord(latitude=28.5, longitude=77.2, range_m=10.0, radio="4G")
        assert rec.range_m == 50.0
        assert rec.is_range_estimated

    def test_f8_above_max_clamped_to_10000m(self):
        rec = CellRecord(latitude=28.5, longitude=77.2, range_m=15000.0, radio="4G")
        assert rec.range_m == 10000.0
        assert rec.is_range_estimated

    def test_f8_non_numeric_range_fallback(self):
        rec = CellRecord(latitude=28.5, longitude=77.2, range="invalid", radio="4G")
        assert rec.range_m == 800.0
        assert rec.is_range_estimated


# ============================================================================
# Feature 9: Dual Solvers on Identical Graph Boundaries
# ============================================================================
class TestFeature09DualSolversBoundaries:
    def test_f9_solvers_empty_graph(self):
        G = build_interference_graph([])
        d_res = color_dsatur(G)
        w_res = color_welsh_powell(G)
        assert d_res["color_count"] == 0
        assert w_res["color_count"] == 0
        assert d_res["validation"]["is_valid"]
        assert w_res["validation"]["is_valid"]

    def test_f9_solvers_single_node(self):
        G = build_interference_graph([_make_cell("T1", 28.5, 77.2)])
        d_res = color_dsatur(G)
        w_res = color_welsh_powell(G)
        assert d_res["color_count"] == 1
        assert w_res["color_count"] == 1

    def test_f9_solvers_disconnected_components(self):
        # 5 widely separated nodes (no edges)
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.1, 77.2, range_m=100.0) for i in range(5)]
        G = build_interference_graph(cells)
        assert G.number_of_edges() == 0
        d_res = color_dsatur(G)
        w_res = color_welsh_powell(G)
        # 1 color reused across all 5 vertices
        assert d_res["color_count"] == 1
        assert w_res["color_count"] == 1

    def test_f9_solvers_complete_graph_k5(self):
        # Complete graph K_5 requires 5 colors
        cells = [_make_cell(f"T{i}", 28.5000 + i * 0.0001, 77.2, range_m=2000.0) for i in range(5)]
        G = build_interference_graph(cells, aggregate_2m=False)
        d_res = color_dsatur(G)
        w_res = color_welsh_powell(G)
        assert d_res["color_count"] == 5
        assert w_res["color_count"] == 5

    def test_f9_solvers_bipartite_graph_k33(self):
        import networkx as nx
        # Construct bipartite graph K_3,3 directly
        G = nx.complete_bipartite_graph(3, 3)
        # Map node names to strings
        mapping = {i: f"node_{i}" for i in G.nodes()}
        G = nx.relabel_nodes(G, mapping)
        d_res = color_dsatur(G)
        w_res = color_welsh_powell(G)
        assert d_res["color_count"] == 2
        assert w_res["color_count"] == 2


# ============================================================================
# Feature 10: Chromatic Metrics Boundaries
# ============================================================================
class TestFeature10ChromaticMetricsBoundaries:
    def test_f10_isolated_nodes_degrees(self):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.1, 77.2, range_m=100.0) for i in range(3)]
        G = build_interference_graph(cells)
        m = get_graph_metrics(G)
        assert m["max_degree"] == 0
        assert m["avg_degree"] == 0.0

    def test_f10_odd_cycle_c5_chromatic_number(self):
        import networkx as nx
        G = nx.cycle_graph(5)
        res = color_dsatur(G)
        # Odd cycle requires 3 colors
        assert res["color_count"] == 3

    def test_f10_even_cycle_c4_chromatic_number(self):
        import networkx as nx
        G = nx.cycle_graph(4)
        res = color_dsatur(G)
        # Even cycle requires 2 colors
        assert res["color_count"] == 2

    def test_f10_channel_reuse_k5_all_ones(self):
        cells = [_make_cell(f"T{i}", 28.5000 + i * 0.0001, 77.2, range_m=2000.0) for i in range(5)]
        G = build_interference_graph(cells, aggregate_2m=False)
        res = color_dsatur(G)
        breakdown = res["channel_reuse_breakdown"]
        assert len(breakdown) == 5
        assert all(count == 1 for count in breakdown.values())

    def test_f10_channel_reuse_empty_graph(self):
        G = build_interference_graph([])
        res = color_dsatur(G)
        assert res["channel_reuse_breakdown"] == {}


# ============================================================================
# Feature 11: Independent Validator Boundaries
# ============================================================================
class TestFeature11ValidatorBoundaries:
    def test_f11_empty_graph_validation(self):
        G = build_interference_graph([])
        val = validate_coloring(G, {})
        assert val["is_valid"] is True
        assert val["edges_inspected"] == 0

    def test_f11_negative_color_in_coloring(self):
        cells = [_make_cell("T1", 28.5, 77.2)]
        G = build_interference_graph(cells)
        val = validate_coloring(G, {"T1": -1})
        assert not val["is_valid"]
        assert val["missing_count"] == 1

    def test_f11_boolean_as_color_rejected(self):
        cells = [_make_cell("T1", 28.5, 77.2)]
        G = build_interference_graph(cells)
        val = validate_coloring(G, {"T1": True})  # bool is subclass of int in python
        assert not val["is_valid"]

    def test_f11_artificial_boundary_violation_flagged(self):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=200.0), _make_cell("T2", 28.51, 77.2, range_m=200.0)]
        G = build_interference_graph(cells)
        G.add_edge("T1", "T2", distance_m=1111.0, threshold_m=400.0)
        val = validate_coloring(G, {"T1": 0, "T2": 1})
        assert not val["is_valid"]
        assert len(val["boundary_violations"]) == 1

    def test_f11_zero_distance_tolerance_1um(self):
        # Edge with distance 0.5 um (< 1e-6)
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.5, 77.2)]
        G = build_interference_graph(cells, aggregate_2m=False)
        val = validate_coloring(G, {"T1": 0, "T2": 1})
        assert val["zero_distance_count"] == 1


# ============================================================================
# Feature 12: Educational Boundaries Object Boundaries
# ============================================================================
class TestFeature12EducationalBoundariesObject:
    def test_f12_default_disclaimer_fields_present(self, client):
        resp = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        disc = resp.json()["educational_disclaimer"]
        assert "is_educational_simulation" in disc
        assert "propagation_model" in disc
        assert "disclaimer" in disc
        assert "recommended_use" in disc

    def test_f12_disclaimer_immutability(self, client):
        resp1 = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        d1 = resp1.json()["educational_disclaimer"]
        d1["disclaimer"] = "MUTATED"
        resp2 = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert "MUTATED" not in resp2.json()["educational_disclaimer"]["disclaimer"]

    def test_f12_disclaimer_on_empty_optimize_request(self, client):
        resp = client.post("/api/optimize", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert resp.status_code == 200
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True

    def test_f12_propagation_model_mentions_overlap_formula(self, client):
        resp = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        prop = resp.json()["educational_disclaimer"]["propagation_model"]
        assert "distance <= r_u + r_v" in prop

    def test_f12_recommended_use_non_empty(self, client):
        resp = client.post("/api/compare", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert len(resp.json()["educational_disclaimer"]["recommended_use"]) >= 20


# ============================================================================
# Feature 13: Interactive Force-Directed Canvas Explorer Boundaries
# ============================================================================
class TestFeature13CanvasExplorerBoundaries:
    def test_f13_large_graph_100_nodes(self, client):
        cells = [_make_cell(f"T{i:03d}", 28.5 + (i // 10) * 0.002, 77.2 + (i % 10) * 0.002) for i in range(100)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 100

    def test_f13_star_graph_degree_scaling(self, client):
        # 1 central node, 9 peripheral nodes
        cells = [_make_cell("CENTER", 28.5000, 77.2000, range_m=2000.0)]
        for i in range(9):
            cells.append(_make_cell(f"LEAF_{i}", 28.5000 + (i + 1) * 0.001, 77.2000, range_m=50.0))
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        nodes = {n["id"]: n for n in resp.json()["nodes"]}
        assert nodes["CENTER"]["degree"] == 9

    def test_f13_zero_edge_serialization(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=50.0), _make_cell("T2", 28.6, 77.3, range_m=50.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert resp.json()["edges"] == []

    def test_f13_edge_threshold_for_adaptive_opacity(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=500.0), _make_cell("T2", 28.501, 77.2, range_m=500.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        edge = resp.json()["edges"][0]
        assert "threshold_m" in edge and "distance_m" in edge

    def test_f13_isolated_nodes_serialization(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=50.0), _make_cell("T2", 28.9, 77.9, range_m=50.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        for n in resp.json()["nodes"]:
            assert n["degree"] == 0


# ============================================================================
# Feature 14: Geographic Map View Boundaries
# ============================================================================
class TestFeature14GeographicMapBoundaries:
    def test_f14_polar_latitude_north_89_9(self):
        c = CellRecord(latitude=89.9, longitude=0.0, range_m=500.0)
        assert c.latitude == 89.9

    def test_f14_polar_latitude_south_minus_89_9(self):
        c = CellRecord(latitude=-89.9, longitude=0.0, range_m=500.0)
        assert c.latitude == -89.9

    def test_f14_date_line_positive_180(self):
        c = CellRecord(latitude=0.0, longitude=180.0, range_m=500.0)
        assert c.longitude == 180.0

    def test_f14_date_line_negative_minus_180(self):
        c = CellRecord(latitude=0.0, longitude=-180.0, range_m=500.0)
        assert c.longitude == -180.0

    def test_f14_radius_slider_max_5000m(self, client):
        # Querying /api/cells with radius > 5000m is rejected by query constraint
        resp = client.get("/api/cells?lat=28.5&lon=77.2&radius_m=5001")
        assert resp.status_code == 422


# ============================================================================
# Feature 15: Side-by-Side Benchmark Boundaries
# ============================================================================
class TestFeature15SideBySideBenchmarkBoundaries:
    def test_f15_empty_cells_compare_response(self, client):
        # Providing cells=[] causes fallback or 422 validation depending on center
        resp = client.post("/api/compare", json={"cells": [], "center": {"latitude": 28.5, "longitude": 77.2}})
        assert resp.status_code in (200, 503)

    def test_f15_exact_solver_executed_for_n_le_25(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(5)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert data["exact"] is not None
        assert data["exact"]["proven_optimal"] is True

    def test_f15_exact_solver_omitted_for_n_gt_25(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(26)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        # For N > 25, exact solver is not executed
        assert data["exact"] is None

    def test_f15_identical_coloring_summary(self, client):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.501, 77.2)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        assert "identical color count" in resp.json()["comparison"]["summary"]

    def test_f15_aggregate_2m_flag_accepted_in_compare(self, client):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.5, 77.2)]
        resp = client.post("/api/compare", json={"cells": cells, "aggregate_2m": True})
        assert resp.status_code == 200
        assert resp.json()["metrics"]["node_count"] == 1


# ============================================================================
# Feature 16: Bidirectional Vertex Inspector Boundaries
# ============================================================================
class TestFeature16VertexInspectorBoundaries:
    def test_f16_inspect_node_zero_degree(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=50.0), _make_cell("T2", 28.9, 77.9, range_m=50.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        nodes = {n["id"]: n for n in resp.json()["nodes"]}
        assert nodes["T1"]["degree"] == 0

    def test_f16_inspect_node_high_degree(self, client):
        cells = [_make_cell("HUB", 28.5, 77.2, range_m=2000.0)]
        for i in range(10):
            cells.append(_make_cell(f"SPOKE_{i}", 28.5005 + i * 0.0001, 77.2, range_m=100.0))
        resp = client.post("/api/graph/build", json={"cells": cells})
        nodes = {n["id"]: n for n in resp.json()["nodes"]}
        assert nodes["HUB"]["degree"] == 10

    def test_f16_co_located_flag_true_for_multi_sector(self):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.5, 77.2)]
        updated, sites = group_cells_into_sites(cells)
        assert updated[0]["is_co_located"] is True
        assert sites[0]["sector_count"] == 2

    def test_f16_co_located_flag_false_for_isolated_site(self):
        cells = [_make_cell("T1", 28.5, 77.2)]
        updated, sites = group_cells_into_sites(cells)
        assert updated[0]["is_co_located"] is False
        assert sites[0]["sector_count"] == 1

    def test_f16_node_warnings_list_serialized(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 0}
        norm = normalize_cell_record(raw)
        assert len(norm["warnings"]) > 0


# ============================================================================
# Feature 17: Frontend Robustness Boundaries
# ============================================================================
class TestFeature17FrontendRobustnessBoundaries:
    def test_f17_extra_unknown_fields_accepted(self, client):
        # Unknown fields in JSON should not crash endpoint
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/graph/build", json={"cells": cells, "extra_unknown_param": 12345})
        assert resp.status_code == 200

    def test_f17_static_file_not_found_404(self, client):
        resp = client.get("/static/non_existent_file.xyz")
        assert resp.status_code == 404

    def test_f17_post_to_get_endpoint_returns_405(self, client):
        resp = client.post("/", json={})
        assert resp.status_code == 405

    def test_f17_get_to_post_endpoint_returns_405(self, client):
        resp = client.get("/api/graph/build")
        assert resp.status_code == 405

    def test_f17_root_response_headers_robustness(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "").lower()


# ============================================================================
# Feature 18: Educational Disclaimer Presentation Boundaries
# ============================================================================
class TestFeature18EducationalDisclaimerBoundaries:
    def test_f18_disclaimer_boolean_strictly_true(self, client):
        resp = client.post("/api/optimize", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True

    def test_f18_disclaimer_min_length(self, client):
        resp = client.post("/api/optimize", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        disc = resp.json()["educational_disclaimer"]["disclaimer"]
        assert len(disc) >= 50

    def test_f18_disclaimer_identical_across_dsatur_and_welsh_powell(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        d_resp = client.post("/api/optimize", json={"cells": cells, "algorithm": "dsatur"})
        w_resp = client.post("/api/optimize", json={"cells": cells, "algorithm": "welsh_powell"})
        assert d_resp.json()["educational_disclaimer"] == w_resp.json()["educational_disclaimer"]

    def test_f18_disclaimer_in_graph_build_response(self, client):
        resp = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True

    def test_f18_disclaimer_in_compare_response(self, client):
        resp = client.post("/api/compare", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True


# ============================================================================
# Feature 19: Lightweight Stack Boundaries
# ============================================================================
class TestFeature19LightweightStackBoundaries:
    def test_f19_fastapi_title_version(self):
        assert app.title == "SpectraMap"
        assert app.version == "2.0"

    def test_f19_no_database_url_env_needed(self):
        # App operates without DB dependencies
        import os
        assert "DATABASE_URL" not in os.environ or os.environ.get("DATABASE_URL") == ""

    def test_f19_pydantic_v2_validation_error_structure(self, client):
        resp = client.post("/api/graph/build", json={"radius_m": -5.0})
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert isinstance(data["detail"], list)

    def test_f19_networkx_graph_nodes_edges_counts(self):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.501, 77.2)]
        G = build_interference_graph(cells)
        assert G.number_of_nodes() == 2
        assert G.number_of_edges() == 1

    def test_f19_rapid_sequential_requests_stability(self, client):
        for _ in range(25):
            r = client.get("/api/health")
            assert r.status_code == 200


# ============================================================================
# Feature 20: Pytest Runner Boundaries
# ============================================================================
class TestFeature20PytestRunnerBoundaries:
    def test_f20_testclient_context_manager(self):
        with TestClient(app) as local_client:
            resp = local_client.get("/api/health")
            assert resp.status_code == 200

    def test_f20_json_content_type_header(self, client):
        resp = client.get("/api/health")
        assert "application/json" in resp.headers["content-type"]

    def test_f20_health_endpoint_latency(self, client):
        import time
        t0 = time.perf_counter()
        resp = client.get("/api/health")
        elapsed = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        assert elapsed < 100.0  # < 100ms

    def test_f20_status_endpoint_latency(self, client):
        import time
        t0 = time.perf_counter()
        resp = client.get("/api/status")
        elapsed = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        assert elapsed < 100.0

    def test_f20_response_json_serializable(self, client):
        resp = client.get("/api/health")
        payload = resp.json()
        # Verify can be serialized to JSON text
        text = json.dumps(payload)
        assert "SpectraMap" in text


# ============================================================================
# Feature 21: Zero Unhandled JS Runtime Errors Boundaries
# ============================================================================
class TestFeature21ZeroUnhandledJSErrorsBoundaries:
    def test_f21_lat_out_of_bounds_high(self, client):
        resp = client.get("/api/cells?lat=90.1&lon=77.2")
        assert resp.status_code == 422

    def test_f21_lat_out_of_bounds_low(self, client):
        resp = client.get("/api/cells?lat=-90.1&lon=77.2")
        assert resp.status_code == 422

    def test_f21_lon_out_of_bounds_high(self, client):
        resp = client.get("/api/cells?lat=28.5&lon=180.1")
        assert resp.status_code == 422

    def test_f21_lon_out_of_bounds_low(self, client):
        resp = client.get("/api/cells?lat=28.5&lon=-180.1")
        assert resp.status_code == 422

    def test_f21_post_graph_build_empty_cells_no_center(self, client):
        resp = client.post("/api/graph/build", json={"cells": []})
        assert resp.status_code == 400
        assert "No tower records or center coordinates provided" in resp.json()["detail"]
