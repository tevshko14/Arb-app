from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)

from app.models.events import Base


class OddsSnapshot(Base):
    """Timestamped odds record — every poll writes here for full history."""

    __tablename__ = "odds_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        String(64), ForeignKey("events.id"), nullable=False, index=True
    )
    bookmaker_key = Column(
        String(64), ForeignKey("bookmakers.key"), nullable=False
    )
    market = Column(
        String(32), nullable=False, default="h2h", comment="h2h, spreads, totals"
    )
    outcome_name = Column(String(128), nullable=False)
    price = Column(Float, nullable=False, comment="Decimal odds")
    point = Column(Float, nullable=True, comment="Spread/total line")
    captured_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_odds_event_book_time", "event_id", "bookmaker_key", "captured_at"),
        Index("ix_odds_captured", "captured_at"),
    )


class OddsLatest(Base):
    """Current best odds per event/outcome — fast-read materialized view."""

    __tablename__ = "odds_latest"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        String(64), ForeignKey("events.id"), nullable=False
    )
    bookmaker_key = Column(
        String(64), ForeignKey("bookmakers.key"), nullable=False
    )
    market = Column(String(32), nullable=False, default="h2h")
    outcome_name = Column(String(128), nullable=False)
    price = Column(Float, nullable=False)
    point = Column(Float, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_latest_event_book_market_outcome",
            "event_id",
            "bookmaker_key",
            "market",
            "outcome_name",
            unique=True,
        ),
    )


class IngestionHealth(Base):
    """Heartbeat log for monitoring the ingestion pipeline."""

    __tablename__ = "ingestion_health"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sport = Column(String(64), nullable=False)
    events_found = Column(Integer, nullable=False, default=0)
    snapshots_written = Column(Integer, nullable=False, default=0)
    errors = Column(String(512), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    polled_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_health_polled", "polled_at"),)


class EntityMapping(Base):
    """Entity resolution lookup — maps source names to canonical names."""

    __tablename__ = "entity_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(
        String(64), nullable=False, comment="Bookmaker or data source key"
    )
    source_name = Column(String(256), nullable=False)
    canonical_name = Column(String(256), nullable=False)
    sport = Column(String(64), nullable=False)
    entity_type = Column(
        String(32), nullable=False, comment="team or fighter"
    )
    confidence = Column(Float, nullable=False, default=1.0)
    is_manual = Column(
        String(1), nullable=False, default="N", comment="Y if manually curated"
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_entity_source_name",
            "source",
            "source_name",
            "sport",
            unique=True,
        ),
    )
