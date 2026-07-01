"""Request/response shapes. Pydantic validates ingest payloads for free."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MetricIn(BaseModel):
    # The wire contract uses camelCase `deviceId` (per the brief); internally we
    # use snake_case. alias + populate_by_name lets both work.
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(alias="deviceId", min_length=1)
    power: float
    temperature: float
    # Optional: devices without a reliable clock can omit it; we stamp server time.
    timestamp: datetime | None = None


class DeviceIn(BaseModel):
    """Control-plane: register/update a device's metadata (separate from telemetry)."""
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(alias="deviceId", min_length=1)
    label: str | None = None
    location: str | None = None
    power_limit: float | None = Field(default=None, alias="powerLimit")
    temp_limit: float | None = Field(default=None, alias="tempLimit")


class Reading(BaseModel):
    """A single point as returned by the read endpoints."""
    power: float
    temperature: float
    timestamp: datetime
