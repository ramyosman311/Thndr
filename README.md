# THNDR Smart Portfolio

A personal, cloud-deployable full-stack application for tracking and managing
an Egyptian stock market and investment fund portfolio — inspired
functionally by apps like Thndr, but an independent, standalone product.

> **Status:** Phase 4 — Idempotent development seed data (initial assets,
> strategy buckets, portfolio configuration, allocation targets, and five
> historical portfolio snapshots). No financial engine or frontend UI
> exist yet. See [Phase Plan](#phase-plan) below.

## What this project does (target scope)

- Track stocks, investment funds, gold, and cash holdings
- Record buy/sell transactions and compute average cost basis
- Calculate current value, profit/loss, and return %
- Track portfolio allocation against configurable targets
- Distinguish **Target Allocation**, **Maximum Allocation**, and **Allow New Buy**
  as independent, database-driven settings (never hardcoded — see
  [FINANCIAL_RULES.md](./FINANCIAL_RULES.md))
- Smart Rebalancing recommendations (never auto-executes trades)
- Smart Cash Inflow Allocation (recommends where new cash should go)
- Watchlist with price/allocation/dip-buy alerts
- Telegram notifications
- Portfolio history via daily snapshots
- Installable PWA, with an architecture ready for a future Capacitor wrapper

## Tech Stack

| Layer      | Technology |
|------------|------------|
| Frontend   | Next.js (App Router), TypeScript, Tailwind CSS, React, PWA |
| Backend    | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic |
| Database   | PostgreSQL (Supabase in production) |
| Testing    | pytest, httpx |
| Packaging  | Docker, docker-compose |
| Mobile     | Capacitor (future iOS/Android wrapper, not required to run the PWA) |

## Repository Structure

```
thndr-smart-portfolio/
├── README.md
├── ARCHITECTURE.md
├── DATABASE.md
├── API.md
├── FINANCIAL_RULES.md
├── DEPLOYMENT.md
├── .gitignore
├── .env.example
├── docker-compose.yml          (added in a later phase)
│
├── backend/
│   ├── Dockerfile              (added in Phase 2)
│   ├── requirements.txt        (added in Phase 2)
│   ├── alembic.ini             (added in Phase 2)
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── core/
│       ├── models/
│       ├── schemas/
│       ├── api/
│       ├── services/
│       ├── domain/
│       ├── repositories/
│       ├── workers/
│       └── tests/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── lib/
│   ├── types/
│   └── public/
│
├── mobile/
│   └── capacitor/
│
└── docs/
```

## Core Principles

1. **Database is the source of truth.** No allocation percentages, asset
   limits, or investment rules are hardcoded in business logic. See
   [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).
2. **Separation of concerns.** Financial calculations live in the backend
   domain layer, never inside React components. See
   [ARCHITECTURE.md](./ARCHITECTURE.md).
3. **The system recommends, it does not execute.** Rebalancing and inflow
   allocation produce recommendations only — no automated trading.
4. **No fabricated data.** Market data comes from an explicit provider
   abstraction; when no real provider is configured, a `MockMarketDataProvider`
   is used and clearly labeled as mock — never presented as real.
5. **Incremental, verified delivery.** Every phase is implemented, run,
   tested, and documented before moving to the next. See the Phase Plan.

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system architecture, layering, auth boundary
- [DATABASE.md](./DATABASE.md) — entity design and schema rationale
- [API.md](./API.md) — REST API surface and conventions
- [FINANCIAL_RULES.md](./FINANCIAL_RULES.md) — financial assumptions and domain rules
- [DEPLOYMENT.md](./DEPLOYMENT.md) — Docker, Supabase, and cloud deployment notes

## Phase Plan

Development proceeds in verified phases; each phase stops for approval
before the next begins.

1. Repository + Architecture *(current)*
2. Backend Foundation (FastAPI, DB connection, Docker, `/api/health`)
3. Database Models + Migrations
4. Seed Data
5. Portfolio Engine (value, P/L, allocation)
6. Strategy Engine (dynamic targets)
7. Smart Inflow Allocator
8. Watchlist + Alerts
9. Telegram Notifications
10. Next.js Frontend
11. PWA
12. Capacitor wrappers
13. Production deployment prep

## Local Development

### Backend

**Prerequisites:** Python 3.12+ (3.11 also works for local dev; the Docker
image pins 3.12), and a running PostgreSQL instance (local, dockerized, or
Supabase).

**1. Install dependencies**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp ../.env.example .env
# edit .env: set DATABASE_URL / DATABASE_URL_SYNC to a real PostgreSQL instance
```

**3. Run the backend**

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then check:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","database":"connected"}
```

`status` reflects application liveness (stable for hosting health checks).
`database` is diagnostic ("connected" or "unavailable") and does not flip
the overall status to an error.

**4. Run tests**

```bash
cd backend
source .venv/bin/activate
python -m pytest -v
```

Tests run against a real PostgreSQL connection (configured via `.env`) —
no mocked database layer. The model tests (`app/tests/test_models.py`) use
a separate `_test`-suffixed database and apply the real Alembic migration
chain automatically before running; create that database once (e.g.
`createdb <dbname>_test`) alongside your main database.

**5. Database migrations (Alembic)**

```bash
cd backend
source .venv/bin/activate
alembic current   # show current DB revision
alembic check     # compare models vs. latest migration
alembic upgrade head
```

**6. Development seed data**

```bash
cd backend
source .venv/bin/activate
python -m app.seed
```

Seeds the initial development portfolio: 7 assets, 6 strategy buckets, 1
portfolio configuration (Cloudz as the emergency asset), 5 allocation
targets, and 5 historical snapshots (35 snapshot items). Safe to run
repeatedly — it is fully idempotent (create-if-missing, keyed on stable
identifiers like asset symbol and snapshot timestamp), never creates
duplicates, and creates no transaction records. This is **development seed
data only** — never run as part of a migration, and never a source of
truth for production data. See `backend/app/seed/data.py` for the exact
values and `DATABASE.md` for the allocation rationale.

### Docker

From the repository root:

```bash
docker compose up --build
```

This starts PostgreSQL and the backend together. The backend Dockerfile
uses `python:3.12-slim`, runs as a non-root user, and exposes a container
`HEALTHCHECK` against `/api/health`.

> **Note:** building the image requires pulling `python:3.12-slim` from
> Docker Hub. In network-restricted environments (e.g. this session's
> sandboxed egress policy) that pull may be blocked — see
> [DEPLOYMENT.md](./DEPLOYMENT.md) for details. The Dockerfile itself is
> unaffected and builds normally wherever Docker Hub is reachable.

### Required Environment Variables (Phase 2)

See `.env.example` for the full list. Backend-relevant variables at this
phase: `APP_ENV`, `APP_DEBUG`, `DEV_MODE`, `BACKEND_HOST`, `BACKEND_PORT`,
`BACKEND_CORS_ORIGINS`, `DATABASE_URL`, `DATABASE_URL_SYNC`, `SECRET_KEY`.
Telegram/market-data/Supabase/frontend variables are placeholders for later
phases and are not read by any code yet.

## License

Private, personal-use project. Not affiliated with or a copy of Thndr.
