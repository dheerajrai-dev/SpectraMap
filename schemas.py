"""
schemas.py — Pydantic models for API request and response validation

Defines the expected shape of incoming JSON requests and response models for:
- Coordinates
- Tower fetching and Cell records
- Physical Site entities and Accounting metadata
- Graph construction
- Frequency optimization & comparison
"""

from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class CenterCoordinates(BaseModel):
    """Geographic center point (latitude and longitude)."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in degrees (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in degrees (-180 to 180)")

    @model_validator(mode="before")
    @classmethod
    def pre_populate_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "latitude" not in data and "lat" in data:
                data["latitude"] = data["lat"]
            if "longitude" not in data and "lon" in data:
                data["longitude"] = data["lon"]
        return data


class CellRecord(BaseModel):
    """
    Normalized cell transceiver record representing an individual radiating sector.
    Each cell transceiver corresponds to a vertex in the spatial interference graph.
    """
    tower_id: str = Field(default="", description="Globally unique transceiver identifier (e.g. '4G_404_11_51005_123')")
    cell_id: int = Field(default=0, description="Cell identifier from cellular network / OpenCellID")
    radio: str = Field(default="4G", description="Radio technology, strictly '4G' or '5G'")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    range_m: float = Field(default=800.0, ge=50.0, le=10000.0, description="Modeled coverage radius in metres")
    is_range_estimated: bool = Field(default=False, description="True if range was estimated via fallback or clamped")
    range_source: str = Field(default="reported", description="Source of range: 'reported', 'fallback_default', 'fallback_clamped'")
    site_id: str = Field(default="", description="Physical mast/site identifier grouping co-located sectors")
    is_co_located: bool = Field(default=False, description="True if multiple transceivers share this physical site")

    # Backward-compatible and contextual inspection fields:
    id: str | None = Field(default=None, description="Alias for tower_id")
    lat: float | None = Field(default=None, description="Alias for latitude")
    lon: float | None = Field(default=None, description="Alias for longitude")
    mcc: int | None = Field(default=None, description="Mobile Country Code")
    mnc: int | None = Field(default=None, description="Mobile Network Code")
    area: int | None = Field(default=None, description="Location Area Code (LAC) or Tracking Area Code (TAC)")
    source: str = Field(default="OpenCellID", description="Data provider source")
    retrieved_at: str | None = Field(default=None, description="ISO-8601 timestamp of data ingestion")
    range_is_fallback: bool = Field(default=False, description="Legacy alias for is_range_estimated")
    fallback_reason: str | None = Field(default=None, description="Reason fallback radius was applied")
    raw_range: Any = Field(default=None, description="Raw range from data source before clamping/fallback")
    warnings: list[str] = Field(default_factory=list, description="Data quality warnings for this transceiver")

    @field_validator("radio")
    @classmethod
    def validate_radio_technology(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean in ("4G", "LTE", "4G LTE", "4G-LTE", "4GLTE", "EUTRAN", "E-UTRAN", "LTE-M"):
            return "4G"
        if clean in ("5G", "NR", "5G NR", "5G-NR", "5GNR"):
            return "5G"
        raise ValueError(f"Invalid radio technology '{v}'. Only '4G' and '5G' are supported.")

    @model_validator(mode="before")
    @classmethod
    def pre_populate_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "latitude" not in data and "lat" in data:
                data["latitude"] = data["lat"]
            if "longitude" not in data and "lon" in data:
                data["longitude"] = data["lon"]
            if ("tower_id" not in data or not data["tower_id"]) and "id" in data:
                data["tower_id"] = str(data["id"])
            if "range_is_fallback" in data and "is_range_estimated" not in data:
                data["is_range_estimated"] = bool(data["range_is_fallback"])
            raw_rng = data.get("range_m") if "range_m" in data else (data.get("range") if "range" in data else data.get("coverage_radius_m"))
            if raw_rng is not None:
                try:
                    rng_val = float(raw_rng)
                    if rng_val <= 0:
                        data["range_m"] = 800.0
                        data["is_range_estimated"] = True
                    elif rng_val < 50.0:
                        data["range_m"] = 50.0
                        data["is_range_estimated"] = True
                    elif rng_val > 10000.0:
                        data["range_m"] = 10000.0
                        data["is_range_estimated"] = True
                    else:
                        data["range_m"] = rng_val
                except (ValueError, TypeError):
                    data["range_m"] = 800.0
                    data["is_range_estimated"] = True
        return data

    @model_validator(mode="after")
    def post_populate_aliases(self) -> "CellRecord":
        if self.id is None:
            self.id = self.tower_id
        if not self.tower_id and self.id:
            self.tower_id = self.id
        if self.lat is None:
            self.lat = self.latitude
        if self.lon is None:
            self.lon = self.longitude
        if not self.site_id:
            self.site_id = f"SITE_{self.latitude:.5f}_{self.longitude:.5f}"
        if self.is_range_estimated and not self.range_is_fallback:
            self.range_is_fallback = True
        elif self.range_is_fallback and not self.is_range_estimated:
            self.is_range_estimated = True
        return self


class SiteEntity(BaseModel):
    """
    Physical site or antenna mast hosting one or more co-located transceivers (sectors).
    """
    site_id: str = Field(..., description="Deterministic site identifier (e.g. 'SITE_28.52000_77.19000')")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude of the physical mast")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude of the physical mast")
    sector_count: int = Field(..., ge=1, description="Number of transceivers hosted on this physical site")
    sectors: list[str] = Field(..., description="List of tower_id identifiers hosted on this site")
    radios: list[str] = Field(..., description="Distinct radio technologies present on this site (e.g. ['4G', '5G'])")

    @model_validator(mode="after")
    def verify_sector_count(self) -> "SiteEntity":
        if self.sector_count != len(self.sectors):
            raise ValueError(f"sector_count ({self.sector_count}) must match len(sectors) ({len(self.sectors)})")
        return self


class AccountingMetadata(BaseModel):
    """
    Accounting metadata detailing dataset reduction across the filtering and sampling pipeline.

    Guarantees the mathematical invariants:
      available_count >= eligible_count >= selected_count >= 0
      excluded_radio_count = available_count - eligible_count
      excluded_limit_count = eligible_count - selected_count
      excluded_count = available_count - selected_count = excluded_radio_count + excluded_limit_count
    """
    available_count: int = Field(..., ge=0, description="Total valid cell records in geographic search area")
    eligible_count: int = Field(..., ge=0, description="Records matching active 4G/5G radio filter")
    selected_count: int = Field(..., ge=0, description="Records selected after spatial dispersion sampling and limit truncation")
    excluded_count: int = Field(..., ge=0, description="Total records excluded (available - selected)")
    excluded_radio_count: int = Field(..., ge=0, description="Records excluded by 4G/5G radio technology filter")
    excluded_limit_count: int = Field(..., ge=0, description="Eligible records excluded by maximum record limit")

    @model_validator(mode="after")
    def verify_accounting_invariants(self) -> "AccountingMetadata":
        if self.available_count < self.eligible_count:
            raise ValueError(
                f"available_count ({self.available_count}) cannot be less than eligible_count ({self.eligible_count})"
            )
        if self.eligible_count < self.selected_count:
            raise ValueError(
                f"eligible_count ({self.eligible_count}) cannot be less than selected_count ({self.selected_count})"
            )
        if self.excluded_radio_count != self.available_count - self.eligible_count:
            raise ValueError(
                f"excluded_radio_count ({self.excluded_radio_count}) must equal available_count - eligible_count "
                f"({self.available_count - self.eligible_count})"
            )
        if self.excluded_limit_count != self.eligible_count - self.selected_count:
            raise ValueError(
                f"excluded_limit_count ({self.excluded_limit_count}) must equal eligible_count - selected_count "
                f"({self.eligible_count - self.selected_count})"
            )
        if self.excluded_count != self.available_count - self.selected_count:
            raise ValueError(
                f"excluded_count ({self.excluded_count}) must equal available_count - selected_count "
                f"({self.available_count - self.selected_count})"
            )
        return self


class TowersResponse(BaseModel):
    """
    Response envelope for GET /api/towers and GET /api/cells endpoints.
    Combines new M1 data structures with 100% backward compatibility for existing tests.
    """
    source: str = Field(default="OpenCellID", description="Dataset source")
    count: int = Field(..., description="Number of selected cell records returned")
    accounting: AccountingMetadata = Field(..., description="Pipeline reduction accounting metadata")
    towers: list[CellRecord] = Field(..., description="List of selected cell transceiver records")
    cells: list[CellRecord] = Field(..., description="Alias for towers for backward compatibility")
    sites: list[SiteEntity] = Field(..., description="List of physical site entities")
    tech_distribution: dict[str, int] = Field(..., description="Distribution of 4G vs 5G transceivers in selection")
    center: dict[str, float] | None = Field(default=None, description="Geographic query center coordinate")
    radius_m: float | None = Field(default=None, description="Search radius in metres")
    warnings: list[str] = Field(default_factory=list, description="Dataset quality warnings")
    attribution: str = Field(default="Cell tower data from OpenCellID, licensed under CC BY-SA 4.0.")
    cached: bool = Field(default=False, description="True if results were served from local query cache")


class GraphBuildRequest(BaseModel):
    """Request payload for POST /api/graph/build."""
    center: CenterCoordinates | None = Field(default=None, description="Center coordinate")
    radius_m: float = Field(default=1500.0, gt=0, le=10000.0, description="Search radius in metres")
    cells: list[CellRecord] | None = Field(default=None, description="Cell transceiver records")
    towers: list[CellRecord] | None = Field(default=None, description="Alias for cells")
    sites: list[SiteEntity | dict[str, Any]] | None = Field(default=None, description="Physical site entities")
    tower_ids: list[str] | None = Field(default=None, description="Optional subset of tower IDs to include")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")
    aggregate_2m: bool = Field(default=False, description="If True, treat towers within 2 metre range as 1 tower")

    @model_validator(mode="after")
    def harmonize_cells_and_towers(self) -> "GraphBuildRequest":
        if self.cells is None and self.towers is not None:
            self.cells = self.towers
        elif self.towers is None and self.cells is not None:
            self.towers = self.cells
        return self


class OptimizeRequest(BaseModel):
    """Request payload for POST /api/optimize."""
    center: CenterCoordinates | None = Field(default=None, description="Geographic center point")
    radius_m: float = Field(default=1000.0, gt=0, le=5000.0, description="Search radius in metres (max 5000m)")
    cells: list[CellRecord] | None = Field(default=None, description="Optional cell records list (for demo or pre-filtered grid)")
    towers: list[CellRecord] | None = Field(default=None, description="Alias for cells")
    sites: list[SiteEntity | dict[str, Any]] | None = Field(default=None, description="Physical site entities")
    algorithm: str = Field(default="both", description="Coloring algorithm: dsatur, welsh_powell, both, exact")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")
    aggregate_2m: bool = Field(default=False, description="If True, treat towers within 2 metre range as 1 tower")

    @model_validator(mode="after")
    def validate_center_and_harmonize(self) -> "OptimizeRequest":
        if self.cells is None and self.towers is not None:
            self.cells = self.towers
        elif self.towers is None and self.cells is not None:
            self.towers = self.cells
        if self.center is None and (not self.cells or len(self.cells) == 0):
            raise ValueError("Field 'center' is required when cells or towers are not provided.")
        return self


class CompareRequest(BaseModel):
    """Request payload for POST /api/compare."""
    center: CenterCoordinates | None = Field(default=None, description="Geographic center point")
    radius_m: float = Field(default=1000.0, gt=0, le=5000.0, description="Search radius in metres (max 5000m)")
    cells: list[CellRecord] | None = Field(default=None, description="Optional cell records list (for demo or pre-filtered grid)")
    towers: list[CellRecord] | None = Field(default=None, description="Alias for cells")
    sites: list[SiteEntity | dict[str, Any]] | None = Field(default=None, description="Physical site entities")
    radius_override_m: float | None = Field(default=None, gt=0, le=20000.0, description="Optional uniform coverage radius assumption in metres")
    aggregate_2m: bool = Field(default=False, description="If True, treat towers within 2 metre range as 1 tower")

    @model_validator(mode="after")
    def validate_center_and_harmonize(self) -> "CompareRequest":
        if self.cells is None and self.towers is not None:
            self.cells = self.towers
        elif self.towers is None and self.cells is not None:
            self.towers = self.cells
        if self.center is None and (not self.cells or len(self.cells) == 0):
            raise ValueError("Field 'center' is required when cells or towers are not provided.")
        return self


class GraphMetrics(BaseModel):
    """Structural topological and spatial metrics for the interference graph."""
    node_count: int = Field(..., ge=0, description="Total number of vertices (cell transceivers)")
    vertex_count: int = Field(..., ge=0, description="Alias for node_count")
    edge_count: int = Field(..., ge=0, description="Total number of interference conflict edges")
    density: float = Field(..., ge=0.0, le=1.0, description="Graph edge density 2|E| / (|V|(|V|-1))")
    connected_components: int = Field(default=0, ge=0, description="Number of connected components")
    max_degree: int = Field(default=0, ge=0, description="Maximum vertex degree Delta(G)")
    delta_g: int = Field(default=0, ge=0, description="Maximum vertex degree Delta(G)")
    avg_degree: float = Field(default=0.0, ge=0.0, description="Average vertex degree")
    clique_lower_bound: int = Field(default=0, ge=0, description="Lower bound on chromatic number omega(G)")
    brooks_upper_bound: int = Field(default=0, ge=0, description="Brooks' theorem upper bound Delta(G) + 1")
    degree_distribution: dict[int, int] = Field(default_factory=dict, description="Frequency count per vertex degree")
    candidate_pairs_examined: int = Field(default=0, ge=0, description="Total candidate vertex pairs evaluated")
    edges_accepted: int = Field(default=0, ge=0, description="Candidate pairs satisfying overlap criterion")
    edges_rejected: int = Field(default=0, ge=0, description="Candidate pairs failing overlap criterion")
    co_located_pairs_count: int = Field(default=0, ge=0, description="Pairs sharing identical physical coordinates")
    unique_coordinates_count: int = Field(default=0, ge=0, description="Distinct geographic coordinate points")
    coordinate_diversity: float = Field(default=1.0, ge=0.0, le=1.0, description="Unique coordinate locations over vertex count |unique_coords| / |V|")
    min_radius_m: float = Field(default=0.0, ge=0.0, description="Minimum effective coverage radius")
    median_radius_m: float = Field(default=0.0, ge=0.0, description="Median effective coverage radius")
    max_radius_m: float = Field(default=0.0, ge=0.0, description="Maximum effective coverage radius")
    min_distance_m: float = Field(default=0.0, ge=0.0, description="Minimum pairwise geodesic distance")
    median_distance_m: float = Field(default=0.0, ge=0.0, description="Median pairwise geodesic distance")
    max_distance_m: float = Field(default=0.0, ge=0.0, description="Maximum pairwise geodesic distance")
    technology_distribution: dict[str, int] = Field(
        default_factory=lambda: {"4G": 0, "5G": 0},
        description="Distribution of 4G vs 5G transceivers in the interference graph",
    )
    tech_distribution: dict[str, int] = Field(
        default_factory=lambda: {"4G": 0, "5G": 0},
        description="Alias for technology_distribution",
    )
    sample_accepted_edges: list[dict[str, Any]] = Field(default_factory=list, description="Sample accepted edge justifications")
    sample_rejected_pairs: list[dict[str, Any]] = Field(default_factory=list, description="Sample rejected pair justifications")
    data_unsuitable: bool = Field(default=False, description="Flagged true if all nodes are co-located at single point")
    data_unsuitable_reason: str | None = Field(default=None, description="Detailed explanation if dataset is unsuitable")


class GraphDiagnostics(GraphMetrics):
    """Full diagnostic payload for the interference graph."""
    pass


class ValidationResult(BaseModel):
    """Independent coloring validation result."""
    is_valid: bool = Field(..., description="True if coloring has zero conflicts and covers all nodes")
    conflict_count: int = Field(default=0, ge=0, description="Number of adjacent conflicts detected")
    conflicts: list[Any] = Field(default_factory=list, description="List of adjacent conflicting vertex pairs")
    conflicting_edges: list[dict[str, Any]] = Field(default_factory=list, description="Detailed conflict edges")
    missing_count: int = Field(default=0, ge=0, description="Count of uncolored vertices")
    missing_nodes: list[Any] = Field(default_factory=list, description="List of uncolored node identifiers")
    color_count: int = Field(default=0, ge=0, description="Number of distinct valid colors assigned")
    chi_heuristic: int = Field(default=0, ge=0, description="Chromatic number found by heuristic")
    edges_inspected: int = Field(default=0, ge=0, description="Total edges inspected by validator")
    zero_distance_edges: list[dict[str, Any]] = Field(default_factory=list, description="Zero-distance co-located edge pairs")
    zero_distance_violations: list[dict[str, Any]] = Field(default_factory=list, description="Alias for zero_distance_edges")
    zero_distance_count: int = Field(default=0, ge=0, description="Count of zero-distance edges")
    boundary_violations: list[dict[str, Any]] = Field(default_factory=list, description="Edges exceeding threshold distance")
    boundary_violation_count: int = Field(default=0, ge=0, description="Count of boundary violations")
    details: str | None = Field(default=None, description="Human-readable validation summary")


class EducationalDisclaimer(BaseModel):
    """Educational boundaries structured object for frequency allocation model."""
    is_educational_simulation: bool = Field(
        default=True,
        description="True indicates this is an educational graph theory demonstration, not an operational RF tool",
    )
    propagation_model: str = Field(
        default="2D Circular Disk Geometric Overlap (distance <= r_u + r_v)",
        description="The mathematical spatial model used to generate proxy interference edges",
    )
    disclaimer: str = Field(
        default="SpectraMap is a pedagogy and algorithmic comparison platform for graph vertex coloring. It models interference as simplified circular coverage overlap and does not account for 3D terrain, building penetration, antenna azimuth/tilt, or ITU propagation standards.",
        description="Notice on physical and operational boundaries of the graph model",
    )
    recommended_use: str = Field(
        default="Computer Science algorithm education, discrete mathematics demonstrations, and graph coloring heuristic comparisons.",
        description="Recommended context for using this software",
    )


EDUCATIONAL_DISCLAIMER_DEFAULT: dict[str, Any] = EducationalDisclaimer().model_dump()


class SolverDiagnostics(BaseModel):
    """Algorithmic solver diagnostic measurements."""
    ordering_sequence: list[str] = Field(default_factory=list, description="Vertex ordering sequence")
    degree_sequence: list[int] = Field(default_factory=list, description="Degree values for ordering sequence")
    max_degree: int = Field(default=0, description="Max vertex degree")
    min_degree: int = Field(default=0, description="Min vertex degree")
    avg_degree: float = Field(default=0.0, description="Average vertex degree")
    passes_count: int = Field(default=0, description="Number of sequential passes")
    selection_order: list[str] = Field(default_factory=list, description="DSatur selection sequence")
    saturation_degrees_at_selection: list[int] = Field(default_factory=list, description="Saturation degrees recorded at vertex selection time")
    max_saturation_degree: int = Field(default=0, description="Max saturation degree observed")
    avg_saturation_degree: float = Field(default=0.0, description="Average saturation degree at selection")
    tie_break_count: int = Field(default=0, description="Number of saturation degree tie-breaks encountered")


class SolverResult(BaseModel):
    """Algorithm coloring solution result."""
    algorithm: str = Field(..., description="Solver algorithm name")
    coloring: dict[str, int] = Field(default_factory=dict, description="Vertex-to-channel assignment mapping")
    color_count: int = Field(default=0, ge=0, description="Total colors/channels utilized")
    chi_heuristic: int | None = Field(default=None, description="Chromatic number found by solver")
    runtime_ms: float = Field(default=0.0, ge=0.0, description="Execution time in milliseconds")
    validation: ValidationResult = Field(..., description="Independent validation report")
    status: str | None = Field(default=None, description="Solver termination status")
    proven_optimal: bool | None = Field(default=None, description="True if proven chromatic number")
    lower_bound: int | None = Field(default=None, description="Lower bound")
    upper_bound: int | None = Field(default=None, description="Upper bound")
    message: str | None = Field(default=None, description="Solver diagnostic message")
    channel_reuse_breakdown: dict[str, int] = Field(default_factory=dict, description="Frequency channel reuse distribution")
    degree_ordering_stats: dict[str, Any] | None = Field(default=None, description="Welsh-Powell degree ordering statistics")
    saturation_stats: dict[str, Any] | None = Field(default=None, description="DSatur dynamic saturation statistics")
    solver_diagnostics: dict[str, Any] = Field(default_factory=dict, description="Solver algorithmic diagnostics")

    @model_validator(mode="after")
    def harmonize_chi_heuristic(self) -> "SolverResult":
        if self.chi_heuristic is None:
            self.chi_heuristic = self.color_count
        return self


class GraphBuildResponse(BaseModel):
    """Response model for POST /api/graph/build."""
    nodes: list[dict[str, Any]] = Field(..., description="Graph vertices with spatial attributes")
    edges: list[dict[str, Any]] = Field(..., description="Interference edges")
    metrics: GraphMetrics = Field(..., description="Graph structural and spatial metrics")
    diagnostics: dict[str, Any] = Field(..., description="Topological diagnostics")
    build_runtime_ms: float = Field(..., ge=0.0, description="Graph construction time in ms")
    warnings: list[str] = Field(default_factory=list, description="Data quality warnings")
    assumptions: list[str] = Field(default_factory=list, description="Model physical assumptions")
    educational_disclaimer: EducationalDisclaimer = Field(default_factory=EducationalDisclaimer, description="Pedagogical boundary notice")


class OptimizeResponse(BaseModel):
    """Response model for POST /api/optimize."""
    result_id: str = Field(..., description="Unique result identifier")
    center: dict[str, float] | None = Field(default=None, description="Center coordinate")
    radius_m: float = Field(..., description="Search radius in metres")
    cached: bool = Field(default=False, description="Cached query flag")
    warnings: list[str] = Field(default_factory=list, description="Data quality warnings")
    attribution: str = Field(default="Cell tower data from OpenCellID, licensed under CC BY-SA 4.0.")
    graph_build_runtime_ms: float = Field(default=0.0, description="Build runtime in ms")
    algorithm: str = Field(..., description="Algorithm requested")
    assignments: dict[str, int] = Field(..., description="Optimal frequency channel assignments")
    colors_used: int = Field(default=0, description="Colors used by selected best algorithm")
    chi_heuristic: int = Field(default=0, description="Chromatic number found by selected best algorithm")
    runtime_ms: float = Field(default=0.0, description="Runtime of selected algorithm in ms")
    metrics: GraphMetrics = Field(..., description="Graph structural metrics including technology distribution")
    diagnostics: dict[str, Any] = Field(..., description="Diagnostics payload")
    best_algorithm: str = Field(..., description="Selected optimal algorithm")
    solver_diagnostics: dict[str, Any] = Field(default_factory=dict, description="Diagnostics from selected solver")
    dsatur: SolverResult | None = Field(default=None, description="DSatur solver result")
    welsh_powell: SolverResult | None = Field(default=None, description="Welsh-Powell solver result")
    exact: SolverResult | None = Field(default=None, description="Exact DSatur BnB result")
    validation: ValidationResult = Field(..., description="Coloring validation result")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Interference edges for visual overlay")
    educational_disclaimer: EducationalDisclaimer = Field(default_factory=EducationalDisclaimer, description="Pedagogical boundary notice")


class CompareResponse(BaseModel):
    """Response model for POST /api/compare."""
    metrics: GraphMetrics = Field(..., description="Graph structural metrics")
    diagnostics: dict[str, Any] = Field(..., description="Diagnostics payload")
    dsatur: SolverResult = Field(..., description="DSatur solver result")
    welsh_powell: SolverResult = Field(..., description="Welsh-Powell solver result")
    exact: SolverResult | None = Field(default=None, description="Exact solver result")
    agreement: bool = Field(default=True, description="True if both DSatur and Welsh-Powell achieved identical color count")
    comparison: dict[str, Any] = Field(..., description="Comparative benchmark metrics")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Interference edges")
    warnings: list[str] = Field(default_factory=list, description="Warnings list")
    educational_disclaimer: EducationalDisclaimer = Field(default_factory=EducationalDisclaimer, description="Pedagogical boundary notice")
