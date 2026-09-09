# Architecture

## Status

This document describes the intended architecture of THNDR Smart Portfolio.
As of Phase 1, only the repository structure exists — no backend or frontend
code has been implemented yet. This document is the contract that later
phases build against.

## High-Level Overview

```
┌─────────────────────┐        ┌──────────────────────────┐        ┌────────────────────┐
│   Next.js Frontend   │  HTTP  │      FastAPI Backend      │  SQL   │   PostgreSQL (DB)   │
│  (App Router, PWA)   │──────▶ │  api → services → domain  │──────▶ │   Supabase-hosted    │
│  Display only         │◀────── │  → repositories           │◀────── │   in production      │
└─────────────────────┘  JSON  └──────────────────────────┘        └────────────────────┘
                                          │
                                          ▼
                                ┌──────────────────────┐
                                │  Workers / Watchdog   │
                                │  (alerts, Telegram)   │
                                └──────────────────────┘
```

## Backend Layering

The backend follows strict separation of concerns, from outer to inner layers:

1. **`api/`** — FastAPI routers. Parse requests, validate with Pydantic
   schemas, call services, return responses. No business logic here.
2. **`schemas/`** — Pydantic models defining the public API contract.
   SQLAlchemy models are never exposed directly as API responses.
3. **`services/`** — Application/orchestration layer. Coordinates
   repositories and domain logic to fulfill a use case (e.g. "record a
   transaction and update the holding").
4. **`domain/`** — Pure financial/business logic: portfolio valuation, cost
   basis, allocation, rebalancing, smart inflow allocation. **No I/O.** No
   database session, no HTTP, no framework imports. This layer is
   independently unit-testable and free of side effects.
   Implemented as of Phase 5: `portfolio_engine.py` (total/emergency/
   investable value), `allocation_engine.py` (actual % vs. target/minimum/
   maximum/allow_new_buy, reporting only — never sells or buys),
   `pnl_engine.py` (basic unrealized P/L per holding), and
   `snapshot_comparison.py` (a plain value-change utility between two
   snapshot totals — explicitly not P/L or investment return).
5. **`repositories/`** — Data access layer. All SQLAlchemy queries live
   here. Services depend on repository interfaces, not raw sessions,
   keeping persistence swappable and mockable in tests.
6. **`models/`** — SQLAlchemy ORM models (the database schema in code).
7. **`workers/`** — Background/scheduled jobs: alert evaluation (watchdog),
   Telegram delivery, future snapshot generation.
8. **`core/`** — Cross-cutting concerns: configuration (`config.py`),
   database engine/session setup (`database.py`), and security utilities
   (`security.py`).

**Hard rule:** financial calculations (portfolio value, P/L, allocation
deviation, rebalancing, smart inflow) live only in `domain/`. They must be
callable and testable without a running database or HTTP server.

## Frontend Layering

The Next.js frontend is a **display and interaction layer only**:

- `app/` — App Router routes/pages (RTL, Arabic, dark mode by default).
- `components/` — Reusable presentational UI components.
- `features/` — Feature-scoped UI modules (dashboard, portfolio, allocation,
  watchlist, journal, settings) composed from `components/`.
- `hooks/` — Data-fetching and UI state hooks. Hooks call the backend API;
  they do not recompute financial figures the backend already returns.
- `lib/` — API client, formatting utilities (currency, percentages, dates).
- `types/` — TypeScript types mirroring backend API schemas.

**Hard rule:** no P/L, allocation, or rebalancing math is computed in React.
The frontend renders numbers the backend has already calculated.

## Why This Layering Matters

- Financial correctness is testable once, in one place (`domain/`), instead
  of being re-verified across every UI surface that happens to display it.
- The domain layer can be reused unchanged by workers (e.g. the alert
  watchdog needs the same allocation math the dashboard displays).
- The frontend can be replaced or wrapped (Capacitor, a future native app)
  without touching business logic.

## Authentication Boundary

The initial version is **single-user**, and for local development a
`DEV_MODE` flag (see `.env.example`) may bypass authentication entirely.

This is a deliberate, documented boundary, not an oversight:

- No production deployment should run with `DEV_MODE=true`.
- The database schema and service layer are designed so a `users` table and
  per-request auth (e.g. Supabase Auth or JWT-based auth) can be introduced
  later **without restructuring existing tables** — see "Future Database
  Tables" in [DATABASE.md](./DATABASE.md).
- Until real authentication exists, the API must not be exposed on an
  unauthenticated public endpoint in production; it should sit behind
  network-level protection (private network, VPN, or a reverse proxy with
  basic auth) as an interim measure. This is documented here so the gap is
  explicit rather than silently assumed away.

## PWA and Capacitor Readiness

- The frontend is built as a standard installable PWA (manifest, service
  worker, icons) — added in Phase 11.
- No Capacitor-specific APIs are used in core application code. Capacitor
  wrapping (Phase 12) adds a thin native shell around the same web app; it
  is not required to run or install the PWA.
- Local storage/cache is used only for offline shell behavior and must
  never be treated as a source of truth — PostgreSQL remains authoritative,
  and stale cached data must be visibly indicated as such, not presented as
  live.

## Market Data Abstraction

All prices flow through a `MarketDataProvider` interface
(`get_quote`, `get_quotes`, `get_gold_price`). Until a real provider is
configured, a `MockMarketDataProvider` is used and is explicitly labeled as
mock throughout the system (logs, and — where surfaced — the API/UI). Mock
data is never presented to the user as real market data.

## Recommendation, Not Execution

The Rebalancing Engine and Smart Inflow Allocator only ever produce
recommendations (asset, amount, reason). Neither engine — nor any other part
of the system — places trades or moves money automatically.

## Related Documents

- [DATABASE.md](./DATABASE.md) — schema design
- [API.md](./API.md) — REST surface
- [FINANCIAL_RULES.md](./FINANCIAL_RULES.md) — domain rules and assumptions
- [DEPLOYMENT.md](./DEPLOYMENT.md) — deployment topology
