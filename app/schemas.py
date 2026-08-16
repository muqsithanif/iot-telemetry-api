"""Request and response shapes.

Validation lives here rather than in the routers so the rules are visible in
one place and testable without spinning up the app.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Metrics the API accepts. Keeping this closed stops typos ("temperture")
# from silently creating a new series nobody queries.
ALLOWED_METRICS = {"temperature", "humidity", "weight", "pressure", "voltage", "current"}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="reader")

    @field_validator("role")
    @classmethod
    def role_must_be_known(cls, v: str) -> str:
        if v not in {"admin", "reader"}:
            raise ValueError("role must be 'admin' or 'reader'")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str


class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    location: str | None = Field(default=None, max_length=128)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str | None
    created_at: datetime


class DeviceCreated(DeviceOut):
    # Returned exactly once, at creation. Only its hash is stored.
    api_key: str


class ReadingIn(BaseModel):
    metric: str
    value: float
    unit: str | None = Field(default=None, max_length=16)
    recorded_at: datetime | None = None

    @field_validator("metric")
    @classmethod
    def metric_must_be_allowed(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ALLOWED_METRICS:
            allowed = ", ".join(sorted(ALLOWED_METRICS))
            raise ValueError(f"metric must be one of: {allowed}")
        return v


class ReadingBatch(BaseModel):
    """Devices on flaky links buffer locally, so ingestion accepts batches."""

    readings: list[ReadingIn] = Field(min_length=1, max_length=500)


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    metric: str
    value: float
    unit: str | None
    recorded_at: datetime
    received_at: datetime


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[str] = []


class MetricSummary(BaseModel):
    device_id: int
    metric: str
    count: int
    minimum: float
    maximum: float
    average: float
    first_recorded_at: datetime
    last_recorded_at: datetime
