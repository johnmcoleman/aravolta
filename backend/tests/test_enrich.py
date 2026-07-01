"""Unit: the _enrich status/alert logic (pure function). No infra needed."""
from datetime import datetime, timedelta, timezone

from app.main import _enrich

NOW = datetime(2026, 6, 30, 20, 0, 0, tzinfo=timezone.utc)
DEVICE = {"device_id": "d", "label": None, "location": None}


def _latest(power=500.0, temp=70.0, age_s=5):
    return {"power": power, "temperature": temp,
            "timestamp": (NOW - timedelta(seconds=age_s)).isoformat()}


def test_no_data_is_offline_and_ok():
    r = _enrich(DEVICE, None, NOW)
    assert r["online"] is False and r["alert"] is False and r["latest"] is None


def test_recent_reading_is_online():
    r = _enrich(DEVICE, _latest(age_s=5), NOW)
    assert r["online"] is True and r["alert"] is False


def test_stale_reading_is_offline():
    r = _enrich(DEVICE, _latest(age_s=60), NOW)  # > online_window_seconds (30)
    assert r["online"] is False


def test_high_power_alerts():
    r = _enrich(DEVICE, _latest(power=1200), NOW)
    assert r["alert"] is True and r["alertReasons"] == ["power"]


def test_high_temp_alerts():
    r = _enrich(DEVICE, _latest(temp=90), NOW)
    assert r["alert"] is True and r["alertReasons"] == ["temperature"]


def test_both_thresholds_alert():
    r = _enrich(DEVICE, _latest(power=1200, temp=90), NOW)
    assert r["alertReasons"] == ["power", "temperature"]
