"""Local-time schedules evaluated and persisted as UTC timestamps."""
from datetime import datetime, timedelta, timezone
from typing import Optional

UTC = timezone.utc


def parse_utc(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def local_text(value: str | None) -> str:
    dt = parse_utc(value)
    if not dt:
        return "—"
    from tzlocal import get_localzone
    return dt.astimezone(get_localzone()).strftime("%Y-%m-%d %H:%M:%S")


def compute_next(kind: str, config: dict, after: datetime | None = None) -> datetime | None:
    """Next schedule occurrence STRICTLY AFTER `after` (UTC)."""
    after = (after or utc_now()).astimezone(UTC)
    if kind == "manual":
        return None
    if kind == "file_event":
        from .file_events import validate
        validate(config)
        return None
    if kind == "interval":
        seconds = int(config["seconds"])
        if seconds < 1:
            raise ValueError("Interval must be at least one second")
        return after + timedelta(seconds=seconds)
    from tzlocal import get_localzone
    local = get_localzone()
    base = after.astimezone(local)
    if kind == "once":
        raw = datetime.fromisoformat(str(config["at"]))
        dt = (raw.replace(tzinfo=local) if raw.tzinfo is None else raw).astimezone(UTC)
        return dt if dt > after else None
    from croniter import croniter
    if kind == "daily":
        h, m = (int(x) for x in str(config["time"]).split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid daily time")
        return croniter(f"{m} {h} * * *", base).get_next(datetime).astimezone(UTC)
    if kind == "weekly":
        h, m = (int(x) for x in str(config["time"]).split(":"))
        day = int(config["weekday"])
        if not (0 <= day <= 6 and 0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid weekly day/time")
        cron_day = (day + 1) % 7
        return croniter(f"{m} {h} * * {cron_day}", base).get_next(datetime).astimezone(UTC)
    if kind == "cron":
        expr = str(config["expression"]).strip()
        if len(expr.split()) != 5:
            raise ValueError("Use a five-field cron expression: minute hour day month weekday")
        return croniter(expr, base).get_next(datetime).astimezone(UTC)
    raise ValueError(f"Unrecognized schedule: {kind}")
