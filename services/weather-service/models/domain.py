"""Pydantic models for weather-service domain objects and API responses."""

from pydantic import BaseModel, Field


class RunwayImpact(BaseModel):
    category: str = Field(description="Impact category")
    arrival_rate: int
    departure_rate: int
    active_runway: str
    ils_required: bool


class WeatherCurrent(BaseModel):
    id: str
    sim_time: str
    category: str
    visibility_m: int
    wind_direction: int
    wind_speed_kt: int
    wind_gust_kt: int
    ceiling_ft: int | None
    temperature_c: float
    dew_point_c: float
    qnh_hpa: int
    phenomena: list[str]
    runway_impact: RunwayImpact
    metar_raw: str


class WeatherHistoryEntry(BaseModel):
    category: str
    from_time: str = Field(alias="from")
    to_time: str = Field(alias="to")
    duration_minutes: int

    model_config = {"populate_by_name": True}


class WeatherHistory(BaseModel):
    from_time: str = Field(alias="from")
    to_time: str = Field(alias="to")
    states: list[WeatherHistoryEntry]

    model_config = {"populate_by_name": True}


class WeatherImpact(BaseModel):
    category: str
    severity: str
    summary: str
    arrival_rate: int
    departure_rate: int
    crosswind_kt: int
    crosswind_limit_kt: int
    operations_normal: bool
