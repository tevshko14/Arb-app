-- Bet Buddy Phase 1: Initial Schema
-- Run this against your Supabase SQL Editor

-- Enums
CREATE TYPE sport_type AS ENUM ('baseball_mlb', 'mma_mixed_martial_arts');
CREATE TYPE event_status AS ENUM ('upcoming', 'live', 'completed', 'cancelled');

-- Events: Universal canonical representation
CREATE TABLE events (
    id              VARCHAR(64) PRIMARY KEY,
    sport           sport_type NOT NULL,
    league          VARCHAR(64) NOT NULL,
    home_team       VARCHAR(128) NOT NULL,
    away_team       VARCHAR(128) NOT NULL,
    commence_time   TIMESTAMPTZ NOT NULL,
    status          event_status NOT NULL DEFAULT 'upcoming',
    external_ids    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_events_sport_commence ON events (sport, commence_time);
CREATE INDEX ix_events_status ON events (status);

-- Bookmakers registry
CREATE TABLE bookmakers (
    key         VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    region      VARCHAR(16) NOT NULL DEFAULT 'ca',
    is_sharp    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed sharp books
INSERT INTO bookmakers (key, name, region, is_sharp) VALUES
    ('pinnacle', 'Pinnacle', 'global', true)
ON CONFLICT (key) DO NOTHING;

-- Odds snapshots: full historical record of every poll
CREATE TABLE odds_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    event_id        VARCHAR(64) NOT NULL REFERENCES events(id),
    bookmaker_key   VARCHAR(64) NOT NULL REFERENCES bookmakers(key),
    market          VARCHAR(32) NOT NULL DEFAULT 'h2h',
    outcome_name    VARCHAR(128) NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    point           DOUBLE PRECISION,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_odds_event_book_time ON odds_snapshots (event_id, bookmaker_key, captured_at);
CREATE INDEX ix_odds_captured ON odds_snapshots (captured_at);

-- Odds latest: current best price per event/outcome (upsert target)
CREATE TABLE odds_latest (
    id              BIGSERIAL PRIMARY KEY,
    event_id        VARCHAR(64) NOT NULL REFERENCES events(id),
    bookmaker_key   VARCHAR(64) NOT NULL REFERENCES bookmakers(key),
    market          VARCHAR(32) NOT NULL DEFAULT 'h2h',
    outcome_name    VARCHAR(128) NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    point           DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ix_latest_event_book_market_outcome
    ON odds_latest (event_id, bookmaker_key, market, outcome_name);

-- Entity mappings: fuzzy resolution lookup
CREATE TABLE entity_mappings (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,
    source_name     VARCHAR(256) NOT NULL,
    canonical_name  VARCHAR(256) NOT NULL,
    sport           VARCHAR(64) NOT NULL,
    entity_type     VARCHAR(32) NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    is_manual       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ix_entity_source_name
    ON entity_mappings (source, source_name, sport);

-- Ingestion health: heartbeat monitoring
CREATE TABLE ingestion_health (
    id                  BIGSERIAL PRIMARY KEY,
    sport               VARCHAR(64) NOT NULL,
    events_found        INTEGER NOT NULL DEFAULT 0,
    snapshots_written   INTEGER NOT NULL DEFAULT 0,
    errors              VARCHAR(512),
    latency_ms          INTEGER,
    polled_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_health_polled ON ingestion_health (polled_at);

-- Auto-update updated_at on events
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_updated_at
    BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
