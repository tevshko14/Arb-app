import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class SportType(str, enum.Enum):
    MLB = "baseball_mlb"
    MMA = "mma_mixed_martial_arts"


class EventStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Event(Base):
    """Universal Event — the canonical representation of a sporting event."""

    __tablename__ = "events"

    id = Column(String(64), primary_key=True, comment="Universal Event ID")
    sport = Column(Enum(SportType), nullable=False, index=True)
    league = Column(String(64), nullable=False)
    home_team = Column(String(128), nullable=False)
    away_team = Column(String(128), nullable=False)
    commence_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        Enum(EventStatus), nullable=False, default=EventStatus.UPCOMING
    )
    external_ids = Column(
        Text, nullable=True, comment="JSON map of source→external_id"
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_events_sport_commence", "sport", "commence_time"),
    )


class Bookmaker(Base):
    """Registry of tracked sportsbooks."""

    __tablename__ = "bookmakers"

    key = Column(String(64), primary_key=True, comment="The-Odds-API key")
    name = Column(String(128), nullable=False)
    region = Column(String(16), nullable=False, default="ca")
    is_sharp = Column(
        String(1), nullable=False, default="N", comment="Y if sharp book"
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
