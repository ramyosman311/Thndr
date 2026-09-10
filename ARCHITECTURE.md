# Architecture

## Status

This document describes the architecture of MIZAN Smart Portfolio Manager. The
backend (FastAPI, domain/service/repository layering) is implemented
through Phase 11; the frontend (Next.js) is implemented as of Phase 9,
extended for price states in Phase 11 — see "Frontend Layering" below
for what exists today. Real Telegram delivery was added in Phase 14 (see
"Workers" below). This document remains the contract later phases (PWA,
Capacitor, deployment) build against.

## High-Level Overview

```
┌─────────────────────┐        ┌──────────────────────────┐        ┌────────────────────┐
│   Next.js Frontend   │  HTTP  │      FastAPI Backend      │  SQL   │   PostgreSQL (DB)   │
│  (App Router, PWA)   │──────▶ │  api → services → domain  │──────▶ │   Supabase-hosted    │
│  Display only         │◀────── │  → repositories           │◀────── │   in production      │
└─────────────────────┘  JSON  └──────────────────────────┘        └────────────────────┘
                                          │
                                          ▼
                                ┌──────────────────────┐        ┌─────────────────┐
                                │  Workers (external-   │  HTTP  │  Telegram Bot   │
                                │  scheduler invoked):   │──────▶ │  API            │
                                │  price_refresh,        │        └─────────────────┘
                                │  alert_notify          │
                                └──────────────────────┘
```

Both workers share the same execution model: a standalone
`python -m app.workers.<name>` script, invoked periodically by an
external scheduler (cron, a platform's scheduled-job feature) — never
started by, or run inside, the FastAPI/Uvicorn process. Neither worker
exists as an in-repo scheduling loop; see DEPLOYMENT.md, "Workers".

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
   here once, instead of being duplicated across service modules. Phase
   11 adds `price_service.py` (the ONLY price read path for every
   request-time consumer — pure DB reads, never a provider call; also
   owns manual price submission) and `price_orchestrator.py` (the ONLY
   caller of a live `PriceProvider`, used exclusively by the background
   refresh worker). `portfolio_shared.py` gained
   `load_priced_positions`, so Portfolio/Strategy/Smart Inflow all price
   their positions through the identical Price-Service-backed call.
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
   introduces no second portfolio calculation path. Phase 11 adds four
   pure modules for the price infrastructure: `price_types.py` (the
   `PriceResult`/`PriceStatus` vocabulary every price read returns),
   `stale_policy.py` (asset-type-aware, weekend-hours-adjusted staleness
   classification — never one universal duration), `manual_precedence.py`
   (the single function deciding whether an automated observation may
   supersede a manual one), and `fx.py` (the one-line currency
   conversion multiplication, defined once rather than inlined per
   caller). None of these touch a database session or call a provider.
5. **`repositories/`** — Data access layer. All SQLAlchemy queries live
   here. Services depend on repository interfaces, not raw sessions,
   keeping persistence swappable and mockable in tests. Phase 11 adds
   `price_repository.py`: every query against `asset_price_configs`,
   `asset_prices`, and `fx_rates`.
6. **`models/`** — SQLAlchemy ORM models (the database schema in code).
7. **`providers/`** (Phase 11) — Live market-data adapters, used
   exclusively by `services/price_orchestrator.py`. `base.py` defines
   the `PriceProvider` Protocol (`get_price(provider_symbol) ->
   ProviderQuote`, or a typed `ProviderError` subclass) and the
   provider-agnostic failure taxonomy (timeout, HTTP error, malformed
   response, missing price, invalid timestamp); `yahoo_provider.py`
   implements it against Yahoo Finance's chart API; `registry.py` maps a
   provider-name string (as configured per-asset in
   `asset_price_configs`) to a provider instance. Manual pricing is
   deliberately NOT a `PriceProvider` — it is a push (a user submits a
   value), not a pull, so it is handled directly by
   `services/price_service.record_manual_price`. See "Price
   Infrastructure" below.
8. **`workers/`** — Background/scheduled jobs, run out-of-band from the
   FastAPI process (see DEPLOYMENT.md, "Workers"). Phase 11 adds
   `price_refresh.py` — `python -m app.workers.price_refresh` — the only
   entrypoint allowed to call `services/price_orchestrator.py`, which is
   in turn the only code allowed to call a live `PriceProvider`. Phase 14
   adds `alert_notify.py` — `python -m app.workers.alert_notify` — the
   only entrypoint that ever constructs a live-HTTP-capable
   `TelegramNotificationDispatcher`; the user-facing
   `POST /api/alerts/evaluate` route (Phase 8) still runs synchronously
   but always gets the safe `NullNotificationDispatcher` default, so an
   on-demand "check now" request from the Watchlist screen never depends
   on a live Telegram call. Both workers keep the non-blocking guarantee
   (see "Price Infrastructure" below) structural rather than a
   convention someone could accidentally violate from inside a request
   handler.
9. **`core/`** — Cross-cutting concerns: configuration (`config.py`),
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
  `transaction-history.tsx`, and Phase 11's `price-state.tsx`:
  `PriceStateBadge` — the current/last-known/unavailable/currency-
  unavailable visual states every price display uses — and
  `ManualPriceEditor`, the pencil-to-inline-form manual price entry
  affordance, which only ever calls `POST /api/assets/{id}/price/manual`
  and never touches a transaction) and the icon set (`icons.tsx`,
  hand-rolled to avoid an icon-library dependency) and navigation
  (`nav.tsx`: `BottomNav` for mobile, `TopNav` for desktop, same
  `NAV_ITEMS`).
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

- Manifest/icon metadata exists since Phase 9 (`manifest.ts`, `icon.tsx`).
  An installable-with-offline-shell PWA (service worker) is a distinct,
  not-yet-implemented future phase — Phase 11 was the price
  infrastructure described below, not PWA work; nothing here should be
  read as claiming a service worker exists yet.
- No Capacitor-specific APIs are used in core application code. Capacitor
  wrapping adds a thin native shell around the same web app; it is not
  required to run or install a future PWA.
- Local storage/cache, when a service worker is eventually added, must be
  used only for offline shell behavior and never treated as a source of
  truth — PostgreSQL remains authoritative, and stale cached data must be
  visibly indicated as such, not presented as live. (This principle
  already governs price data today — see "Price Infrastructure" below,
  "Never Silently Present Stale As Live".)

## Price Infrastructure (Phase 11)

Every asset price — for any current or future asset, not just the ones
seeded today — flows through one generic, provider-driven,
non-blocking pipeline. This section is the architectural summary; the
authoritative rules live in FINANCIAL_RULES.md (stale-price policy,
manual-vs-automated precedence, FX conversion, non-blocking valuation)
and DATABASE.md (`asset_price_configs`, `asset_prices`, `fx_rates`).

```
Background (out-of-band, app/workers/price_refresh.py):
  AssetPriceConfig ──▶ Price Orchestrator ──▶ PriceProvider (Yahoo, ...)
                              │                        │
                              │  (failure: try secondary, then give up)
                              ▼
                        asset_prices  (immutable observation history)
                              ▲
Request-time (every API read, always synchronous, never blocked):     │
  Portfolio / Allocation / P&L / Dashboard / Alerts ──▶ Price Service ─┘
                                                       (DB read only,
                                                        classifies
                                                        staleness,
                                                        never calls a
                                                        provider)
```

- **`PriceProvider` abstraction** (`app/providers/base.py`): a Protocol
  (`get_price(provider_symbol) -> ProviderQuote`, or a typed
  `ProviderError` subclass on failure). The core system never knows or
  cares how a provider fetches data — adding a new provider means
  implementing this Protocol and registering it in
  `app/providers/registry.py`; nothing else changes.
- **Price Orchestrator** (`services/price_orchestrator.py`): the ONLY
  code that ever calls a live provider. Generic primary → secondary →
  (nothing stored) fallback chain per asset; one asset's provider
  failure never stops the rest of the batch. Enforces manual-vs-
  automated precedence (domain/manual_precedence.py) before ever
  storing a fetched observation. Called exclusively by
  `app/workers/price_refresh.py`, run out-of-band by an external
  scheduler/process manager — never as an in-process loop inside the
  FastAPI server (see DEPLOYMENT.md, "Workers").
- **Price Service** (`services/price_service.py`): the ONLY price read
  path for every request-time consumer. Reads the latest `asset_prices`
  row (or the latest per asset, batched, for a whole portfolio),
  classifies it via `domain/stale_policy.py`, and converts into the
  portfolio's base currency via `domain/fx.py` + `fx_rates` when
  needed. **Never calls a provider** — this is what makes a
  `GET /api/portfolio/summary` request's latency and success
  independent of any provider's latency or an outage. Also owns manual
  price submission (`record_manual_price`), since that's a direct user
  write, not a provider fetch.
- **Price storage** (`asset_prices`): an append-only, immutable
  observation history — never updated or deleted. "Current price" is
  never stored redundantly anywhere else; `holdings.current_price`
  (pre-Phase-11 column) is no longer read or written by any code path —
  see FINANCIAL_RULES.md, "Single Source Of Truth For Current Price".
- **FX** (`fx_rates`, `domain/fx.py`): a separate, generic
  currency-pair observation domain, using the exact same
  provider/storage/staleness shape as asset prices, not a special-cased
  USD/EGP path. A valuation across a currency mismatch with no FX rate
  on record reports `CURRENCY_CONVERSION_UNAVAILABLE`, never a
  fabricated or assumed 1:1 rate.

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

## Domain Readiness & Administration (Phase 12)

Phase 12 added no new tables and no new domain engines. It did two
things: (1) a full read-only audit of the existing schema/services/routes
for accidental single-portfolio or single-user assumptions, and (2) a
safe administration layer (CRUD + activate/deactivate, never destructive
where history exists) over Asset, Asset Price Config, Portfolio Config,
Strategy Bucket, and Allocation Target — so these can be managed through
the app instead of direct DB writes. The full audit findings, including
exactly which single-portfolio assumptions were found, fixed, and
deliberately deferred, are recorded in
[DECISIONS.md](./DECISIONS.md) rather than duplicated here.

Ownership boundaries introduced by the new admin services mirror the
read/write split already established for prices in Phase 11:

- `price_config_service.py` (config CRUD only) vs. `price_service.py`
  (Phase 11, request-time reads) vs. `price_orchestrator.py` (Phase 11,
  background fetch) — three services, three jobs, none overlapping.
- `portfolio_config_service.py` (config CRUD only) vs. `portfolio_
  service.py` (Phase 5, read-only valuation, unchanged).
- `strategy_admin_service.py` (bucket/target CRUD, per-row validation
  only) vs. `strategy_service.py` (Phase 6, read-only, owns the
  aggregate "does this add up to 100%" validation exclusively). Saving
  an incomplete or partial strategy configuration is allowed by design —
  see FINANCIAL_RULES.md, "Strategy Validation Ownership".

None of the three new admin services ever calls a `PriceProvider`, ever
computes a valuation, or ever re-implements a rule the domain layer
already owns; they only validate their own row-level invariants (the
same ones already enforced by CHECK/UNIQUE constraints) and persist.

## Related Documents

- [DATABASE.md](./DATABASE.md) — schema design
- [API.md](./API.md) — REST surface
- [FINANCIAL_RULES.md](./FINANCIAL_RULES.md) — domain rules and assumptions
- [DEPLOYMENT.md](./DEPLOYMENT.md) — deployment topology
- [DECISIONS.md](./DECISIONS.md) — architectural decision log (domain readiness audit, Phase 12)
