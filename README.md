# THNDR Smart Portfolio

A personal, cloud-deployable full-stack application for tracking and managing
an Egyptian stock market and investment fund portfolio — inspired
functionally by apps like Thndr, but an independent, standalone product.

> **Status:** Phase 1 — Repository & Architecture scaffolding. No backend
> logic, database models, or frontend UI exist yet. See [Phase Plan](#phase-plan)
> below.

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

Setup instructions will be added as each phase introduces runnable code
(Phase 2 onward). Nothing is runnable yet in Phase 1.

## License

Private, personal-use project. Not affiliated with or a copy of Thndr.
