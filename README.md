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
5. **Simulates outcomes** — Monte Carlo engine with sport-specific models (Poisson for MLB, Elo for UFC) and variance reduction techniques
6. **Finds +EV edges** — ensemble scoring blends sharp lines, model output, and Bayesian priors, then compares against soft book odds
7. **Sizes bets** — Kelly Criterion (Half Kelly default) with portfolio exposure caps
8. **Tracks accuracy** — Brier score calibration automatically shifts ensemble weights as the model proves itself
9. **Serves signals** via a FastAPI REST API with health monitoring

## Supported Sports (Phase 1)

- MLB (Major League Baseball)
- UFC / MMA (Mixed Martial Arts)

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
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

# 5. Install and start the backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# 6. Install and start the dashboard (in a new terminal)
cd frontend
npm install
npm run dev
```

The API will be available at `http://localhost:8000`. Swagger docs at `http://localhost:8000/docs`.
The dashboard will be available at `http://localhost:3000`.

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
| `/signals` | GET | Current +EV signals — the Daily Golden Plays |
| `/calibration` | GET | Model calibration metrics (Brier scores) |
| `/risk` | GET | Risk management state (drawdown, Kelly, exposure) |
| `/clv` | GET | Closing Line Value report (signal quality) |
| `/alerts` | GET | Line movement alerts (steam moves, stale lines) |

### Query Parameters

**`/events`**
- `sport` — `baseball_mlb` or `mma_mixed_martial_arts`
- `status` — `upcoming` (default), `live`, `completed`, `cancelled`
- `limit` — 1–200 (default 50)
- `offset` — pagination offset (default 0)

**`/odds/{event_id}/history`**
- `bookmaker` — filter by bookmaker key (e.g., `pinnacle`)
- `limit` — 1–1000 (default 100)

**`/signals`**
- `sport` — filter by sport key
- `min_edge` — minimum edge threshold, 0.0–0.5 (default 0.02 = 2%)
- `limit` — 1–100 (default 20)

**`/alerts`**
- `hours` — look back period, 1–168 (default 24)
- `priority` — filter by priority: `high`, `medium`, `low`

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI App                            │
│  /health  /events  /odds  /quota  /signals  /calibration     │
└──────┬──────────────────┬───────────────────┬────────────────┘
       │                  │                   │
┌──────▼──────┐    ┌──────▼──────┐    ┌───────▼────────┐
│  Adaptive   │    │   Redis     │    │  Signal        │
│  Scheduler  │    │   Cache     │    │  Pipeline      │
│ (idle/warm/ │    │ (latest     │    │  ("The Brain") │
│    hot)     │    │  prices)    │    └───────┬────────┘
└──────┬──────┘    └─────────────┘            │
       │                              ┌───────┼───────────┐
┌──────▼──────┐                ┌──────▼──┐ ┌──▼────┐ ┌────▼───┐
│  Ingestion  │                │Ensemble │ │ Edge  │ │ Kelly  │
│  Pipeline   │                │ Scorer  │ │Finder │ │ Sizer  │
│  ┌────────┐ │                └────┬────┘ └───────┘ └────────┘
│  │OddsAPI │ │──→ The-Odds-API    │
│  │Client  │ │               ┌────┼────────────┐
│  └────────┘ │          ┌────▼──┐ │       ┌────▼───────┐
│  ┌────────┐ │          │Sharp  │ │       │ Calibration│
│  │Normal- │ │          │ Line  │ │       │ Tracker    │
│  │izer    │ │          └───────┘ │       │ (Brier)    │
│  └────────┘ │               ┌────▼────┐  └────────────┘
│  ┌────────┐ │               │Monte    │
│  │Entity  │ │──→ Fuzzy      │Carlo    │
│  │Resolver│ │    matching   │Engine   │
│  └────────┘ │               ├─────────┤
└──────┬──────┘               │MLB:Pois.│
       │                      │UFC:Elo  │
┌──────▼──────┐               └─────────┘
│  Supabase   │
│  (Postgres) │
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

## How The Brain Works

The signal engine (Phase 2) runs a full analysis pipeline for each event:

1. **Sharp Line Extraction** — pulls Pinnacle odds, removes vig to get "true" probabilities
2. **Monte Carlo Simulation** — runs 10,000 simulations per event:
   - **MLB**: Poisson run-scoring model (offense/defense ratings, pitcher ERA, home field)
   - **UFC**: Elo rating system + striking/grappling stat adjustments
   - **Variance reduction**: antithetic variates + stratified sampling for accurate estimates
3. **Ensemble Scoring** — blends three probability sources:
   - Sharp line (55%) — the market's best estimate
   - Sport model (35%) — our independent Monte Carlo estimate
   - Bayesian prior (10%) — shrinkage toward 50% to prevent overconfidence
4. **Edge Detection** — compares ensemble probability against each soft bookmaker's odds:
   - `Edge = (Model_Prob × Decimal_Odds) - 1`
   - Only surfaces edges above 2% threshold
5. **Kelly Sizing** — calculates optimal bet size:
   - Half Kelly (0.5×) by default for conservative bankroll growth
   - 5% max single-bet cap, 20% max portfolio exposure
6. **Calibration Tracking** — Brier score monitors prediction accuracy:
   - When model proves calibrated (Brier < 0.15), ensemble auto-shifts weight toward model
   - Walk-forward backtesting validates on rolling windows

## Risk & Intelligence (Phase 3)

The system includes four defensive intelligence modules:

1. **Risk Manager** — dynamic Kelly tuning based on performance:
   - Four risk levels: Aggressive / Normal / Cautious / Defensive
   - Kelly multiplier adjusts automatically (0.65× → 0.15× based on drawdown)
   - Per-bookmaker exposure limits prevent concentration risk
   - Circuit breaker halts betting if bankroll drops below 25% of initial
2. **CLV Tracker** — measures signal quality via Closing Line Value:
   - Tracks whether lines move in our direction after we signal an edge
   - Positive CLV = capturing real information inefficiencies
   - Bookmaker softness scoring — ranks which books are most exploitable
3. **Humanizer** — makes bet patterns look natural to avoid restrictions:
   - Stake randomization (±5-15%) with rounding to natural amounts
   - Timing delays (log-normal distribution, ~2 min average)
   - Per-bookmaker daily/weekly frequency limits
   - Win streak cooloff to avoid automated detection
   - Bookmaker rotation suggestions
4. **InfoFi Scanner** — line movement detection:
   - Steam moves — sudden sharp line changes (>3% implied probability)
   - Stale line detection — bookmakers slow to update vs sharp market
   - Convergence tracking — soft books drifting toward Pinnacle prices
   - Market consensus calculation from all bookmakers

## Roadmap

- **Phase 1** ✓: Data ingestion, entity resolution, adaptive polling
- **Phase 2** ✓: Monte Carlo simulator, ensemble scoring, edge/Kelly/calibration engine
- **Phase 3** ✓: Risk management, CLV tracking, humanizer, InfoFi line scanner
- **Phase 4** ✓: Next.js dashboard, Discord/Telegram alerts

## License

Private — all rights reserved.
