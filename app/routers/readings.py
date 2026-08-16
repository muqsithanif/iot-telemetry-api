"""Ingestion and query endpoints.

Ingestion authenticates as a device (X-API-Key); queries authenticate as a user
(bearer token). A device can only ever write to its own series.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_device, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import Device, Reading, User, utcnow
from app.schemas import (
    IngestResult,
    MetricSummary,
    ReadingBatch,
    ReadingIn,
    ReadingOut,
)

router = APIRouter(tags=["readings"])
settings = get_settings()


def _as_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC rather than guessing the device's zone."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _store(db: Session, device: Device, item: ReadingIn) -> str:
    """Insert one reading. Returns 'accepted', 'duplicate', or a rejection reason."""
    recorded_at = _as_utc(item.recorded_at) if item.recorded_at else utcnow()
    now = utcnow()

    if recorded_at > now + timedelta(minutes=5):
        return "timestamp is in the future"
    if recorded_at < now - timedelta(hours=settings.max_reading_age_hours):
        return f"timestamp older than {settings.max_reading_age_hours}h"

    reading = Reading(
        device_id=device.id,
        metric=item.metric,
        value=item.value,
        unit=item.unit,
        recorded_at=recorded_at,
    )
    db.add(reading)
    try:
        db.commit()
    except IntegrityError:
        # Unique constraint on (device, metric, recorded_at): the device retried
        # a batch it already delivered. Not an error worth failing the request.
        db.rollback()
        return "duplicate"
    return "accepted"


@router.post("/readings", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
def ingest(
    payload: ReadingBatch,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> IngestResult:
    accepted = duplicates = 0
    rejected: list[str] = []

    for item in payload.readings:
        outcome = _store(db, device, item)
        if outcome == "accepted":
            accepted += 1
        elif outcome == "duplicate":
            duplicates += 1
        else:
            rejected.append(f"{item.metric}: {outcome}")

    return IngestResult(accepted=accepted, duplicates=duplicates, rejected=rejected)


@router.get("/devices/{device_id}/readings", response_model=list[ReadingOut])
def list_readings(
    device_id: int,
    metric: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Reading]:
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    # device_id first, then recorded_at — the order the composite index expects.
    query = db.query(Reading).filter(Reading.device_id == device_id)
    if metric:
        query = query.filter(Reading.metric == metric.lower())
    if since:
        query = query.filter(Reading.recorded_at >= _as_utc(since))
    if until:
        query = query.filter(Reading.recorded_at <= _as_utc(until))

    return (
        query.order_by(Reading.recorded_at.desc()).offset(offset).limit(limit).all()
    )


@router.get("/devices/{device_id}/summary", response_model=list[MetricSummary])
def summarise(
    device_id: int,
    since: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MetricSummary]:
    """Aggregate in the database rather than pulling rows into Python."""
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    query = db.query(
        Reading.metric,
        func.count(Reading.id),
        func.min(Reading.value),
        func.max(Reading.value),
        func.avg(Reading.value),
        func.min(Reading.recorded_at),
        func.max(Reading.recorded_at),
    ).filter(Reading.device_id == device_id)

    if since:
        query = query.filter(Reading.recorded_at >= _as_utc(since))

    rows = query.group_by(Reading.metric).order_by(Reading.metric).all()
    return [
        MetricSummary(
            device_id=device_id,
            metric=metric,
            count=count,
            minimum=minimum,
            maximum=maximum,
            average=round(average, 4),
            first_recorded_at=first,
            last_recorded_at=last,
        )
        for metric, count, minimum, maximum, average, first, last in rows
    ]
