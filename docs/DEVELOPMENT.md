# Developer Guide — Bet Buddy

## Project Structure

```
Arb-app/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app, routes, lifespan
│   │   ├── config.py                   # Pydantic settings (env vars)
│   │   ├── models/
│   │   │   ├── events.py               # SQLAlchemy ORM: Event, Bookmaker
│   │   │   └── odds.py                 # SQLAlchemy ORM: OddsSnapshot, OddsLatest, etc.
│   │   ├── ingestion/
│   │   │   ├── odds_api_client.py      # HTTP client for The-Odds-API v4
│   │   │   ├── normalizer.py           # Raw JSON → canonical dicts
│   │   │   ├── pipeline.py             # Orchestrates: fetch → normalize → store → cache
│   │   │   └── scheduler.py            # Adaptive 3-tier polling loop
│   │   ├── entity_resolution/
│   │   │   ├── resolver.py             # Fuzzy matcher + static JSON tables
│   │   │   └── mappings/
│   │   │       ├── mlb_teams.json      # All 30 MLB teams + variants
│   │   │       └── ufc_fighters.json   # Top UFC fighters + variants
│   │   ├── engine/                     # Phase 2 — "The Brain"
│   │   │   ├── monte_carlo.py          # MC engine (antithetic + stratified sampling)
│   │   │   ├── models/
│   │   │   │   ├── mlb.py              # Poisson run-scoring model
│   │   │   │   └── ufc.py             # Elo + stat adjustment model
│   │   │   ├── ensemble.py             # Weighted probability blending
│   │   │   ├── edge.py                 # Edge detection across bookmakers
│   │   │   ├── kelly.py                # Kelly Criterion bet sizing
│   │   │   ├── calibration.py          # Brier score tracking + backtesting
│   │   │   ├── signal_pipeline.py      # Full analysis orchestrator
│   │   │   ├── risk_manager.py         # Phase 3 — dynamic Kelly + drawdown protection
│   │   │   ├── clv_tracker.py          # Phase 3 — Closing Line Value measurement
│   │   │   ├── humanizer.py            # Phase 3 — bet pattern randomization
│   │   │   ├── line_movement.py        # Phase 3 — InfoFi line scanner
│   │   │   └── alerts.py              # Phase 4 — Discord/Telegram webhooks
│   │   └── utils/
│   │       ├── database.py             # Async SQLAlchemy engine (lazy init)
│   │       ├── health.py               # Health check functions
│   │       ├── redis_cache.py          # Redis odds cache
│   │       └── validation.py           # Input validation (event IDs, bookmaker keys)
│   ├── migrations/
│   │   └── 001_initial_schema.sql      # Supabase DDL
│   ├── tests/
│   │   ├── test_normalizer.py          # 16 tests — normalizer + edge cases
│   │   ├── test_entity_resolver.py     # 11 tests — fuzzy + static matching
│   │   ├── test_scheduler.py           # 7 tests — tier determination logic
│   │   ├── test_odds_api_client.py     # 4 tests — quota tracking, error types
│   │   ├── test_api_validation.py      # 12 tests — input validation + injection defense
│   │   ├── test_edge.py                # 13 tests — edge calculation + vig removal
│   │   ├── test_monte_carlo.py         # 14 tests — MC engine + variance reduction
│   │   ├── test_kelly.py               # 14 tests — Kelly sizing + portfolio caps
│   │   ├── test_ensemble.py            # 10 tests — ensemble scoring + disagreement
│   │   ├── test_calibration.py         # 10 tests — Brier scores + backtesting
│   │   ├── test_sport_models.py        # 17 tests — MLB Poisson + UFC Elo
│   │   ├── test_risk_manager.py        # 18 tests — risk levels, Kelly tuning, exposure
│   │   ├── test_clv_tracker.py         # 12 tests — CLV calculation, bookmaker profiling
│   │   ├── test_humanizer.py           # 14 tests — stake noise, timing, suppression
│   │   ├── test_line_movement.py       # 15 tests — steam moves, stale lines, consensus
│   │   └── test_alerts.py             # 12 tests — webhook config, message formatting
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/                           # Phase 4 — Next.js dashboard
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx             # Root layout with nav
│   │   │   ├── page.tsx               # Dashboard — signals, risk, calibration
│   │   │   ├── events/page.tsx        # Events browser
│   │   │   ├── alerts/page.tsx        # Alerts feed + CLV + bookmaker softness
│   │   │   └── globals.css            # Tailwind + dark theme CSS
│   │   ├── components/
│   │   │   ├── Nav.tsx                # Navigation bar
│   │   │   ├── Card.tsx               # Content card wrapper
│   │   │   ├── MetricBox.tsx          # Metric display box
│   │   │   └── StatusBadge.tsx        # Color-coded status badges
│   │   └── lib/
│   │       ├── api.ts                 # Typed API client for backend
│   │       └── types.ts              # TypeScript interfaces matching Pydantic
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   └── postcss.config.mjs
├── docker-compose.yml                  # Redis only
├── .env.example
├── .gitignore
└── README.md
```

## Data Flow

```
The-Odds-API  ──→  OddsAPIClient.get_events(sport)
                        │
                        ▼
                   Raw JSON events
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
        normalize_   normalize_  extract_
        event()      odds()     bookmakers()
              │         │         │
              ▼         ▼         ▼
        EntityResolver.resolve()
              │         │         │
              ▼         ▼         ▼
        ┌─────────────────────────────┐
        │    PostgreSQL (Supabase)    │
        │  events │ odds_snapshots   │
        │  odds_latest │ bookmakers  │
        │  ingestion_health          │
        └─────────────────────────────┘
              │
              ▼
        Redis Cache (odds:latest:*)
```

## Key Design Decisions

### Lazy Database Initialization
`database.py` uses `@lru_cache` to create the SQLAlchemy engine on first use, not at import time. This prevents import errors when tests don't need a DB connection.

### Entity Resolution Strategy
Resolution order:
1. **Exact match** in static JSON table → O(1) dict lookup
2. **Fuzzy match** via `rapidfuzz.fuzz.token_sort_ratio` with 85% threshold → catches misspellings
3. **No match** → returns original name, logs warning for manual review

Results are cached in-memory (dict) to avoid repeated fuzzy comparisons.

### Adaptive Polling
The scheduler checks `next_commence_time` after each poll to determine the tier:
- If no games within 6h → poll every 5 minutes (save API quota)
- If game within 2-6h → poll every 60 seconds (catch early line moves)
- If game within 2h → poll every 30 seconds (catch steam moves)

Rate limit (429) → automatic 120-second backoff.

### Parameterized SQL
All queries use SQLAlchemy `text()` with `:param` placeholders — **never** string interpolation. Input validation via regex patterns blocks injection at the API layer as an additional defense.

## Database Schema

### Core Tables

**`events`** — Canonical events with Universal Event IDs
- Primary key: `id` (from The-Odds-API)
- Indexed: `sport + commence_time`, `status`
- Trigger: auto-updates `updated_at` on any modification

**`bookmakers`** — Registry of tracked sportsbooks
- `is_sharp` boolean — true for Pinnacle, false for soft books
- Seeded with Pinnacle on migration

**`odds_snapshots`** — Full historical record (append-only)
- Every poll writes new rows — never overwrites
- Indexed: `event_id + bookmaker_key + captured_at`
- Used for: line movement analysis, CLV calculation, backtesting

**`odds_latest`** — Current best price (upsert target)
- Unique constraint: `event_id + bookmaker_key + market + outcome_name`
- Used for: real-time signal display, edge calculation

**`entity_mappings`** — Resolution lookup (DB-backed, for future use)
- Currently unused — resolution runs from JSON files
- Planned: auto-persist fuzzy matches to DB for learning

**`ingestion_health`** — Heartbeat log
- Tracks: events found, snapshots written, errors, latency per poll
- Freshness check: flags if last poll > 10 minutes ago

## Phase 2 — Engine Design ("The Brain")

### Monte Carlo Engine (`engine/monte_carlo.py`)

The core simulation engine supports two modes:
- **Binary simulation** — for two-outcome events (UFC win/loss). Uses antithetic variates (mirrors each random draw) to cut variance in half.
- **Scoring simulation** — for score-based events (MLB runs). Takes callable scoring functions that generate random scores per simulation.

Variance reduction techniques:
- **Antithetic variates**: For each random uniform `u`, also simulate with `1 - u`. Doubles effective sample size at zero cost.
- **Stratified sampling**: Divides `[0, 1]` into `n` equal strata and draws one sample per stratum. Eliminates clustering.
- **Importance sampling**: Overweights the underdog region for rare events (prob < 10%), then corrects with likelihood ratios. Reduces estimation error for tail probabilities.

All methods accept a `seed` parameter for reproducibility.

### Sport Models

**MLB Poisson** (`engine/models/mlb.py`):
- Expected runs use a log5/Pythagorean formula: `(team_offense * opponent_defense) / league_avg`
- Adjustments: home field (+0.25 runs), starter ERA (scales opponent defense)
- Simulation: independent Poisson draws for each team's runs, count wins/losses/draws across 10K sims

**UFC Elo** (`engine/models/ufc.py`):
- Base probability from standard logistic Elo: `1 / (1 + 10^((elo_b - elo_a) / 400))`
- Stat adjustment (±10% cap): 60% striking differential + 40% grappling differential
- Combined probability clamped to [0.05, 0.95] to prevent extreme confidence

### Ensemble Scorer (`engine/ensemble.py`)

Blends three probability sources with configurable weights:

| Source | Default Weight | Description |
|---|---|---|
| Sharp line | 0.55 | Pinnacle implied probability (vig-removed) |
| Sport model | 0.35 | Our Monte Carlo simulation output |
| Bayesian prior | 0.10 | Uniform prior — shrinkage toward 50% |

Weights auto-normalize to sum to 1.0. When the calibration tracker confirms model accuracy (Brier < 0.15), the system recommends shifting to `CALIBRATED_WEIGHTS` (model=0.55, sharp=0.35).

The `disagreement` metric (mean absolute difference between sharp and model) flags potential alpha or miscalibration.

### Edge Detection (`engine/edge.py`)

For each soft bookmaker's odds:
1. Convert decimal odds to implied probability: `1 / odds`
2. Compare against ensemble probability: `edge = (model_prob × decimal_odds) - 1`
3. Surface edges above the min_edge threshold (default 2%)

Vig removal normalizes a bookmaker's implied probabilities to sum to 1.0, revealing the "true" market probability underneath the margin.

### Kelly Criterion (`engine/kelly.py`)

Full Kelly formula: `f* = (p × b - q) / b` where `p` = model probability, `b` = decimal odds - 1, `q` = 1 - p.

Safety rails:
- **Half Kelly** (0.5×) by default — trades growth rate for lower variance
- **5% max stake** on any single bet
- **20% max portfolio exposure** — if total exceeds this, all bets are scaled proportionally
- **2% min edge** — won't recommend bets with tiny edges (noise risk)

### Calibration (`engine/calibration.py`)

Tracks prediction accuracy via Brier score: `BS = (1/N) × Σ(predicted - actual)²`
- Lower is better (0 = perfect, 0.25 = coin flip on binary events)
- Computes per-sport breakdown and calibration bins (deciles)
- `should_increase_model_weight()` returns `True` when ensemble Brier beats sharp-only by >0.005

Walk-forward backtester validates on rolling windows without lookahead bias.

### Signal Pipeline (`engine/signal_pipeline.py`)

Orchestrates the full flow for one event:
1. Extract sharp probs (Pinnacle, vig-removed)
2. Ensemble blend (sharp + model + prior)
3. Find edges against all soft bookmakers
4. Kelly sizing for each edge signal
5. Portfolio cap (scale down if total exposure > 20%)
6. Record predictions for calibration tracking

## Phase 3 — Risk & Intelligence

### Risk Manager (`engine/risk_manager.py`)

Dynamically adjusts bet sizing based on performance and drawdown:

| Risk Level | Kelly Multiplier | Max Stake | Max Portfolio | Trigger |
|---|---|---|---|---|
| Aggressive | 0.65× | 6% | 25% | Win rate > 55%, drawdown < 3% |
| Normal | 0.50× | 5% | 20% | Default state |
| Cautious | 0.35× | 3% | 15% | Drawdown 10-20% |
| Defensive | 0.15× | 2% | 8% | Drawdown > 20% |

Additional protections:
- **Per-bookmaker exposure**: Max 40% of bankroll at any single book
- **Circuit breaker**: Halts all betting if bankroll drops below 25% of initial
- **Win/loss tracking**: Per-bookmaker P&L and win rate history

### CLV Tracker (`engine/clv_tracker.py`)

Measures Closing Line Value — the gold standard metric for sharp bettors:

```
CLV = Closing_Implied_Prob - Signal_Implied_Prob
```

Positive CLV means the line moved in our direction after we identified the edge, confirming we captured a real information inefficiency.

- **Bookmaker softness scoring**: Ranks bookmakers by how often they offer exploitable lines
- **Per-sport CLV tracking**: Identifies which sports our model adds the most alpha

### Humanizer (`engine/humanizer.py`)

Prevents sportsbook restrictions by making bet patterns look natural:

- **Stake noise**: ±5-15% randomization, rounded to natural amounts ($25, $50, $100, etc.)
- **Timing delays**: Log-normal distribution (30s–5min, peak ~2min)
- **Frequency limits**: Max 3 bets/day and 10 bets/week per bookmaker
- **Win streak cooloff**: Pauses at a bookmaker after 5 consecutive wins
- **Bookmaker rotation**: Ranks bookmakers by how safe they are to bet at right now

### InfoFi Line Scanner (`engine/line_movement.py`)

Monitors odds changes across all bookmakers to identify exploitable moments:

- **Steam moves**: >3% implied probability change in one snapshot (AlertPriority.HIGH)
- **Stale lines**: Bookmaker is >4% off the sharp (Pinnacle) line
- **Convergence**: Soft book gradually moving toward sharp price (AlertPriority.MEDIUM)
- **Market consensus**: Median implied probability across all books (vig-removed)
- **Movement velocity**: Rate of line change per minute for drift detection

### Updated Signal Pipeline Flow

```
SignalPipeline.analyze_event()
  ├─ Extract sharp probs (Pinnacle, remove vig)
  ├─ Ensemble blend (sharp + model + prior)
  ├─ Find edges against soft bookmakers
  ├─ Check for stale lines (InfoFi scanner)          ← NEW
  ├─ Risk Manager: dynamic Kelly multiplier           ← NEW
  │   ├─ Check risk level (drawdown-based)
  │   ├─ Check bookmaker exposure limits
  │   └─ Block bets if circuit breaker active
  ├─ Kelly sizing with risk-adjusted parameters
  ├─ Portfolio cap (risk-level-adjusted)
  ├─ Humanize bets (noise + timing + suppression)     ← NEW
  ├─ Record predictions for calibration
  └─ Record signals for CLV tracking                   ← NEW
```

## Adding a New Sport

1. Add the sport key to `config.py` → `supported_sports`
2. Add a new enum value to `models/events.py` → `SportType`
3. Add a SQL migration: `ALTER TYPE sport_type ADD VALUE 'new_sport_key';`
4. Create a mapping file: `entity_resolution/mappings/new_sport_teams.json`
5. Add the mapping key to `resolver.py` → `_mapping_key()`
6. Create a sport model in `engine/models/` (implement `simulate_*` function)
7. Wire the model into `signal_pipeline.py` to feed Monte Carlo probabilities

## Adding a New Bookmaker

Just add the bookmaker key to `config.py` → `target_bookmakers`. The system will auto-discover it on the next poll and create a `bookmakers` table entry.

## Testing

```bash
cd backend
python -m pytest tests/ -v           # all tests
python -m pytest tests/ -v -k fuzzy  # run specific tests
```

### Test Coverage by Module

| Module | Tests | Coverage |
|---|---|---|
| Normalizer | 16 | Event normalization, odds extraction, edge cases, error handling |
| Entity Resolver | 11 | Static matching, fuzzy matching, caching, dynamic additions |
| Scheduler | 7 | All tier boundaries, past events, no-event case |
| API Validation | 12 | Input sanitization, injection attempts, boundary values |
| Odds API Client | 4 | Quota tracking, error types |
| Edge Calculator | 13 | Edge formula, vig removal, find_edges across bookmakers |
| Monte Carlo Engine | 14 | Binary/scoring simulation, antithetic variates, stratified sampling |
| Kelly Criterion | 14 | Full/fractional Kelly, bet caps, portfolio sizing |
| Ensemble Scorer | 10 | Weight blending, normalization, disagreement |
| Calibration Tracker | 10 | Brier scores, prediction recording, outcome resolution |
| MLB Poisson Model | 10 | Expected runs, home field, pitcher ERA, simulation |
| UFC Elo Model | 7 | Elo probabilities, stat adjustments, probability clamping |
| Risk Manager | 18 | Risk levels, dynamic Kelly, drawdown, exposure, circuit breaker |
| CLV Tracker | 12 | CLV calculation, bookmaker profiles, softness scoring |
| Humanizer | 14 | Stake randomization, timing, frequency limits, win streak cooloff |
| Line Movement | 15 | Steam moves, convergence, stale lines, market consensus |
| Alert System | 12 | Webhook config, message formatting, edge filtering |
| **Total** | **219** | |

### What's NOT Tested (Known Gaps)

- **Integration tests** — Pipeline end-to-end with real DB (requires test DB setup)
- **Async tests** — `pipeline.run_cycle()`, `scheduler.start()` (requires async fixtures + mocks)
- **API endpoint tests** — Full HTTP request/response via `TestClient` (requires all dependencies running)
- **Signal pipeline integration** — `SignalPipeline.analyze_event()` with live odds data

## Phase 4 — Interface & Alerts

### Next.js Dashboard (`frontend/`)

Built with Next.js 16, TypeScript, and Tailwind CSS 4. Uses the App Router with server components for data fetching.

**Pages:**
- `/` (Dashboard) — Golden Plays signals table, risk state metrics (bankroll, drawdown, Kelly, exposure), calibration tracking (Brier scores), betting stats
- `/events` — Events browser with sport/status badges, commence times
- `/alerts` — CLV summary metrics, steam move alerts, convergence events, bookmaker softness ranking with progress bars

**Architecture:**
- `src/lib/types.ts` — TypeScript interfaces matching every Pydantic response model
- `src/lib/api.ts` — Typed fetch functions for all 11 API endpoints
- `src/components/` — Reusable UI: `Card`, `MetricBox`, `StatusBadge`, `Nav`
- Server-side rendering with `revalidate: 30` for fresh data every 30 seconds
- Dark theme using CSS custom properties
- Set `NEXT_PUBLIC_API_URL` to point to the backend (default: `http://localhost:8000`)

### Alert System (`engine/alerts.py`)

Sends real-time notifications via Discord webhooks and Telegram Bot API:

**Alert types:**
- `SIGNAL` — New +EV signal detected (configurable min edge, default 3%)
- `STEAM_MOVE` — High-priority line movement
- `RISK_CHANGE` — Risk level transition (e.g., normal → cautious)
- `DAILY_SUMMARY` — End-of-day recap with P&L, signals, calibration

**Setup:**
- Discord: Set `DISCORD_WEBHOOK_URL` in `.env` (get from Discord channel settings → Integrations → Webhooks)
- Telegram: Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

Both channels are fire-and-forget with error logging. The `AlertManager` uses `httpx.AsyncClient` for non-blocking sends.

## Security Measures

- **No secrets in code** — all credentials via `.env` (in `.gitignore`)
- **CORS restricted** — configurable allowed origins, GET-only
- **Input validation** — regex-based event ID and bookmaker key validation
- **Parameterized queries** — all SQL uses named parameters, never f-strings
- **Bounded responses** — all queries have LIMIT clauses
- **Typed responses** — Pydantic models enforce response structure
- **Enum validation** — sport and status filters use Python enums (rejects arbitrary input)
