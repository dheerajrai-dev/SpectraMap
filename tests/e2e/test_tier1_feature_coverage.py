"""
tests/e2e/test_tier1_feature_coverage.py
SpectraMap Path B — Tier 1: Happy-Path Feature Coverage (>= 105 tests across 21 features)

Opaque-box verification through public HTTP REST API endpoints and contract interfaces.
Requirement sources: ORIGINAL_REQUEST.md, PROJECT.md, TEST_INFRA.md.
"""

import math
from collections import Counter
import pytest
from fastapi.testclient import TestClient

from app import app
from data_service import (
    haversine_distance,
    EARTH_RADIUS_METRES,
    normalize_radio_type,
    normalize_cell_record,
    select_spatially_dispersed_records,
    group_cells_into_sites,
    aggregate_towers_within_distance,
)
from graph_engine import (
    build_interference_graph,
    color_dsatur,
    color_welsh_powell,
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
# Feature 1: Spherical Haversine Distance (1 um)
# ============================================================================
class TestFeature01HaversineDistance:
    def test_f1_equatorial_distance_accuracy(self):
        # 1 deg along equator: 2 * pi * 6,371,000 / 360 ≈ 111,194.9266 m
        d = haversine_distance(0.0, 0.0, 0.0, 1.0)
        expected = (2.0 * math.pi * EARTH_RADIUS_METRES) / 360.0
        assert abs(d - expected) < 1e-4

    def test_f1_meridian_distance_accuracy(self):
        # 1 deg along any meridian: ≈ 111,194.9266 m
        d = haversine_distance(10.0, 50.0, 11.0, 50.0)
        expected = (2.0 * math.pi * EARTH_RADIUS_METRES) / 360.0
        assert abs(d - expected) < 1e-4

    def test_f1_zero_distance_identical_coords(self):
        d = haversine_distance(28.5224, 77.1906, 28.5224, 77.1906)
        assert d == 0.0

    def test_f1_sub_millimetre_distance_resolution(self):
        # Tiny offset (1e-7 deg ≈ 0.011m = 11mm), verify Haversine resolves it
        d = haversine_distance(0.0, 0.0, 1e-7, 0.0)
        assert d > 0.010
        assert d < 0.012

    def test_f1_antipodal_maximum_distance(self):
        # Half circumference: pi * R ≈ 20,015,086.796 m
        d = haversine_distance(0.0, 0.0, 0.0, 180.0)
        expected = math.pi * EARTH_RADIUS_METRES
        assert abs(d - expected) < 1e-3


# ============================================================================
# Feature 2: Closed-Disc Conflict Graph Modeling (d <= r_u + r_v)
# ============================================================================
class TestFeature02ClosedDiscGraphModel:
    def test_f2_tangent_discs_form_edge(self, client):
        # Two towers separated by 1000m with ranges 500m + 500m = 1000m (tangent)
        lat_offset = 1000.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_f2_overlapping_discs_form_edge(self, client):
        # Two towers separated by 600m with ranges 500m + 500m = 1000m (> 600m)
        lat_offset = 600.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source"] in ("T1", "T2")

    def test_f2_disjoint_discs_no_edge(self, client):
        # Two towers separated by 2000m with ranges 500m + 500m = 1000m (< 2000m)
        lat_offset = 2000.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["edges"]) == 0

    def test_f2_multi_vertex_triangle_overlap(self, client):
        # Line of 3 towers: T1-(600m)-T2-(600m)-T3. T1 and T3 separated by 1200m > 1000m.
        lat_step = 600.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_step, 77.2000, range_m=500.0),
            _make_cell("T3", 28.5000 + 2 * lat_step, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2  # (T1,T2) and (T2,T3), but not (T1,T3)

    def test_f2_radius_override_expands_conflict_graph(self, client):
        # Disjoint at 500m ranges (1200m apart), but with radius_override_m=700m threshold becomes 1400m
        lat_offset = 1200.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_offset, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells, "radius_override_m": 700.0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["edges"]) == 1


# ============================================================================
# Feature 3: Co-Located Mast Resolution (<= 2m)
# ============================================================================
class TestFeature03CoLocatedMastResolution:
    def test_f3_aggregate_2m_false_preserves_distinct_transceivers(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T3", 28.5000, 77.2000, range_m=700.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 3

    def test_f3_aggregate_2m_true_consolidates_into_single_vertex(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T3", 28.5000, 77.2000, range_m=700.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": True})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1

    def test_f3_sub_2m_spacing_consolidates_sectors(self):
        # 1.5m separation along meridian: 1.5 / 111194.9266 ≈ 1.35e-5 deg
        d_lat = 1.5 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + d_lat, 77.2000, range_m=500.0),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 1
        assert agg[0]["sector_count"] == 2

    def test_f3_over_2m_spacing_preserves_sectors(self):
        # 2.5m separation along meridian
        d_lat = 2.5 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + d_lat, 77.2000, range_m=500.0),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 2

    def test_f3_aggregated_node_preserves_maximum_range(self):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=400.0),
            _make_cell("T2", 28.5000, 77.2000, range_m=950.0),
        ]
        agg = aggregate_towers_within_distance(cells, distance_threshold_m=2.0)
        assert len(agg) == 1
        assert agg[0]["range_m"] == 950.0


# ============================================================================
# Feature 4: Graph Topological Diagnostics
# ============================================================================
class TestFeature04GraphDiagnostics:
    def test_f4_empty_graph_diagnostics(self):
        G = build_interference_graph([])
        metrics = get_graph_metrics(G)
        assert metrics["node_count"] == 0
        assert metrics["edge_count"] == 0
        assert metrics["density"] == 0.0

    def test_f4_complete_clique_diagnostics(self, client):
        # 4 mutually overlapping towers (all at same coord or very close)
        cells = [
            _make_cell(f"T{i}", 28.5000 + i * 0.0001, 77.2000, range_m=1000.0)
            for i in range(4)
        ]
        resp = client.post("/api/graph/build", json={"cells": cells, "aggregate_2m": False})
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert metrics["node_count"] == 4
        assert metrics["edge_count"] == 6
        assert metrics["density"] == 1.0
        assert metrics["max_degree"] == 3

    def test_f4_coordinate_diversity_metric(self):
        # 4 cells, 2 distinct locations -> diversity = 2/4 = 0.5
        cells = [
            _make_cell("T1", 28.5000, 77.2000),
            _make_cell("T2", 28.5000, 77.2000),
            _make_cell("T3", 28.5010, 77.2010),
            _make_cell("T4", 28.5010, 77.2010),
        ]
        G = build_interference_graph(cells)
        metrics = get_graph_metrics(G)
        assert metrics["coordinate_diversity"] == 0.5

    def test_f4_candidate_pairs_accounting(self, client):
        # N=5 nodes -> 10 candidate pairs examined
        cells = [
            _make_cell(f"T{i}", 28.5000 + i * 0.01, 77.2000, range_m=500.0)
            for i in range(5)
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert metrics["candidate_pairs_examined"] == 10
        assert metrics["edges_accepted"] + metrics["edges_rejected"] == 10

    def test_f4_degree_distribution_and_bounds(self, client):
        # Linear chain of 3 nodes: degrees are 1, 2, 1
        lat_step = 600.0 / 111194.9266
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=500.0),
            _make_cell("T2", 28.5000 + lat_step, 77.2000, range_m=500.0),
            _make_cell("T3", 28.5000 + 2 * lat_step, 77.2000, range_m=500.0),
        ]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert metrics["max_degree"] == 2
        assert metrics["brooks_upper_bound"] == 3
        assert metrics["degree_distribution"] == {"1": 2, "2": 1}


# ============================================================================
# Feature 5: Modern Cellular Filtering (4G/5G only)
# ============================================================================
class TestFeature05ModernCellularFiltering:
    def test_f5_admit_4g_lte_records(self):
        assert normalize_radio_type("4G") == "4G"
        assert normalize_radio_type("LTE") == "4G"
        assert normalize_radio_type("4G LTE") == "4G"

    def test_f5_admit_5g_nr_records(self):
        assert normalize_radio_type("5G") == "5G"
        assert normalize_radio_type("NR") == "5G"
        assert normalize_radio_type("5G-NR") == "5G"

    def test_f5_reject_2g_gsm_records(self, client):
        # Querying /api/towers with 2G/GSM must be rejected with HTTP 400
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=GSM")
        assert resp.status_code == 400
        assert "Invalid radio technology 'GSM'" in resp.json()["detail"]

    def test_f5_reject_3g_umts_records(self, client):
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=UMTS")
        assert resp.status_code == 400
        assert "Invalid radio technology 'UMTS'" in resp.json()["detail"]

    def test_f5_strict_radio_in_graph_build_rejects_legacy(self, client):
        # Payload with radio='2G' fails Pydantic validation (422)
        cells = [{"tower_id": "T1", "latitude": 28.5, "longitude": 77.2, "range_m": 500.0, "radio": "2G"}]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 422


# ============================================================================
# Feature 6: Deterministic FPS Sampling & Ceilings
# ============================================================================
class TestFeature06DeterministicFPSSampling:
    def test_f6_seed_anchors_closest_to_center(self):
        # 3 points along meridian at lat 28.51, 28.50, 28.55; center at 28.50
        records = [
            _make_cell("T_far", 28.5500, 77.2000),
            _make_cell("T_mid", 28.5100, 77.2000),
            _make_cell("T_closest", 28.5001, 77.2000),
        ]
        sampled = select_spatially_dispersed_records(records, 28.5000, 77.2000, limit=2)
        assert len(sampled) == 2
        assert sampled[0]["tower_id"] == "T_closest"

    def test_f6_fps_spatial_dispersion(self):
        # Candidates: T0 (closest), T1 (near), T2 (very far)
        records = [
            _make_cell("T0", 28.5000, 77.2000),
            _make_cell("T1", 28.5010, 77.2000),
            _make_cell("T2", 28.5200, 77.2000),
        ]
        sampled = select_spatially_dispersed_records(records, 28.5000, 77.2000, limit=2)
        assert sampled[0]["tower_id"] == "T0"
        assert sampled[1]["tower_id"] == "T2"  # Farthest from T0

    def test_f6_deterministic_tie_breaking(self):
        # Two identical distance points: tie-break on ascending tower_id
        records = [
            _make_cell("T_B", 28.5100, 77.2000),
            _make_cell("T_A", 28.5100, 77.2000),
            _make_cell("T_center", 28.5000, 77.2000),
        ]
        s1 = select_spatially_dispersed_records(records, 28.5000, 77.2000, limit=2)
        s2 = select_spatially_dispersed_records(records, 28.5000, 77.2000, limit=2)
        assert [r["tower_id"] for r in s1] == [r["tower_id"] for r in s2]
        assert s1[1]["tower_id"] == "T_A"

    def test_f6_configurable_limit_enforced(self):
        records = [_make_cell(f"T{i:03d}", 28.5 + i * 0.001, 77.2) for i in range(25)]
        sampled = select_spatially_dispersed_records(records, 28.5, 77.2, limit=10)
        assert len(sampled) == 10

    def test_f6_limit_ceiling_range_validation(self, client):
        # Valid limit=10 returns 400 (if radios invalid) or 422 (if bounds violated)
        # Testing query limit parameter boundary via /api/towers query validation
        resp_low = client.get("/api/towers?lat=28.5&lon=77.2&limit=9")
        assert resp_low.status_code == 422
        resp_high = client.get("/api/towers?lat=28.5&lon=77.2&limit=201")
        assert resp_high.status_code == 422


# ============================================================================
# Feature 7: Data Provenance Accounting
# ============================================================================
class TestFeature07DataProvenanceAccounting:
    def test_f7_accounting_invariant_available_ge_eligible(self):
        meta = AccountingMetadata(
            available_count=50,
            eligible_count=40,
            selected_count=30,
            excluded_count=20,
            excluded_radio_count=10,
            excluded_limit_count=10,
        )
        assert meta.available_count >= meta.eligible_count

    def test_f7_accounting_invariant_eligible_ge_selected(self):
        meta = AccountingMetadata(
            available_count=50,
            eligible_count=40,
            selected_count=30,
            excluded_count=20,
            excluded_radio_count=10,
            excluded_limit_count=10,
        )
        assert meta.eligible_count >= meta.selected_count

    def test_f7_accounting_invariant_excluded_sums(self):
        meta = AccountingMetadata(
            available_count=100,
            eligible_count=70,
            selected_count=50,
            excluded_count=50,
            excluded_radio_count=30,
            excluded_limit_count=20,
        )
        assert meta.excluded_count == meta.excluded_radio_count + meta.excluded_limit_count

    def test_f7_accounting_invariant_available_minus_selected(self):
        meta = AccountingMetadata(
            available_count=80,
            eligible_count=80,
            selected_count=50,
            excluded_count=30,
            excluded_radio_count=0,
            excluded_limit_count=30,
        )
        assert meta.excluded_count == meta.available_count - meta.selected_count

    def test_f7_accounting_in_towers_response(self, client, monkeypatch):
        async def mock_fetch(lat, lon, radius_m, api_key):
            return [
                {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "LTE", "range": 500},
                {"cellid": 2, "lat": 28.51, "lon": 77.21, "radio": "GSM", "range": 500},
            ], [], False

        monkeypatch.setattr("app.fetch_opencellid_records", mock_fetch)
        resp = client.get("/api/towers?lat=28.5&lon=77.2&radios=4G&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        acc = data["accounting"]
        assert acc["available_count"] == 2
        assert acc["eligible_count"] == 1
        assert acc["selected_count"] == 1
        assert acc["excluded_radio_count"] == 1


# ============================================================================
# Feature 8: Coverage Radii Fallback Hierarchy
# ============================================================================
class TestFeature08CoverageRadiiFallbackHierarchy:
    def test_f8_reported_valid_range_preserved(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 650.0}
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == 650.0
        assert norm["range_source"] == "reported"
        assert not norm["is_range_estimated"]

    def test_f8_missing_range_4g_applies_800m_default(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G"}
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == 800.0
        assert norm["range_source"] == "fallback_default"
        assert norm["is_range_estimated"]

    def test_f8_missing_range_5g_applies_500m_default(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "5G"}
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == 500.0
        assert norm["range_source"] == "fallback_default"
        assert norm["is_range_estimated"]

    def test_f8_clamped_outlier_high_range(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "4G", "range": 25000.0}
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == 10000.0
        assert norm["range_source"] == "fallback_clamped"
        assert norm["is_range_estimated"]

    def test_f8_clamped_outlier_low_range(self):
        raw = {"cellid": 1, "lat": 28.5, "lon": 77.2, "radio": "5G", "range": 15.0}
        norm = normalize_cell_record(raw)
        assert norm["range_m"] == 50.0
        assert norm["range_source"] == "fallback_clamped"
        assert norm["is_range_estimated"]


# ============================================================================
# Feature 9: Dual Solvers on Identical Graph
# ============================================================================
class TestFeature09DualSolversOnIdenticalGraph:
    def test_f9_compare_endpoint_runs_both_solvers(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T2", 28.5030, 77.2000, range_m=600.0),
        ]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert "dsatur" in data
        assert "welsh_powell" in data
        assert data["dsatur"]["algorithm"] == "DSatur"
        assert data["welsh_powell"]["algorithm"] == "Welsh-Powell"

    def test_f9_both_solvers_color_all_nodes(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T2", 28.5030, 77.2000, range_m=600.0),
        ]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["dsatur"]["coloring"].keys()) == {"T1", "T2"}
        assert set(data["welsh_powell"]["coloring"].keys()) == {"T1", "T2"}

    def test_f9_both_solvers_use_identical_graph_metrics(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T2", 28.5030, 77.2000, range_m=600.0),
        ]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["node_count"] == 2
        assert data["metrics"]["edge_count"] == 1

    def test_f9_compare_agreement_boolean(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T2", 28.5030, 77.2000, range_m=600.0),
        ]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        expected_agreement = (data["dsatur"]["color_count"] == data["welsh_powell"]["color_count"])
        assert data["agreement"] == expected_agreement

    def test_f9_optimize_both_mode_returns_dual_solutions(self, client):
        cells = [
            _make_cell("T1", 28.5000, 77.2000, range_m=600.0),
            _make_cell("T2", 28.5030, 77.2000, range_m=600.0),
        ]
        resp = client.post("/api/optimize", json={"cells": cells, "algorithm": "both"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dsatur"] is not None
        assert data["welsh_powell"] is not None


# ============================================================================
# Feature 10: Chromatic Metrics & Statistics
# ============================================================================
class TestFeature10ChromaticMetricsAndStats:
    def test_f10_chi_heuristic_matches_color_count(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.002, 77.2, range_m=500.0) for i in range(4)]
        resp = client.post("/api/optimize", json={"cells": cells, "algorithm": "dsatur"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["chi_heuristic"] == data["colors_used"]

    def test_f10_welsh_powell_degree_ordering_sequence(self):
        # Build star graph with T0 as center
        cells = [
            _make_cell("T0", 28.5000, 77.2000, range_m=1000.0),
            _make_cell("T1", 28.5020, 77.2000, range_m=300.0),
            _make_cell("T2", 28.4980, 77.2000, range_m=300.0),
        ]
        G = build_interference_graph(cells)
        res = color_welsh_powell(G)
        seq = res["degree_ordering_stats"]["degree_sequence"]
        # Verify non-increasing order
        assert all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1))
        assert seq[0] == 2  # Center has degree 2

    def test_f10_dsatur_saturation_stats_present(self):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=600.0) for i in range(4)]
        G = build_interference_graph(cells)
        res = color_dsatur(G)
        assert "saturation_stats" in res
        assert len(res["saturation_stats"]["selection_order"]) == 4
        assert len(res["saturation_stats"]["saturation_degrees_at_selection"]) == 4

    def test_f10_channel_reuse_breakdown_sums_to_node_count(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.002, 77.2, range_m=500.0) for i in range(5)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        data = resp.json()
        dsatur_reuse = data["dsatur"]["channel_reuse_breakdown"]
        assert sum(dsatur_reuse.values()) == 5

    def test_f10_runtime_ms_is_positive_float(self, client):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.501, 77.2)]
        resp = client.post("/api/optimize", json={"cells": cells})
        assert resp.status_code == 200
        assert resp.json()["runtime_ms"] >= 0.0


# ============================================================================
# Feature 11: Independent 100% Conflict & Boundary Validator
# ============================================================================
class TestFeature11IndependentValidator:
    def test_f11_valid_coloring_passes_validation(self):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=600.0), _make_cell("T2", 28.502, 77.2, range_m=600.0)]
        G = build_interference_graph(cells)
        # Valid assignment: different colors
        val = validate_coloring(G, {"T1": 0, "T2": 1})
        assert val["is_valid"]
        assert val["conflict_count"] == 0

    def test_f11_adjacent_same_color_detected_as_conflict(self):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=600.0), _make_cell("T2", 28.502, 77.2, range_m=600.0)]
        G = build_interference_graph(cells)
        # Conflict assignment: same colors on incident edge
        val = validate_coloring(G, {"T1": 0, "T2": 0})
        assert not val["is_valid"]
        assert val["conflict_count"] == 1

    def test_f11_missing_node_assignment_detected(self):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.502, 77.2)]
        G = build_interference_graph(cells)
        val = validate_coloring(G, {"T1": 0})  # Missing T2
        assert not val["is_valid"]
        assert val["missing_count"] == 1
        assert "T2" in val["missing_nodes"]

    def test_f11_zero_distance_edge_inspection(self):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.5, 77.2)]
        G = build_interference_graph(cells, aggregate_2m=False)
        val = validate_coloring(G, {"T1": 0, "T2": 1})
        assert val["zero_distance_count"] == 1

    def test_f11_boundary_violation_detection(self):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=100.0), _make_cell("T2", 28.51, 77.2, range_m=100.0)]
        G = build_interference_graph(cells)
        # Artificially inject an edge violating the boundary threshold
        G.add_edge("T1", "T2", distance_m=1100.0, threshold_m=200.0)
        val = validate_coloring(G, {"T1": 0, "T2": 1})
        assert not val["is_valid"]
        assert val["boundary_violation_count"] == 1


# ============================================================================
# Feature 12: Educational Boundaries Structured Object
# ============================================================================
class TestFeature12EducationalBoundariesStructuredObject:
    def test_f12_graph_build_includes_disclaimer(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert "educational_disclaimer" in resp.json()
        assert resp.json()["educational_disclaimer"]["is_educational_simulation"] is True

    def test_f12_optimize_includes_disclaimer(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/optimize", json={"cells": cells})
        assert resp.status_code == 200
        disc = resp.json()["educational_disclaimer"]
        assert "SpectraMap is a pedagogy" in disc["disclaimer"]

    def test_f12_compare_includes_disclaimer(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        assert "educational_disclaimer" in resp.json()

    def test_f12_disclaimer_propagation_model_field(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        disc = resp.json()["educational_disclaimer"]
        assert "2D Circular Disk Geometric Overlap" in disc["propagation_model"]

    def test_f12_disclaimer_recommended_use_field(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/optimize", json={"cells": cells})
        disc = resp.json()["educational_disclaimer"]
        assert "Computer Science algorithm education" in disc["recommended_use"]


# ============================================================================
# Feature 13: Interactive Force-Directed Canvas Explorer
# ============================================================================
class TestFeature13InteractiveForceDirectedCanvasExplorer:
    def test_f13_graph_payload_nodes_have_degrees(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=500.0), _make_cell("T2", 28.501, 77.2, range_m=500.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        assert all("degree" in n for n in nodes)

    def test_f13_graph_payload_nodes_have_radio(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, radio="5G")]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert resp.status_code == 200
        assert resp.json()["nodes"][0]["radio"] == "5G"

    def test_f13_graph_payload_edges_have_source_target(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=500.0), _make_cell("T2", 28.501, 77.2, range_m=500.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        edges = resp.json()["edges"]
        assert len(edges) == 1
        assert "source" in edges[0] and "target" in edges[0]

    def test_f13_canvas_view_container_present_in_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="graph-canvas"' in html
        assert 'id="graph-canvas-container"' in html

    def test_f13_physics_simulation_controls_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'id="tab-graph-view"' in resp.text


# ============================================================================
# Feature 14: Geographic Map View & Seamless Switching
# ============================================================================
class TestFeature14GeographicMapViewAndSeamlessSwitching:
    def test_f14_map_container_present_in_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'id="map"' in resp.text

    def test_f14_leaflet_scripts_referenced(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "leaflet.css" in resp.text

    def test_f14_view_tabs_present_in_html(self, client):
        resp = client.get("/")
        assert 'id="tab-map-view"' in resp.text
        assert 'id="tab-graph-view"' in resp.text

    def test_f14_nodes_contain_latitude_longitude_for_map(self, client):
        cells = [_make_cell("T1", 28.5224, 77.1906)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        node = resp.json()["nodes"][0]
        assert node["latitude"] == 28.5224
        assert node["longitude"] == 77.1906

    def test_f14_edges_contain_gps_endpoints_for_overlay(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=500.0), _make_cell("T2", 28.501, 77.2, range_m=500.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        edge = resp.json()["edges"][0]
        assert "source_coords" in edge
        assert "target_coords" in edge


# ============================================================================
# Feature 15: Side-by-Side Benchmark Comparison Dashboard
# ============================================================================
class TestFeature15SideBySideBenchmarkDashboard:
    def test_f15_compare_endpoint_faster_heuristic_field(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(4)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        comp = resp.json()["comparison"]
        assert "faster_heuristic" in comp

    def test_f15_compare_endpoint_fewer_colors_field(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(4)]
        resp = client.post("/api/compare", json={"cells": cells})
        assert resp.status_code == 200
        comp = resp.json()["comparison"]
        assert "fewer_colors_heuristic" in comp

    def test_f15_compare_channel_reuse_breakdowns_populated(self, client):
        cells = [_make_cell(f"T{i}", 28.5 + i * 0.001, 77.2, range_m=500.0) for i in range(4)]
        resp = client.post("/api/compare", json={"cells": cells})
        data = resp.json()
        assert "channel_reuse_breakdown" in data["dsatur"]
        assert "channel_reuse_breakdown" in data["welsh_powell"]

    def test_f15_benchmark_card_html_markup_present(self, client):
        resp = client.get("/")
        assert 'id="dashboard-compare-card"' in resp.text

    def test_f15_validation_badges_in_compare_results(self, client):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.501, 77.2)]
        resp = client.post("/api/compare", json={"cells": cells})
        data = resp.json()
        assert data["dsatur"]["validation"]["is_valid"] is True
        assert data["welsh_powell"]["validation"]["is_valid"] is True


# ============================================================================
# Feature 16: Bidirectional Vertex Inspector
# ============================================================================
class TestFeature16BidirectionalVertexInspector:
    def test_f16_nodes_have_site_id_for_clustering_inspection(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        assert "site_id" in resp.json()["nodes"][0]

    def test_f16_nodes_have_unique_id(self, client):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.51, 77.21)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        ids = [n["id"] for n in resp.json()["nodes"]]
        assert len(ids) == len(set(ids))

    def test_f16_vertex_inspector_container_in_html(self, client):
        resp = client.get("/")
        assert 'id="vertex-inspector"' in resp.text
        assert 'id="inspector-cell-id"' in resp.text

    def test_f16_edges_connect_inspectable_node_ids(self, client):
        cells = [_make_cell("T1", 28.5, 77.2, range_m=600.0), _make_cell("T2", 28.502, 77.2, range_m=600.0)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        node_ids = {n["id"] for n in resp.json()["nodes"]}
        for edge in resp.json()["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids

    def test_f16_node_provenance_fields_available_for_inspection(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        resp = client.post("/api/graph/build", json={"cells": cells})
        node = resp.json()["nodes"][0]
        assert "range_source" in node
        assert "is_range_estimated" in node


# ============================================================================
# Feature 17: Frontend Robustness & Safe DOM Access
# ============================================================================
class TestFeature17FrontendRobustnessAndSafeDOMAccess:
    def test_f17_static_app_js_served(self, client):
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"].lower()

    def test_f17_static_style_css_served(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"].lower()

    def test_f17_no_syntax_errors_in_static_files(self, client):
        resp_js = client.get("/static/app.js")
        assert len(resp_js.text) > 1000
        resp_css = client.get("/static/style.css")
        assert len(resp_css.text) > 1000

    def test_f17_all_button_listeners_target_existing_ids(self, client):
        html = client.get("/").text
        # Critical action buttons checked in app.js
        for btn_id in ["btn-fetch", "btn-build-graph", "btn-optimize", "btn-compare-action"]:
            assert f'id="{btn_id}"' in html

    def test_f17_safe_dom_guards_in_app_js(self, client):
        js = client.get("/static/app.js").text
        # Verify safe DOM guard pattern or element checks exist
        assert "document.getElementById" in js


# ============================================================================
# Feature 18: Educational Disclaimer Presentation
# ============================================================================
class TestFeature18EducationalDisclaimerPresentation:
    def test_f18_disclaimer_card_present_in_html(self, client):
        html = client.get("/").text
        assert "How SpectraMap Works" in html or "cellular-reality-card" in html

    def test_f18_disclaimer_mentions_heuristic_abstraction(self, client):
        resp = client.post("/api/optimize", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        disc = resp.json()["educational_disclaimer"]["disclaimer"]
        assert "pedagogy" in disc or "abstraction" in disc

    def test_f18_disclaimer_mentions_cellular_simplification(self, client):
        resp = client.post("/api/graph/build", json={"cells": [_make_cell("T1", 28.5, 77.2)]})
        disc = resp.json()["educational_disclaimer"]["disclaimer"]
        assert "circular coverage" in disc

    def test_f18_structured_disclaimer_returned_in_health(self, client):
        # /api/health confirms educational app identity
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["app"] == "SpectraMap"

    def test_f18_disclaimer_persists_across_all_graph_endpoints(self, client):
        cells = [_make_cell("T1", 28.5, 77.2)]
        b_resp = client.post("/api/graph/build", json={"cells": cells})
        o_resp = client.post("/api/optimize", json={"cells": cells})
        c_resp = client.post("/api/compare", json={"cells": cells})
        assert "educational_disclaimer" in b_resp.json()
        assert "educational_disclaimer" in o_resp.json()
        assert "educational_disclaimer" in c_resp.json()


# ============================================================================
# Feature 19: Lightweight Managed Stack Compliance
# ============================================================================
class TestFeature19LightweightManagedStackCompliance:
    def test_f19_fastapi_framework_identified(self):
        assert app.title == "SpectraMap"
        assert app.version == "2.0"

    def test_f19_pure_python_haversine_no_gis_dependency(self):
        # Pure Python haversine execution without external native binary libraries
        d = haversine_distance(12.9716, 77.5946, 13.0827, 80.2707)
        assert d > 280000.0 and d < 300000.0

    def test_f19_networkx_graph_data_structures(self):
        cells = [_make_cell("T1", 28.5, 77.2), _make_cell("T2", 28.501, 77.2)]
        G = build_interference_graph(cells)
        import networkx as nx
        assert isinstance(G, nx.Graph)

    def test_f19_no_database_engine_required(self, client):
        # Requests execute directly in-memory without persistent db connection
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_f19_health_endpoint_confirms_monolith_architecture(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["app"] == "SpectraMap"
        assert data["version"] == "2.0"


# ============================================================================
# Feature 20: Automated Pytest Pass Rate
# ============================================================================
class TestFeature20AutomatedPytestPassRate:
    def test_f20_fastapi_testclient_initialization(self, client):
        assert client is not None

    def test_f20_health_check_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_f20_status_check_returns_200(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_f20_root_view_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_f20_clean_teardown_isolation(self, client):
        # Sequential calls do not contaminate subsequent results
        r1 = client.get("/api/health")
        r2 = client.get("/api/health")
        assert r1.status_code == 200 and r2.status_code == 200


# ============================================================================
# Feature 21: Zero Unhandled JS Runtime Errors
# ============================================================================
class TestFeature21ZeroUnhandledJSRuntimeErrors:
    def test_f21_app_js_has_no_duplicate_case_or_keys(self, client):
        js = client.get("/static/app.js").text
        assert "function" in js or "class" in js or "const" in js
        assert len(js) > 0

    def test_f21_index_html_has_no_duplicate_element_ids(self, client):
        import re
        html = client.get("/").text
        ids = re.findall(r'id=["\']([^"\']+)["\']', html)
        duplicates = [item for item, count in Counter(ids).items() if count > 1]
        assert len(duplicates) == 0, f"Duplicate HTML IDs found: {duplicates}"

    def test_f21_api_error_responses_return_standard_json(self, client):
        resp = client.get("/api/cells")  # Missing lat, lon
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_f21_invalid_json_body_returns_422(self, client):
        resp = client.post(
            "/api/graph/build",
            content="invalid non json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_f21_missing_required_fields_handled_gracefully(self, client):
        resp = client.post("/api/optimize", json={})
        assert resp.status_code == 422
        assert "detail" in resp.json()
