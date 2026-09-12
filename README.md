# MIZAN Smart Portfolio Manager

A personal, cloud-deployable full-stack application for tracking and managing
an Egyptian stock market and investment fund portfolio — inspired
functionally by apps like Thndr, but an independent, standalone product.

> **Status:** Phase 23.5 — Production Provisioning. A real deployment
> attempt was made against all four target providers named in the
> intended architecture — Vercel (web/PWA), Render/Railway (FastAPI
> backend), and Supabase (PostgreSQL) — from this session's own network,
> not merely assumed unreachable. Every one of `api.vercel.com`,
> `api.render.com`, `backboard.railway.app`, and `api.supabase.com` was
> denied at the egress-proxy layer with an explicit `403` policy
> rejection, logged by the proxy itself at the same moment for all four
> hosts — the same category of restriction already documented for
> `docker.io` (Phase 2) and `dl.google.com` (Phase 22). No credentials
> for any of these providers exist in this environment either, so even
> unblocked network access would not have been enough on its own.
> **No durable external deployment exists as a result** — there is no
> production API URL, no production database, and no production web
> deployment. Nothing in the repository or its configuration is the
> cause; every piece of Phase 23's preparation was re-verified fresh in
> this session instead (full backend and frontend test suites, a
> migration run against a brand-new empty database, both production
> build modes, Capacitor sync and its structural tests, and a full
> security scan — all green). See [DEPLOYMENT.md](./DEPLOYMENT.md),
> "Production Provisioning Attempt Log" for the exact evidence, and
> [DECISIONS.md](./DECISIONS.md), "Phase 23.5 — Production Provisioning"
> for the full rationale and exactly what a human with real cloud
> credentials would need to do from here to reach a genuinely live,
> verified deployment.
>
> Phase 23 — Production Infrastructure & Deployment
> Readiness. This phase makes the existing FastAPI/PostgreSQL/Next.js/
> Capacitor architecture (Phases 2–22) production-ready as
> infrastructure, without changing any financial logic. Backend: the
> Docker image now binds to a platform-injected `$PORT` (previously
> hardcoded to 8000), runs as a non-root user with only runtime
> dependencies (`requirements.txt`; `pytest`/`pytest-asyncio` moved to
> `requirements-dev.txt`), and gained a connection-pool `pool_recycle`
> setting so a managed Postgres's own idle-connection timeout can't
> silently drop connections. `GET /api/health/ready` is new — a true
> readiness probe (503 when the database is unreachable) distinct from
> the unchanged `GET /api/health` liveness check, which still never
> flips to an error state on a database hiccup. Every process (the API
> and all three workers) now shares one structured log format via
> `app/core/logging_config.py`, audited to confirm no secret is ever
> logged. `python -m app.seed` refuses to run against
> `APP_ENV=production` unless explicitly overridden — not because the
> seed is destructive (it never deletes anything), but because it would
> otherwise inject fake demo assets into a real portfolio. `.env.example`
> had two vestigial, never-read variables removed
> (`MARKET_DATA_PROVIDER`/`MARKET_DATA_API_KEY`) and gained explicit
> production-vs-development guidance for every remaining variable,
> including exactly which origins `BACKEND_CORS_ORIGINS` needs in
> production (the web origin plus the Capacitor app's `https://localhost`
> WebView origin) and exactly what `NEXT_PUBLIC_API_BASE_URL` must be for
> a Capacitor build (an explicit, durable HTTPS URL — the existing Phase
> 22 build-time guard rejecting a missing/insecure/Codespace-preview URL
> was re-verified with real build attempts, not just re-read). A new
> `.github/workflows/ci.yml` runs the full backend and frontend test
> suites on every push/PR — no deployment step, no secrets required.
> Migrations were verified end-to-end against a brand-new, completely
> empty PostgreSQL database (all 5 migrations applied cleanly, `alembic
> check` clean afterward) — the strongest verification available without
> a real target platform. **No durable external deployment exists**:
> this sandboxed environment has no Render/Railway/Supabase/Vercel
> credentials, so provisioning a real production API URL, database, and
> hosting remains an explicit external step — never faked, never a
> Codespace/localhost/placeholder URL presented as live. See
> [DEPLOYMENT.md](./DEPLOYMENT.md) for the complete architecture,
> environment variable reference, migration/backup/rollback procedures,
> and readiness checklist, and [DECISIONS.md](./DECISIONS.md), "Phase 23
> — Production Infrastructure & Deployment Readiness" for the full
> rationale and the implemented-and-verified vs. prepared-but-external
> distinction.
>
> Phase 22 — Capacitor Native Wrappers. MIZAN now ships as a
> native Android/iOS app shell (`mobile/capacitor/`, app id
> `com.mizan.app`) alongside the unchanged web/PWA build, from the same
> `frontend/` codebase — Capacitor bundles a Next.js **static export**
> (`BUILD_TARGET=capacitor npm run build:capacitor`; the normal
> `npm run build` is untouched) rather than running a second frontend or
> packaging FastAPI/PostgreSQL into the app; the native app calls the same
> FastAPI backend over HTTPS. A build-time guard
> (`lib/capacitor-build-guard.ts`) refuses to produce a Capacitor build
> with a missing, non-HTTPS, or ephemeral Codespace/cloud-IDE preview
> `NEXT_PUBLIC_API_BASE_URL` — no production API exists yet, and this
> phase does not invent one or hardcode this session's own preview URL.
> The Phase 21 service worker is disabled inside the native shell
> (`lib/capacitor-env.ts`'s `isNativeApp()`) since a bundled, on-disk app
> has no "offline app shell" gap for it to fill and no service-worker-
> delivered update path (native updates ship through the App/Play Store);
> the Phase 21 offline banner stays fully active, since a bundled app can
> still be on a device with no network. MIZAN's existing brand mark (the
> same teal `#0f766e` background, bold white "M" as `app/icon.tsx`) was
> used to generate real launcher icons and splash screens for both
> platforms — never Capacitor's generic default icon. Android and iOS
> native projects were generated and structurally validated (identifiers,
> manifests, icons, no cleartext/ATS exceptions); a real Gradle build and
> a real signed Xcode build were not completed in this sandboxed
> environment (Android: `dl.google.com` blocked by egress policy,
> confirmed directly; iOS: no macOS/Xcode toolchain exists here at all) —
> see [DEPLOYMENT.md](./DEPLOYMENT.md), "Capacitor Native Builds" for
> exactly what was and wasn't verified, and
> [DECISIONS.md](./DECISIONS.md), "Phase 22 — Capacitor Native Wrappers"
> for the full design rationale. No backend or database change; no
> investment-strategy, allocation, recommendation, notification,
> transaction, or Telegram logic touched.
>
> Phase 21 — PWA / Mobile App Experience. MIZAN is now
> installable as a standalone, app-like PWA: `app/manifest.ts` declares a
> standard (`purpose: "any"`) and a maskable icon (`app/icon1.tsx`, named
> per Next's numbered-icon convention since `icon-maskable.tsx` is not a
> recognized file-convention name and silently produced no route at all
> — caught by a live build/serve check, not assumed), plus
> `orientation: "portrait-primary"`. iOS gets a dedicated
> `app/apple-icon.tsx` (iOS ignores the manifest's icon array and reads
> only `<link rel="apple-touch-icon">`) and `capable`/`statusBarStyle`
> Apple web-app metadata, which Next.js 16 renders as the modern
> `mobile-web-app-capable` meta tag rather than the deprecated
> vendor-prefixed one. The pre-existing `.safe-top`/`.safe-bottom`
> safe-area handling (notch/Dynamic Island/home indicator) gained a
> `.safe-x` companion for landscape left/right insets on the header and
> bottom nav. A new hand-rolled service worker (`public/sw.js`, no
> third-party PWA library) caches only the static app shell
> (`/_next/static/*`, cache-first, content-hashed so it's safe forever)
> and never intercepts `/api/*` or non-GET requests at all — the app's
> `lib/api.ts` already sends every request with `cache: "no-store"`, so
> the one remaining risk was a service worker reintroducing staleness at
> the Cache Storage layer underneath that, which this design structurally
> avoids rather than merely avoiding by convention. Updates are opt-in: a
> new service worker installs but waits for an explicit "تحديث" click
> before `skipWaiting()`, so a reload can never interrupt someone mid-
> transaction-entry. A new global offline banner
> (`components/offline-banner.tsx`) makes it explicit when current
> financial data cannot be refreshed, additive to the existing per-request
> `ErrorBlock`/`QueryBoundary` handling. See [DECISIONS.md](./DECISIONS.md),
> "Phase 21 — PWA / Mobile App Experience" for the full design rationale.
> No backend or database change; no investment-strategy, allocation,
> recommendation, notification, transaction, or Telegram logic touched.
>
> Phase 20 (Telegram push delivery for the Notification Center) taught
> the existing `TelegramNotificationDispatcher` a second delivery method,
> `dispatch_notification`, so the out-of-band worker can deliver the
> persisted Phase 19 Notification Center — its sole source of truth,
> never recomputed — gated by global config → portfolio switch →
> per-alert-rule opt-in for alert-origin notifications (portfolio switch
> alone for recommendation-origin ones). See
> [DECISIONS.md](./DECISIONS.md), "Phase 19 — Alerts & Notifications" for
> the delivery design this phase completed.
>
> Phase 19 — Alerts & Notifications (P1). A new in-app
> Notification Center (`GET/PATCH/POST /api/portfolio/notifications*`)
> sits on top of the existing, unmodified Phase 8 alert engine and
> Phase 17/18 rebalancing/recommendation outputs — never a third
> financial engine. Every newly-triggered allocation/price/dip-buy check
> (`alert_service.evaluate_alerts`) and every CRITICAL/WARNING Phase 18
> recommendation becomes a persisted, deduplicated `Notification` row
> (`PRICE_ALERT`/`ALLOCATION_ALERT`/`RECOMMENDATION_ALERT`, severity
> `CRITICAL`/`WARNING`/`INFO`) with a contextual navigation action
> (review Distribution/Recommendations/Watchlist) — never an executed
> trade. A database-level partial unique index on `source_id` guarantees
> repeated evaluation never spams duplicate notifications, and the same
> edge-triggered "new vs. still active vs. cleared" idea Phase 8 already
> uses is mirrored for Phase 18's otherwise-stateless recommendations.
> The pre-existing "an asset must be both watched AND have its alert rule
> enabled" activation hierarchy was investigated and found correct and
> deliberate — left completely unchanged, only made visible in the
> Watchlist UI (which layer, if either, is currently the reason alerts
> are off for a given asset). Telegram delivery is explicitly untouched
> and deferred to Phase 20 — in-app visibility never depends on it. See
> [DECISIONS.md](./DECISIONS.md), "Phase 19 — Alerts & Notifications"
> for the full design rationale. One new table (`notifications`); no
> existing table's shape changed.
>
> Phase 18 (Smart Recommendations, P1) added `GET /api/portfolio/
> recommendations`, synthesizing Phase 17's per-category rebalancing
> output into prioritized, Arabic, user-facing guidance — a maximum
> breach becomes `CRITICAL`/`BREACH_RESOLUTION`, a fundable BUY becomes
> `CASH_DEPLOYMENT`, an underweight category with no fundable cash or
> disabled buying becomes an informational `RESTRICTED_ACTION` (never a
> false BUY), and a healthy portfolio gets a single all-clear
> `PORTFOLIO_HEALTHY` recommendation — presentation only, every number
> read verbatim from Phase 17. See [DECISIONS.md](./DECISIONS.md),
> "Phase 18 — Smart Recommendations".
>
> Phase 17 (Smart Rebalancing, P1) added `GET /api/portfolio/rebalancing`,
> a per-category BUY/REDUCE/HOLD/NO_CAPACITY/NO_TARGET recommendation
> deliberately reusing two already-approved engines rather than inventing
> new math: the BUY side is the Phase 7 Smart Inflow Allocator itself,
> fed Phase 16's `available_cash`; the one new calculation is the REDUCE
> amount for a category already over its configured maximum. See
> [DECISIONS.md](./DECISIONS.md), "Phase 17 — Smart Rebalancing".
>
> Phase 16 (Financial Core & Cash Logic, P0) fixed a confirmed bug: the
> dashboard previously labeled `investable_value` (an allocation-
> percentage denominator that INCLUDES invested market value) as
> "Investable Cash." `available_cash`/`invested_market_value` are now
> genuinely separate fields, a missing live price falls back to a real
> stale price or same-currency average cost (`price_status`:
> `"LIVE"`/`"PENDING_SYNC"`, unrealized P/L always 0 when not live), and
> the frontend shows sane quantity/currency precision, accessible P/L
> direction wording, and strictly newest-first transactions — see
> [DECISIONS.md](./DECISIONS.md), "Phase 16 — Financial Core & Cash
> Logic". `TRANSFER` transaction semantics and an Egypt-local EOD
> boundary remain unimplemented (Phase 15, disclosed). No broker
> integration, automatic trading, authentication, or full multi-user/
> multi-portfolio system exist yet. See [Phase Plan](#phase-plan) below.

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
16. Financial Core & Cash Logic, P0 (separated Portfolio Value / Investable Value / Available Cash / Reserved Cash so a stock-only holding can never show as spendable cash; missing-price fallback to a stale price or same-currency average cost, exposed as a simple LIVE/PENDING_SYNC signal with unrealized P/L always 0 when not live; user-facing quantity/currency formatting; accessible P/L presentation with explicit arrow + direction wording, not color alone; deterministic newest-first transaction ordering) — done
17. Smart Rebalancing, P1 (per-category BUY/REDUCE/HOLD/NO_CAPACITY/NO_TARGET recommendations reusing the Phase 7 Smart Inflow Allocator for BUY distribution funded only by Phase 16's `available_cash`, plus a new maximum-breach REDUCE calculation; maximum always takes priority over target; recommendation-only, surfaced contextually on the Distribution screen — never an executed trade) — done
18. Smart Recommendations, P1 (prioritized, Arabic, user-facing guidance synthesized from Phase 17's own rebalancing output — never a second rebalancing engine — classifying each category into BREACH_RESOLUTION/CASH_DEPLOYMENT/REBALANCING_OPPORTUNITY/RESTRICTED_ACTION/PORTFOLIO_HEALTHY with deterministic IDs and priority ordering; surfaced as a Dashboard card; recommendation-only, no automatic trade execution) — done
19. Alerts & Notifications, P1 (in-app Notification Center built on the existing, unmodified Phase 8 alert engine and Phase 17/18 rebalancing/recommendation outputs — never a third financial engine; deduplicated via a database-level partial unique index so repeated evaluation never spams; PRICE_ALERT/ALLOCATION_ALERT/RECOMMENDATION_ALERT categories with CRITICAL/WARNING/INFO severity; unread/read state; contextual navigation to Distribution/Recommendations/Watchlist; the existing two-level watchlist-entry + alert-rule activation hierarchy made visible, not changed; no automatic trade execution; Telegram delivery intentionally untouched, deferred to Phase 20) — done
20. Telegram push delivery for the Notification Center (Phase 19 explicitly deferred external delivery — see [DECISIONS.md](./DECISIONS.md), "Phase 19 — Alerts & Notifications"; delivers the persisted Phase 19 Notification Center as its sole source of truth via the existing Telegram dispatcher, gated by global config → portfolio switch → per-alert-rule opt-in for alert-origin notifications, portfolio switch alone for recommendation-origin notifications; never recomputes an alert or recommendation) — done
21. PWA / Mobile App Experience (installable manifest with standard + maskable icons, iOS home-screen metadata and safe-area handling for the notch/Dynamic Island/home indicator, a minimal hand-rolled service worker that caches only the static app shell and never touches `/api/*` so financial data is always network-authoritative, an offline banner, and an opt-in update prompt that never reloads mid-transaction — see [DECISIONS.md](./DECISIONS.md), "Phase 21 — PWA / Mobile App Experience") — done
22. Capacitor Native Wrappers (native Android/iOS shell — `mobile/capacitor/`, app id `com.mizan.app` — bundling the frontend's static export, `BUILD_TARGET=capacitor npm run build:capacitor`, alongside the unchanged web/PWA build from the same codebase; a build-time guard rejects a missing, non-HTTPS, or ephemeral-Codespace-preview `NEXT_PUBLIC_API_BASE_URL` rather than ever hardcoding one; the Phase 21 service worker is disabled inside the native shell as redundant there, the offline banner stays active; MIZAN brand icons/splash screens generated for both platforms; Android/iOS native projects generated and structurally validated — a real Gradle build and a real Xcode build were not completed in this sandboxed environment, see [DEPLOYMENT.md](./DEPLOYMENT.md), "Capacitor Native Builds" — see [DECISIONS.md](./DECISIONS.md), "Phase 22 — Capacitor Native Wrappers") — done
23. Production Infrastructure & Deployment Readiness (Docker hardened — `$PORT`-aware startup, non-root user, split runtime/dev dependencies; `GET /api/health/ready` added alongside the unchanged liveness `/api/health`; shared structured logging across the API and every worker with an audited no-secrets-logged guarantee; the dev seed script now refuses to run against `APP_ENV=production` without explicit override; `.env.example` corrected (two unused variables removed); CORS/HTTPS/Capacitor production-API requirements documented; a minimal test-only CI workflow added; migrations verified end-to-end against a clean empty database — see [DEPLOYMENT.md](./DEPLOYMENT.md) for the full architecture, environment variables, and production readiness checklist, and [DECISIONS.md](./DECISIONS.md), "Phase 23 — Production Infrastructure & Deployment Readiness" for what's implemented-and-verified versus prepared-but-externally-unprovisioned: no cloud account access exists in this environment, so no durable production URL, database, or deployment exists yet) — done
23.5. Production Provisioning (a real deployment attempt against all four target providers — Vercel, Render, Railway, Supabase — confirmed with direct evidence that this environment's egress policy denies outbound connections to every one of them; no credentials for any provider exist here either. Nothing in the repository blocks deployment — only the absence of both network access and cloud credentials from this environment. Every locally-verifiable piece of Phase 23's work was re-confirmed fresh: full test suites, a clean-database migration run, both production build modes, Capacitor sync/tests, and a full security scan — see [DEPLOYMENT.md](./DEPLOYMENT.md), "Production Provisioning Attempt Log" and [DECISIONS.md](./DECISIONS.md), "Phase 23.5 — Production Provisioning") — done *(current)*
24. Full multi-portfolio support (deferred from Phase 12 — see [DECISIONS.md](./DECISIONS.md))
25. A verified EGID or EGXAPI adapter, or another zero-cost EGX-specific data source (deferred from Phase 13 — see [DECISIONS.md](./DECISIONS.md), requires network access and human-obtained API documentation this environment could not get)
26. Live Telegram verification (deferred from Phase 14 — see [DECISIONS.md](./DECISIONS.md), `api.telegram.org` confirmed blocked by this environment's egress policy) and a "send test message" admin action (explicitly deferred by Phase 14's own approval)
27. TRANSFER transaction semantics, Egypt-local (Africa/Cairo) EOD trading-day boundary, and analytics coverage for pre-Phase-15 snapshot history (deferred from Phase 15 — see [DECISIONS.md](./DECISIONS.md))
28. A fully-integrated cash ledger where BUY/SELL automatically debit/credit a cash balance (Phase 16 confirmed no such link exists or was ever approved — see [DECISIONS.md](./DECISIONS.md), "Phase 16 — Financial Core & Cash Logic"; only an explicit DEPOSIT/WITHDRAWAL moves `available_cash` today)
29. Asset-level SELL selection within an overweight category, and an actual "execute this rebalancing recommendation" action (Phase 17 explicitly recommendation-only — see [DECISIONS.md](./DECISIONS.md), "Phase 17 — Smart Rebalancing")
30. An asset-selection algorithm for which specific holding(s) to BUY/REDUCE within a category, and an actual "execute this recommendation" action (Phase 18 explicitly category-level and recommendation-only — see [DECISIONS.md](./DECISIONS.md), "Phase 18 — Smart Recommendations")
31. A dedicated `alert_events` table giving independent per-condition-type dedup (deferred since Phase 8 — see DATABASE.md, "Known Schema Limitations (Phase 8)"; Phase 19's `notifications` table solves a different problem and does not fix this)

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
pip install -r requirements-dev.txt  # runtime deps + pytest; use requirements.txt alone for a production install
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
