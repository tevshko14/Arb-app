# Bet Buddy — InfoFi Platform

**Data-driven sports betting signal engine for the Canadian market.**

Bet Buddy identifies Positive Expected Value (+EV) opportunities by comparing odds across all Canadian-available sportsbooks against sharp market prices. It transitions sports betting from gambling to quantitative asset management.

## What It Does

1. **Polls odds** from 11+ sportsbooks via The-Odds-API (Pinnacle as the sharp anchor, bet365/FanDuel/DraftKings/etc. as soft books)
2. **Normalizes data** — resolves naming differences across books (e.g., "Jays" → "Toronto Blue Jays") using fuzzy matching
3. **Stores full history** — every odds snapshot is timestamped for line movement analysis and backtesting
4. **Adaptive polling** — smart 3-tier scheduler saves API costs while catching line movements:
   - **Idle** (5 min) — no games within 6 hours
   - **Warm** (60s) — games 2–6 hours away
   - **Hot** (30s) — games < 2 hours out
5. **Serves signals** via a FastAPI REST API with health monitoring

## Supported Sports (Phase 1)

- MLB (Major League Baseball)
- UFC / MMA (Mixed Martial Arts)

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (for Redis)
- A [Supabase](https://supabase.com) project (free tier works)
- An API key from [The-Odds-API](https://the-odds-api.com)

### Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd Arb-app

# 2. Start Redis
docker compose up -d

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys and Supabase connection string

# 4. Run the database migration
# Copy the contents of backend/migrations/001_initial_schema.sql
# and run it in your Supabase SQL Editor (Dashboard → SQL Editor → New Query)

# 5. Install dependencies
cd backend
pip install -r requirements.txt

# 6. Start the server
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. Swagger docs at `http://localhost:8000/docs`.

### Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System health (DB, Redis, scheduler status) |
| `/health/ingestion` | GET | Recent poll history with freshness check |
| `/events` | GET | List events (filter by sport, status; paginated) |
| `/odds/{event_id}` | GET | Latest odds across all bookmakers |
| `/odds/{event_id}/history` | GET | Historical odds snapshots for line movement |
| `/quota` | GET | Remaining Odds API request quota |

### Query Parameters

**`/events`**
- `sport` — `baseball_mlb` or `mma_mixed_martial_arts`
- `status` — `upcoming` (default), `live`, `completed`, `cancelled`
- `limit` — 1–200 (default 50)
- `offset` — pagination offset (default 0)

**`/odds/{event_id}/history`**
- `bookmaker` — filter by bookmaker key (e.g., `pinnacle`)
- `limit` — 1–1000 (default 100)

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   FastAPI App                     │
│  /health  /events  /odds  /quota                 │
└──────────┬──────────────────┬────────────────────┘
           │                  │
    ┌──────▼──────┐    ┌──────▼──────┐
    │  Adaptive   │    │   Redis     │
    │  Scheduler  │    │   Cache     │
    │ (idle/warm/ │    │ (latest     │
    │    hot)     │    │  prices)    │
    └──────┬──────┘    └─────────────┘
           │
    ┌──────▼──────┐
    │  Ingestion  │
    │  Pipeline   │
    │  ┌────────┐ │
    │  │OddsAPI │ │──→ The-Odds-API
    │  │Client  │ │
    │  └────────┘ │
    │  ┌────────┐ │
    │  │Normal- │ │
    │  │izer    │ │
    │  └────────┘ │
    │  ┌────────┐ │
    │  │Entity  │ │──→ Fuzzy matching + static maps
    │  │Resolver│ │
    │  └────────┘ │
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │  Supabase   │
    │  (Postgres) │
    │  ┌────────┐ │
    │  │events  │ │
    │  │odds_*  │ │
    │  │health  │ │
    │  └────────┘ │
    └─────────────┘
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `ODDS_API_KEY` | The-Odds-API key | *required* |
| `DATABASE_URL` | Supabase Postgres connection string | *required* |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `POLL_IDLE_INTERVAL` | Seconds between polls (no near games) | `300` |
| `POLL_WARM_INTERVAL` | Seconds between polls (games 2-6h out) | `60` |
| `POLL_HOT_INTERVAL` | Seconds between polls (games < 2h out) | `30` |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins (JSON list) | `["http://localhost:3000"]` |
| `LOG_LEVEL` | Python log level | `INFO` |

## Roadmap

- **Phase 1** (current): Data ingestion, entity resolution, adaptive polling
- **Phase 2**: Monte Carlo simulator, ensemble scoring, Edge/Alpha calculation
- **Phase 3**: Kelly Criterion engine, InfoFi signal scanner, variance tester
- **Phase 4**: Next.js dashboard, Telegram/Discord alerts, deployment

## License

Private — all rights reserved.
