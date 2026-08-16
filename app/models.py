"""Database tables.

Schema notes that matter for a telemetry workload:

* `readings` is append-only and grows fastest, so it carries a composite index
  on (device_id, recorded_at). Every read path filters by device and then by
  time window, and that index serves both without a table scan.
* `devices.api_key_hash` is unique so a device can be looked up by its key in
  one indexed hit during ingestion.
* Deleting a device cascades to its readings; orphaned rows are never useful.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # "admin" may register devices and delete data; "reader" may only query.
    role: Mapped[str] = mapped_column(String(16), default="reader")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    readings: Mapped[list["Reading"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Time the device says it sampled, not the time the server received it.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    device: Mapped[Device] = relationship(back_populates="readings")

    __table_args__ = (
        Index("ix_readings_device_time", "device_id", "recorded_at"),
        # A device sending the same metric twice for the same instant is a
        # retry, not new data. Rejecting it keeps ingestion idempotent.
        UniqueConstraint(
            "device_id", "metric", "recorded_at", name="uq_reading_device_metric_time"
        ),
    )
