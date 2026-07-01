"""Unit: payload validation. No infra needed."""
import pytest
from pydantic import ValidationError

from app.models import DeviceIn, MetricIn


def test_camelcase_alias_and_optional_timestamp():
    m = MetricIn(**{"deviceId": "rack-a1", "power": 612, "temperature": 77})
    assert m.device_id == "rack-a1"
    assert m.timestamp is None  # optional; server will stamp it


def test_timestamp_is_parsed():
    m = MetricIn(deviceId="d", power=1, temperature=2, timestamp="2026-06-30T20:00:00Z")
    assert m.timestamp.year == 2026 and m.timestamp.tzinfo is not None


def test_populate_by_name_also_works():
    m = MetricIn(device_id="d", power=1, temperature=2)
    assert m.device_id == "d"


def test_rejects_empty_device_id():
    with pytest.raises(ValidationError):
        MetricIn(deviceId="", power=1, temperature=2)


def test_requires_power():
    with pytest.raises(ValidationError):
        MetricIn(deviceId="d", temperature=2)


def test_device_in_alias():
    d = DeviceIn(**{"deviceId": "d", "label": "L", "location": "X"})
    assert d.device_id == "d" and d.label == "L" and d.location == "X"
