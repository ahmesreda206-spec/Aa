from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class BootstrapRequest(LoginRequest):
    bootstrap_token: str = Field(default="", max_length=256)

    @field_validator("password")
    @classmethod
    def require_strong_initial_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Initial administrator password must be at least 12 characters")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str


class BootstrapStatus(BaseModel):
    required: bool
    token_required: bool


class DeviceCreate(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    zone: str = Field(min_length=2, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    zone: str
    latitude: float
    longitude: float
    active: bool
    created_at: datetime
    last_seen: datetime | None
    online: bool = False


class DeviceTokenResponse(BaseModel):
    device: DeviceOut
    token: str


class TelemetryCreate(StrictModel):
    device_id: str = Field(min_length=5, max_length=40, pattern=r"^qf-[a-z0-9-]+$")
    recorded_at: datetime | None = None
    temperature_c: float = Field(ge=-40, le=85)
    humidity_pct: float = Field(ge=0, le=100)
    soil_moisture_pct: float = Field(ge=0, le=100)
    water_level_pct: float = Field(ge=0, le=100)
    battery_v: float = Field(ge=0, le=15)
    rssi_dbm: int = Field(ge=-130, le=0)

    @field_validator("recorded_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        now = datetime.now(timezone.utc)
        if value > now + timedelta(minutes=5) or value < now - timedelta(hours=24):
            raise ValueError("recorded_at must be within the last 24 hours")
        return value


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    recorded_at: datetime
    temperature_c: float
    humidity_pct: float
    soil_moisture_pct: float
    water_level_pct: float
    battery_v: float
    rssi_dbm: int


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatResponse(BaseModel):
    message: ChatMessageOut
    model: str
    adapter: str


class AIStatus(BaseModel):
    enabled: bool
    loaded: bool
    model: str
    adapter: str
    detail: str


class AlertOut(BaseModel):
    id: str
    device_id: str
    device_name: str
    severity: Literal["warning", "critical"]
    message: str
    created_at: datetime


class DashboardMetrics(BaseModel):
    total_devices: int
    online_devices: int
    active_alerts: int
    average_temperature_c: float | None
    average_soil_moisture_pct: float | None
    average_water_level_pct: float | None


class DashboardSummary(BaseModel):
    metrics: DashboardMetrics
    devices: list[DeviceOut]
    alerts: list[AlertOut]
    readings: list[TelemetryOut]
    generated_at: datetime
