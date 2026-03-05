# Developer Guide — Bet Buddy Phase 1

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
│   │   └── test_api_validation.py      # 16 tests — input validation + injection defense
│   ├── pytest.ini
│   └── requirements.txt
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

## Adding a New Sport

1. Add the sport key to `config.py` → `supported_sports`
2. Add a new enum value to `models/events.py` → `SportType`
3. Add a SQL migration: `ALTER TYPE sport_type ADD VALUE 'new_sport_key';`
4. Create a mapping file: `entity_resolution/mappings/new_sport_teams.json`
5. Add the mapping key to `resolver.py` → `_mapping_key()`

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
| API Validation | 16 | Input sanitization, injection attempts, boundary values |
| Odds API Client | 4 | Quota tracking, error types |
| **Total** | **54** | |

### What's NOT Tested (Phase 1 Known Gaps)

- **Integration tests** — Pipeline end-to-end with real DB (requires test DB setup)
- **Async tests** — `pipeline.run_cycle()`, `scheduler.start()` (requires async fixtures + mocks)
- **API endpoint tests** — Full HTTP request/response via `TestClient` (requires all dependencies running)

These will be addressed when we add the test infrastructure in Phase 2.

## Security Measures

- **No secrets in code** — all credentials via `.env` (in `.gitignore`)
- **CORS restricted** — configurable allowed origins, GET-only
- **Input validation** — regex-based event ID and bookmaker key validation
- **Parameterized queries** — all SQL uses named parameters, never f-strings
- **Bounded responses** — all queries have LIMIT clauses
- **Typed responses** — Pydantic models enforce response structure
- **Enum validation** — sport and status filters use Python enums (rejects arbitrary input)
