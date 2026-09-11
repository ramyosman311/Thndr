# MIZAN Smart Portfolio Manager

A personal, cloud-deployable full-stack application for tracking and managing
an Egyptian stock market and investment fund portfolio — inspired
functionally by apps like Thndr, but an independent, standalone product.

> **Status:** Phase 16 — Financial Core & Cash Logic (P0). A confirmed
> bug is fixed: the dashboard previously labeled `investable_value`
> (total value minus emergency value — an allocation-percentage
> denominator that INCLUDES invested market value) as "Investable Cash,"
> so a user holding only stocks could see a large nonzero "cash" figure
> with none actually available. `GET /api/portfolio/summary` now exposes
> a genuinely separate `available_cash` (non-emergency CASH/SAVINGS
> holdings only — the real spendable-cash figure) and
> `invested_market_value`, alongside the unchanged `total_value`/
> `emergency_value`/`investable_value`. A held asset with no live price
> now falls back to a real stale price or its own same-currency average
> cost (`services/portfolio_shared.resolve_valuation_price`) instead of
> being silently excluded, exposed via a simple `price_status`:
> `"LIVE"`/`"PENDING_SYNC"` — `unrealized_pnl` is always exactly 0 when
> not live, never a fabricated profit. The frontend shows quantities/
> prices with sane precision (no more `50.00000000`), P/L with an
> explicit arrow and direction wording rather than color alone, and
> transactions strictly newest-first. BUY/SELL were confirmed to have no
> automatic link to `available_cash` (only DEPOSIT/WITHDRAWAL move it) —
> a disclosed, pre-existing scope boundary, not a new limitation — see
> [DECISIONS.md](./DECISIONS.md), "Phase 16 — Financial Core & Cash
> Logic" for the full design rationale and open scope question. No
> database/migration change was needed. `TRANSFER` transaction semantics
> and an Egypt-local EOD boundary remain unimplemented (Phase 15,
> disclosed). No broker integration, automatic trading, authentication,
> or full multi-user/multi-portfolio system exist yet. See
> [Phase Plan](#phase-plan) below.

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
mizan-smart-portfolio/
├── README.md
├── ARCHITECTURE.md
├── DATABASE.md
├── API.md
├── FINANCIAL_RULES.md
├── DEPLOYMENT.md
├── DECISIONS.md                (added in Phase 12)
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
4. **No fabricated data.** Every price flows through an explicit
   `PriceProvider` abstraction (Phase 11) — Yahoo Finance where
   supported, a first-class manual entry path otherwise. An asset class
   with no genuinely available/documented provider (EGX, generic fund
   NAV) is left unconfigured rather than backed by an invented endpoint
   or fabricated data; a price that cannot currently be determined is
   reported as unavailable, never guessed or shown as zero.
5. **Incremental, verified delivery.** Every phase is implemented, run,
   tested, and documented before moving to the next. See the Phase Plan.

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system architecture, layering, auth boundary
- [DATABASE.md](./DATABASE.md) — entity design and schema rationale
- [API.md](./API.md) — REST API surface and conventions
- [FINANCIAL_RULES.md](./FINANCIAL_RULES.md) — financial assumptions and domain rules
- [DEPLOYMENT.md](./DEPLOYMENT.md) — Docker, Supabase, and cloud deployment notes
- [DECISIONS.md](./DECISIONS.md) — architectural decision log (domain readiness audit, single-portfolio assumptions, deferred multi-portfolio work)

## Phase Plan

Development proceeds in verified phases; each phase stops for approval
before the next begins.

1. Repository + Architecture — done
2. Backend Foundation (FastAPI, DB connection, Docker, `/api/health`) — done
3. Database Models + Migrations — done
4. Seed Data — done
5. Portfolio Engine (value, P/L, allocation) — done
6. Strategy Engine (dynamic targets) — done
7. Smart Inflow Allocator — done
8. Watchlist + Alerts — done
9. Next.js Frontend (Portfolio Dashboard, mobile-first, RTL, dark mode) — done
10. Transaction & Holdings Engine (BUY/SELL, average-cost accounting) — done
11. Generic Hybrid Price Infrastructure (provider-driven prices, FX, non-blocking valuation) — done
12. Portfolio & Asset Administration + Domain Readiness (Settings UI for Assets/Pricing/Portfolio/Strategy, single-portfolio assumption audit) — done
13. EGX Market Data Provider Integration & Verification (EGID/EGXAPI investigated and rejected; Mubasher Egypt implemented as primary, mock-tested, with Yahoo Finance retained as secondary fallback for the real EGX equities) — done
14. Telegram Notifications (real delivery, out-of-band worker, strict AND-gated enablement, mock-tested) — done
15. Historical Snapshots & Wealth Analytics Engine (DEPOSIT/WITHDRAWAL cash-flow semantics, EOD + post-transaction snapshot lifecycle, Time-Weighted Return isolating market performance from cash flow, real snapshot-driven dashboard chart with 1W/1M/3M/YTD/ALL ranges) — done
16. Financial Core & Cash Logic, P0 (separated Portfolio Value / Investable Value / Available Cash / Reserved Cash so a stock-only holding can never show as spendable cash; missing-price fallback to a stale price or same-currency average cost, exposed as a simple LIVE/PENDING_SYNC signal with unrealized P/L always 0 when not live; user-facing quantity/currency formatting; accessible P/L presentation with explicit arrow + direction wording, not color alone; deterministic newest-first transaction ordering) — done *(current)*
17. PWA (installable, offline-capable)
18. Capacitor wrappers
19. Production deployment prep
20. Full multi-portfolio support (deferred from Phase 12 — see [DECISIONS.md](./DECISIONS.md))
21. A verified EGID or EGXAPI adapter, or another zero-cost EGX-specific data source (deferred from Phase 13 — see [DECISIONS.md](./DECISIONS.md), requires network access and human-obtained API documentation this environment could not get)
22. Live Telegram verification (deferred from Phase 14 — see [DECISIONS.md](./DECISIONS.md), `api.telegram.org` confirmed blocked by this environment's egress policy) and a "send test message" admin action (explicitly deferred by Phase 14's own approval)
23. TRANSFER transaction semantics, Egypt-local (Africa/Cairo) EOD trading-day boundary, and analytics coverage for pre-Phase-15 snapshot history (deferred from Phase 15 — see [DECISIONS.md](./DECISIONS.md))
24. A fully-integrated cash ledger where BUY/SELL automatically debit/credit a cash balance (Phase 16 confirmed no such link exists or was ever approved — see [DECISIONS.md](./DECISIONS.md), "Phase 16 — Financial Core & Cash Logic"; only an explicit DEPOSIT/WITHDRAWAL moves `available_cash` today)

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

### Frontend

**Prerequisites:** Node.js 22+, and the backend running locally (see
above) — the frontend is a pure API client and has nothing to render
without it.

**1. Install dependencies**

```bash
cd frontend
npm install
```

**2. Configure environment**

```bash
cp ../.env.example .env.local
# NEXT_PUBLIC_API_BASE_URL defaults to http://localhost:8000/api, matching the backend above
```

**3. Run the dev server**

```bash
npm run dev
```

Then open `http://localhost:3000` — Dashboard, Portfolio, Allocation/
Strategy, Smart Inflow, Watchlist + Alerts, and a Settings placeholder,
fully RTL/Arabic with light/dark mode (`next-themes`, respects the system
preference by default).

**4. Run tests**

```bash
cd frontend
npm test
```

Vitest + Testing Library, run in isolation with the API client mocked
per-test (no network calls) — component rendering, loading/error/empty
states, and interaction flows (add/remove a watchlist entry, submit the
Smart Inflow form, evaluate alerts) are covered without needing a live
backend.

**5. Production build**

```bash
cd frontend
npm run build
```

Uses Next.js 16 (App Router, Turbopack). `npm run lint` runs ESLint
separately.

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

### Required Environment Variables

See `.env.example` for the full list. Backend variables: `APP_ENV`,
`APP_DEBUG`, `DEV_MODE`, `BACKEND_HOST`, `BACKEND_PORT`,
`BACKEND_CORS_ORIGINS`, `DATABASE_URL`, `DATABASE_URL_SYNC`, `SECRET_KEY`.
Frontend: `NEXT_PUBLIC_API_BASE_URL` (Phase 9 — read by `frontend/lib/api.ts`).
Telegram/market-data/Supabase variables remain placeholders for later
phases and are not read by any code yet.

## License

Private, personal-use project. Not affiliated with or a copy of Thndr.
