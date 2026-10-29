from datetime import datetime,timezone,timedelta
import pytest
from task_runner.scheduling import compute_next,parse_utc,utc_text

UTC=timezone.utc


def test_manual_is_never_scheduled():
    assert compute_next("manual",{},datetime(2026,10,29,tzinfo=UTC)) is None


def test_interval_is_relative_and_strict():
    at=datetime(2026,10,29,13,15,tzinfo=UTC)
    assert compute_next("interval",{"seconds":120},at)==at+timedelta(seconds=120)


def test_interval_rejects_nonpositive():
    with pytest.raises(ValueError):compute_next("interval",{"seconds":0})


def test_cron_produces_future_utc():
    at=datetime(2026,10,29,13,15,tzinfo=UTC)
    pytest.importorskip("croniter")
    pytest.importorskip("tzlocal")
    result=compute_next("cron",{"expression":"*/10 * * * *"},at)
    assert result>at
    assert result.tzinfo is not None


def test_once_past_returns_none():
    pytest.importorskip("tzlocal")
    assert compute_next("once",{"at":"2000-01-01T12:00:00"}) is None


def test_utc_serialization_roundtrip():
    at=datetime(2026,10,29,13,15,29,tzinfo=UTC)
    assert parse_utc(utc_text(at))==at


def test_cron_requires_exactly_five_fields():
    pytest.importorskip("croniter")
    pytest.importorskip("tzlocal")
    with pytest.raises(ValueError):compute_next("cron",{"expression":"* * * * * *"})
