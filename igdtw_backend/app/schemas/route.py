from pydantic import BaseModel, Field


class Location(BaseModel):
    lat: float = Field(
        ...,
        json_schema_extra={"example": 28.6139},
        description="Latitude coordinate",
    )
    lon: float = Field(
        ...,
        json_schema_extra={"example": 77.2090},
        description="Longitude coordinate",
    )


class RouteRequest(BaseModel):
    origin: Location
    destination: Location

    alpha: float = Field(
        default=1.20,
        ge=1.0,
        le=2.0,
        description="Maximum allowed detour multiplier",
    )

    unknown_policy: str = Field(
        default="neutral",
        # show_gaps is a deprecated alias for neutral, kept so that a front end
        # deployed before this change keeps working instead of getting a 422
        # during the window where the two halves are on different versions.
        pattern="^(avoid|neutral|assume_typical|show_gaps)$",
        description=(
            "Stance toward streets with no lighting evidence. "
            "neutral: distance only, no assumption. "
            "assume_typical: scored as darkly as the average observed street. "
            "avoid: heavily penalised, taken only when unavoidable."
        ),
    )

    hour: int = Field(
        default=12,
        ge=0,
        le=23,
        description="Hour of day in local time (0-23)",
    )


class PathMetrics(BaseModel):
    total_length_m: float
    unlit_length_m: float
    unknown_length_m: float
    dark_fraction: float
    coverage_ratio: float


class RouteSegment(BaseModel):
    """
    One physical street along the route, with its own geometry and evidence.
    """

    road_id: int | None = None
    length_m: float

    # NULL means no evidence is available.
    dark_fraction: float | None = None

    observation_state: str
    coordinates: list[tuple[float, float]]


class RouteOption(BaseModel):
    nodes: list[tuple[float, float]]
    segments: list[RouteSegment] = []
    metrics: PathMetrics


class EvidenceSummary(BaseModel):
    unlit_meters_avoided: float
    extra_distance_m: float
    safety_gain_percent: float


class RouteResponse(BaseModel):
    status: str
    detour_multiplier_cap: float

    # Time-of-day context used by the routing decision.
    hour: int
    time_weighting_factor: float

    baseline_route: RouteOption
    chiraag_route: RouteOption
    evidence_summary: EvidenceSummary