# Architecture

## Status

This document describes the architecture of THNDR Smart Portfolio. The
backend (FastAPI, domain/service/repository layering) is implemented
through Phase 8; the frontend (Next.js) is implemented as of Phase 9 — see
"Frontend Layering" below for what exists today. This document remains the
contract later phases (PWA, Capacitor, deployment) build against.

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
   transaction and update the holding"). Also holds `portfolio_shared.py`
   (Phase 7): the emergency-bucket lookup and position-building helpers
   used by the Portfolio, Strategy, and Smart Inflow services all live
   here once, instead of being duplicated across service modules.
4. **`domain/`** — Pure financial/business logic: portfolio valuation, cost
   basis, allocation, rebalancing, smart inflow allocation. **No I/O.** No
   database session, no HTTP, no framework imports. This layer is
   independently unit-testable and free of side effects.
   Implemented as of Phase 5: `portfolio_engine.py` (total/emergency/
   investable value), `allocation_engine.py` (actual % vs. target/minimum/
   maximum/allow_new_buy, reporting only — never sells or buys),
   `pnl_engine.py` (basic unrealized P/L per holding), and
   `snapshot_comparison.py` (a plain value-change utility between two
   snapshot totals — explicitly not P/L or investment return). Phase 6
   adds `strategy_validation.py`: validates the aggregate configured
   target allocation (only `target_percent` values are summed; a
   maximum-only rule never contributes) and reports a machine-readable
   status — it never rewrites a percentage to force validity. Phase 7
   adds `inflow_allocator.py`: recommends where new cash should go among
   eligible buckets (target gap, capped by any maximum, ordered by
   priority) — a recommendation engine only, never a rebalancer; it never
   sells and never invents a destination for unallocated cash. Phase 8
   adds `alert_engine.py`: evaluates Watchlist + Alert Rule conditions
   (allocation breach, price target, dip buy, rebalance suggestion,
   income maturity) against explicit inputs, reusing the Allocation
   Engine's own output for allocation-related checks rather than
   recomputing it — reports triggers only, never places a trade. Phase 10
   adds `transaction_engine.py`: pure BUY/SELL average-cost math
   (`apply_buy`/`apply_sell`) that turns a transaction into the next
   `holdings` state — quantity, average cost, and (for SELL only) an
   immediate realized P/L. This is the only place `holdings.quantity`/
   `average_cost` are ever computed; once written, the existing Phase 5
   Portfolio/P/L/Allocation Engines read the result unchanged — Phase 10
   introduces no second portfolio calculation path.
5. **`repositories/`** — Data access layer. All SQLAlchemy queries live
   here. Services depend on repository interfaces, not raw sessions,
   keeping persistence swappable and mockable in tests.
6. **`models/`** — SQLAlchemy ORM models (the database schema in code).
7. **`workers/`** — Background/scheduled jobs: alert evaluation (watchdog),
   Telegram delivery, future snapshot generation. Not implemented yet —
   Phase 8 evaluates alerts synchronously via
   `POST /api/alerts/evaluate` and defines only the delivery interface
   (`services/notification_dispatcher.py`'s `NotificationDispatcher`
   Protocol, with a no-op `NullNotificationDispatcher` default) a future
   scheduled worker or Telegram integration would implement, without
   coupling alert evaluation to either.
8. **`core/`** — Cross-cutting concerns: configuration (`config.py`),
   database engine/session setup (`database.py`), and security utilities
   (`security.py`).

**Hard rule:** financial calculations (portfolio value, P/L, allocation
deviation, rebalancing, smart inflow) live only in `domain/`. They must be
callable and testable without a running database or HTTP server.

## Frontend Layering

The Next.js frontend is a **display and interaction layer only**. Implemented
as of Phase 9 (Next.js 16, App Router, TypeScript, Tailwind CSS v4, Cairo
font, full RTL, class-based dark mode via `next-themes`):

- `app/` — App Router routes/pages: `/` (Dashboard), `/portfolio` (holdings +
  P/L detail), `/allocation` (per-bucket allocation + strategy validation
  detail), `/inflow` (Smart Inflow Allocator workflow), `/watchlist`
  (Watchlist + Alerts CRUD and on-demand evaluation), `/settings`
  (explicit placeholder — no backend capability yet). Phase 10 upgrades
  `/portfolio` with a transaction entry form (BUY/SELL, asset picker
  reusing `GET /api/assets`, quantity/price/fees/date/notes, an explicit
  review-then-confirm step, and a clear "records an executed transaction,
  not a recommendation" label) and a read-only transaction history list —
  see `components/portfolio/`. Root `layout.tsx`
  sets `lang="ar" dir="rtl"`, loads the Cairo font, and renders the shared
  header/nav shell. `manifest.ts`/`icon.tsx` provide PWA-ready metadata
  (installable-ready; the offline service worker itself is Phase 11).
- `components/` — Reusable presentational UI (`ui/` primitives: card,
  status pill, metric card, query-boundary loading/error/empty states)
  plus per-screen component groups (`dashboard.tsx`, `allocation.tsx`,
  `watchlist/`, `portfolio/` — Phase 10's `transaction-form.tsx` and
  `transaction-history.tsx`) and the icon set (`icons.tsx`, hand-rolled to
  avoid an icon-library dependency) and navigation (`nav.tsx`: `BottomNav`
  for mobile, `TopNav` for desktop, same `NAV_ITEMS`).
- `hooks/` — `use-api-query.ts`: a minimal fetch-on-mount/refetch hook
  used by every screen instead of a state-management library. Hooks call
  the backend API; they do not recompute financial figures the backend
  already returns.
- `lib/` — `api.ts` (the single typed API client — no component calls
  `fetch()` directly), `format.ts` (Decimal-string presentation
  formatting: thousands grouping, currency/percent suffixes — never
  round-trips a value through a binary float), `status-labels.ts`
  (Arabic label + color tone per backend-defined status string — pure
  translation/presentation, never a new or reinterpreted status).
- `types/api.ts` — TypeScript types mirroring every backend Pydantic
  schema field-for-field, including `DecimalStr` (a Decimal serialized as
  a string) to keep the "never treat a financial value as a float" rule
  visible in the type system itself.

**Hard rule:** no P/L, allocation, or rebalancing math is computed in React.
The frontend renders numbers the backend has already calculated. Where a
Phase 9 screen needed a genuinely missing backend capability (a portfolio-
level P/L aggregate for the dashboard header; a way to list assets for the
Watchlist "add" picker), the addition was made as a minimal, clean backend
endpoint/field — see FINANCIAL_RULES.md ("Portfolio-Level P/L
Aggregation") and API.md ("Assets") — never as client-side financial logic.

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

The Rebalancing Engine, Smart Inflow Allocator, and Alert Engine (its
`REBALANCE_SUGGESTED` check) only ever produce recommendations/alerts
(asset, amount or condition, reason). None of them ever place a trade or
move money automatically, and none of them ever calls
`POST /api/transactions` on the user's behalf.

`POST /api/transactions` (Phase 10) is the deliberate, explicit exception:
it exists specifically so a *user* can record a trade they already
executed elsewhere (a real brokerage, in practice). This is manual data
entry of a real-world event, never automated trading — the system still
never decides to buy or sell anything, and no recommendation engine's
output is ever wired to it automatically.

## Related Documents

- [DATABASE.md](./DATABASE.md) — schema design
- [API.md](./API.md) — REST surface
- [FINANCIAL_RULES.md](./FINANCIAL_RULES.md) — domain rules and assumptions
- [DEPLOYMENT.md](./DEPLOYMENT.md) — deployment topology
