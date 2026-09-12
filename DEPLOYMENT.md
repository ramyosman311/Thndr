# Deployment

## Status

**Phase 23 (this document's authoritative revision)**: production
infrastructure is implemented and locally verified — Docker image,
migrations, health/readiness endpoints, structured logging, CORS,
secrets handling, CI, and Capacitor production configuration are all in
place and tested in this environment. **No durable external deployment
has been provisioned** — this sandboxed environment has no cloud
credentials for Render/Railway/Supabase/Vercel or any other provider.
Every section below distinguishes what was implemented-and-verified here
from what still requires an operator with real cloud account access to
provision externally. See DECISIONS.md, "Phase 23 — Production
Infrastructure & Deployment Readiness" for the full rationale.

## Architecture

MIZAN's production topology, chosen because it was already the
documented target in this file since early phases and nothing found
during the Phase 23 audit gave a concrete technical reason to change it:

| Component | Local Development | Production |
|---|---|---|
| Backend | Docker (docker-compose), FastAPI + Uvicorn | Container on Render or Railway (either is compatible — see "Why this architecture" below) |
| Database | Dockerized PostgreSQL | Supabase-hosted PostgreSQL |
| Frontend (web/PWA) | `next dev` | Deployed as a Next.js app (e.g. Vercel) or containerized alongside the backend |
| Frontend (native) | N/A | Capacitor-wrapped static export, distributed via Google Play / App Store (see "Capacitor Production Configuration") |
| Workers (`price_refresh`, `alert_notify`, `snapshot_eod`) | Run manually/on-demand in dev | Scheduled process in production (no in-repo scheduler — external cron/platform feature required) |

```
                    ┌─────────────────────┐        ┌──────────────────────┐
                    │  Web/PWA (Vercel)   │        │ Capacitor native app │
                    │  next build (server)│        │ (static export       │
                    └──────────┬──────────┘        │  bundled on-device)  │
                               │                    └──────────┬───────────┘
                               │ HTTPS                          │ HTTPS
                               └───────────────┬─────────────────┘
                                                ▼
                                   ┌────────────────────────┐
                                   │  FastAPI (Render/       │
                                   │  Railway container)     │
                                   └────────────┬────────────┘
                                                │
                                                ▼
                                   ┌────────────────────────┐
                                   │  Supabase PostgreSQL    │
                                   └────────────────────────┘

     (out-of-band, scheduled externally -- never inside the API process)
     price_refresh / alert_notify / snapshot_eod  ──▶  same PostgreSQL
     alert_notify  ──▶  Telegram Bot API (only when explicitly enabled)
```

### Why this architecture

- **FastAPI on Render/Railway**: both support a plain Dockerfile-based
  web service with persistent environment variables, a durable HTTPS
  URL, and a documented health-check integration — exactly what this
  backend already provides (`backend/Dockerfile`, `GET /api/health`).
  Neither requires restructuring the application; either is a drop-in
  target for the image already built here.
- **Supabase for PostgreSQL**: already the documented choice (this file,
  every phase back to Phase 2) and already how the codebase talks to the
  database — a plain `DATABASE_URL`/`DATABASE_URL_SYNC` connection
  string, no Supabase client SDK dependency. Managed backups, durable
  storage, and no server to patch.
- **Vercel (or the same container) for the web/PWA frontend**: the
  Next.js build is entirely standard (`npm run build`, a normal server
  build with the `/api/*` rewrite) — Vercel is a zero-config fit; the
  "containerized alongside the backend" alternative stays available
  without any code change since nothing here is Vercel-specific.
- **Capacitor for native**: already implemented in Phase 22; Phase 23
  only makes its production API configuration a hard build-time
  requirement (see "Capacitor Production Configuration").

No provider swap was made or considered necessary — the audit found the
existing architecture already sound for this codebase's actual shape
(a stateless FastAPI process, a single Postgres database, a static-
export-compatible frontend).

## Environment Variables

All configuration is via environment variables — `.env.example` (repo
root) is the authoritative list of names and safe placeholders; never
commit a real `.env`. Full inventory and what each controls:

| Variable | Dev default | Production requirement |
|---|---|---|
| `APP_ENV` | `development` | `production` — gates debug mode and the seed script's production guard |
| `APP_DEBUG` | `true` | `false` (also force-disabled whenever `APP_ENV=production`, regardless of this value) |
| `DEV_MODE` | `true` | `false` — see ARCHITECTURE.md, "Authentication Boundary" |
| `BACKEND_HOST` | `0.0.0.0` | `0.0.0.0` (required for a container to accept external traffic) |
| `BACKEND_PORT` | `8000` | Not usually set directly — most platforms inject `$PORT`, which `backend/Dockerfile`'s CMD already reads with `8000` as its fallback |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated, explicit production origins — see "CORS" below. Never `*` |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | local/dockerized Postgres | Supabase (or equivalent) connection strings — async and sync forms respectively (Alembic uses the sync one) |
| `SECRET_KEY` | placeholder | A strong, unique, randomly generated value |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Backend-only secrets — see "Secrets" and "Telegram Configuration" below |
| `TELEGRAM_ENABLED` | `false` | `true` only once credentials are set and delivery is wanted |
| `ALLOW_SEED_IN_PRODUCTION` | unset | Leave unset in real production — only set to `1` deliberately, e.g. seeding a pre-launch demo instance |
| `NEXT_PUBLIC_API_BASE_URL` | `/api` (relative, dev) | The production API's HTTPS URL for the web deployment; a build-time-baked HTTPS URL for the Capacitor build — see "Web Deployment" and "Capacitor Production Configuration" |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | unset | Reserved — no code path reads these today (see `.env.example`'s comment); do not set real values without a corresponding feature that uses them |

## Local Development

Unchanged by Phase 23 — `docker-compose.yml` still brings up Postgres +
backend with the exact same commands as before:

```
docker compose up
```

(`docker compose config` was re-validated in this session and still
parses correctly.) See README.md, "Local Development" for the full
step-by-step for running the backend outside Docker and the frontend via
`next dev`.

## Production Services

### Backend (FastAPI container)

`backend/Dockerfile` — a single-stage, non-root, minimal image:

- Base: `python:3.12-slim`.
- Runtime dependencies only (`backend/requirements.txt`) — `pytest`/
  `pytest-asyncio` live in `backend/requirements-dev.txt` instead (which
  layers on top via `-r requirements.txt`) and are never installed into
  the production image.
- Runs as a non-root `appuser` (uid 1000).
- `HEALTHCHECK` polls `GET /api/health` on `$PORT` (default `8000`).
- Startup command binds to `0.0.0.0:${PORT:-8000}` (shell form, so a
  platform-injected `$PORT` is actually honored — fixed in Phase 23;
  previously hardcoded to `8000`) with **no** `--reload` — reload is a
  development-only uvicorn flag and was never enabled here.
- `.dockerignore` excludes both `.venv/` and `venv/` (Phase 23: the
  latter was previously missing, so a local venv could have bloated the
  build context), `__pycache__/`, `.env*` (except `.env.example`), and
  `.git/`.

**Verified in this session:** `docker compose config` parses cleanly;
the Dockerfile was reviewed line-by-line for the non-root user, minimal
apt footprint (`libpq5` only), healthcheck, and shell-form CMD/
HEALTHCHECK; a real `docker build` was attempted and — as in Phase 2 —
blocked by this sandboxed environment's egress policy (`docker.io`'s
CloudFront-backed blob storage returns `403 Forbidden`; the registry API
itself is reachable, confirming this is a deliberate proxy policy, not a
transient network fault). **This must be re-verified with a real `docker
build` on any environment with standard Docker Hub access** (a developer
machine, GitHub Actions, or the target platform's own build step) before
the first production deploy — nothing about the Dockerfile itself is
expected to fail there.

### Database (Supabase PostgreSQL)

- `asyncpg` (async, application traffic) and `psycopg2` (sync, Alembic)
  drivers, both already in `requirements.txt`.
- `pool_pre_ping=True` (already present) plus `pool_recycle=1800`
  (Phase 23) on the async engine — recycles connections every 30 minutes
  so a managed Postgres/pooler's own idle-connection timeout can't
  silently drop a long-lived connection out from under the process.
- Native `UUID` primary keys (application-generated via `uuid.uuid4`,
  not a Postgres extension — portable across any managed Postgres
  without needing `pgcrypto`/`uuid-ossp` enabled) and
  `TIMESTAMP(timezone=True)` columns with `server_default=func.now()`
  throughout (`app/models/mixins.py`) — audited in Phase 23, already
  correct, no change needed.

### Workers

Unchanged from Phase 11/14/15 — `price_refresh`, `alert_notify`, and
`snapshot_eod` remain standalone, out-of-band processes
(`python -m app.workers.<name>`), invoked by an external scheduler
(platform cron/scheduled job). None run inside the FastAPI process, and
this project still has no in-repo scheduler — that remains a disclosed,
deliberate minimum-mechanism choice, not an oversight. Phase 23 only
changed how each worker sets up logging (see "Logging" below), not their
execution model or scheduling requirements.

## Database Creation & Migration Procedure

1. Provision a PostgreSQL database (Supabase project, or any Postgres
   16-compatible instance).
2. Set `DATABASE_URL`/`DATABASE_URL_SYNC` to that instance.
3. Run migrations **once, before the application starts serving
   traffic**, as an explicit, separate step — never automatically on
   container boot, and never from more than one replica concurrently:
   ```
   cd backend && alembic upgrade head
   ```
   On a platform with multiple replicas (Render's autoscaling, Railway's
   horizontal scaling), run this as that platform's dedicated one-off/
   pre-deploy command feature, not as part of every replica's own
   startup — Alembic takes no application-level lock against concurrent
   invocations, so two replicas migrating simultaneously is a real risk
   this procedure exists to avoid.
4. Only then start (or restart) the API service.

**Verified in this session**: created a brand-new, completely empty
PostgreSQL database and ran `alembic upgrade head` against it directly
— all 5 migrations (`ac3c275604cd` through `e7b9c2a1d430`) applied
cleanly in order, producing all 15 expected tables; `alembic check`
confirmed no drift afterward. This is the strongest available proof
short of running it against the real target platform.

Never rewrite a historical migration file — Phase 23 added no new
migration (no schema change was required for any infrastructure work).

## Secrets Management

Audited in Phase 23; no changes needed to the mechanism (environment
variables only, `pydantic-settings` reading them — see
`app/core/config.py`), only to what's documented:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`,
  `DATABASE_URL_SYNC`, `SECRET_KEY` are backend-only. A repo-wide scan
  confirms zero references to any of these names anywhere under
  `frontend/` or `mobile/` — the only `process.env.NEXT_PUBLIC_*` read
  anywhere in the frontend is `NEXT_PUBLIC_API_BASE_URL` (enforced by an
  automated test, `frontend/tests/capacitor.test.tsx`).
- No log statement anywhere in the backend references a token, password,
  secret, or connection string (grepped for the literal identifiers as
  part of this audit) — `services/telegram_dispatcher.py`'s "never logs
  the bot token on any failure path" guarantee (Phase 14, still tested)
  is the pattern every other log call already follows.
- `MARKET_DATA_PROVIDER`/`MARKET_DATA_API_KEY` were removed from
  `.env.example` in Phase 23 — a repo-wide search found these were never
  actually read by any code path (Phase 13 wired providers per-asset via
  `asset_price_configs.primary_provider` instead), so documenting them
  as required configuration was actively misleading.
- `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` remain in `.env.example`,
  now explicitly marked "reserved, not read by any code today" — the
  database connection already works against Supabase-hosted Postgres via
  a plain connection string with no Supabase SDK dependency; these two
  are placeholders for a possible future Supabase Auth integration
  (already anticipated in ARCHITECTURE.md), not a currently-required
  value.
- Never commit a real `.env` — already gitignored; verified still the
  case in this session's `git status`.

## CORS

`BACKEND_CORS_ORIGINS` (comma-separated) drives FastAPI's
`CORSMiddleware` — already fully environment-driven with no wildcard
default (`http://localhost:3000` in dev, confirmed by reading
`app/main.py` and `app/core/config.py`; no code path ever passes `"*"`).

**A production deployment must set this to include:**

1. The production web/PWA origin (e.g. `https://mizan.example.com`,
   whatever the actual Vercel/custom domain ends up being).
2. `https://localhost` — the Capacitor native app's WebView origin
   (`mobile/capacitor/capacitor.config.ts` sets
   `server.androidScheme: "https"`), once a native build is distributed.

Example: `BACKEND_CORS_ORIGINS=https://mizan.example.com,https://localhost`

Development remains more permissive (`http://localhost:3000` only,
matching the local Next.js dev server) — no change needed there.

## Health & Readiness

Two distinct endpoints (readiness added in Phase 23; liveness unchanged
from Phase 2):

- **`GET /api/health`** — liveness. Returns `{"status": "ok", "database":
  "connected"|"unavailable"}` with HTTP 200 always, as long as the
  process is running and able to respond — a database hiccup shows up
  only in the informational `database` field, never as a non-200 status.
  Use this for "is the process alive" checks (container restart
  policies).
- **`GET /api/health/ready`** — readiness (Phase 23, new). Returns
  `{"status": "ready"}` with HTTP 200 when the database is reachable,
  or HTTP 503 with `{"detail": "database unavailable"}` otherwise. Use
  this for "should traffic be routed here" checks (a load balancer or
  orchestrator's readiness probe) — a platform that only supports one
  health-check URL should use this one, since it actually reflects
  whether the instance can serve a real request.

Neither endpoint exposes internal infrastructure details beyond a single
connected/unavailable flag — no connection string, no stack trace, no
table names.

## Logging

Phase 23 added `app/core/logging_config.py` (`configure_logging()`),
called once by the FastAPI process (`app/main.py`, at import time) and
by every worker's `main()` (replacing each worker's previous bare
`logging.basicConfig(level=logging.INFO)`), so every process emits the
same format: `<ISO8601 timestamp> <LEVEL> [<logger name>] <message>`.
Level is `INFO` in production (`DEBUG` only in local dev with
`APP_DEBUG=true`).

The FastAPI process also now logs an explicit line on startup (env +
debug flag) and shutdown (via a `lifespan` context manager, which also
disposes the database engine's connection pool cleanly on shutdown).

**Never logged, anywhere in this codebase** (audited in Phase 23 by
grepping every `logger.*` call for token/password/secret/database_url/
dsn-shaped identifiers — zero matches): passwords, tokens, full
connection strings, or other secrets. Failures are still logged with
enough context to diagnose (which asset/notification/request failed and
why), per the existing pattern in `telegram_dispatcher.py`,
`alert_notify.py`, `price_refresh.py`, and the FastAPI global exception
handler.

**Verified live in this session**: started the backend locally (both
with and without a `$PORT` override) and confirmed the startup/shutdown
log lines appear with the expected timestamped format, and that
`/api/health` and `/api/health/ready` both respond correctly.

## Restart & Recovery

Nothing in this application stores state only in the container
filesystem — verified by inspection, not merely assumed:

- All persistent data (portfolios, transactions, holdings, snapshots,
  notifications, `telegram_sent_at` delivery state, alert rules,
  watchlist entries, asset/price configuration) lives in PostgreSQL,
  external to the API container.
- The API process is fully stateless between requests — no in-memory
  session store, no local file writes for application data.
- `pool_pre_ping=True` (already present) means a restarted database (or
  a network blip) is transparently recovered from on the next request,
  rather than the app serving stale/broken connections.
- A container restart therefore loses nothing: on the next boot the app
  reconnects to the same external Postgres and every table is exactly as
  it was. Alembic's `alembic_version` table means a restart can never
  cause migrations to silently re-run or diverge.
- No new stateful service was introduced by Phase 23 (no cache layer, no
  message queue, no session store) — deliberately, since none of this
  application's actual requirements need one.

## Backup & Restore Strategy

**Not yet configured** — this requires an actual Supabase project (or
equivalent managed Postgres), which does not exist in this sandboxed
environment. Documented here so a real deployment does not skip it:

- **If using Supabase**: Supabase's paid tiers include automated daily
  backups with a plan-dependent retention window (consult the current
  Supabase pricing/docs for the exact retention on whatever plan is
  chosen — this changes over time and this document should not guess a
  number that could go stale). The free tier does **not** include
  automated backups — if cost constraints mean starting on the free
  tier, an external `pg_dump` on a schedule (e.g. a scheduled GitHub
  Action, alongside `alert_notify`'s existing external-scheduler
  pattern) is the interim mitigation, and should be treated as a
  required setup step, not an optional one.
- **Manual restore procedure** (works against Supabase or any Postgres):
  ```
  pg_dump "$DATABASE_URL_SYNC" > backup.sql       # take a backup
  psql "$DATABASE_URL_SYNC" < backup.sql          # restore into an empty database
  ```
  followed by `alembic stamp head` only if restoring into a database
  whose schema already matches the current migration head (a plain
  `pg_dump`/`psql` restore already includes the `alembic_version` table,
  so this is usually unnecessary — verify with `alembic check` after
  restoring).
- **Never** treat the development seed data (`python -m app.seed`) as a
  backup or recovery mechanism — it is demo/fixture data, and Phase 23
  added an explicit guard (`ALLOW_SEED_IN_PRODUCTION`) specifically to
  stop it from ever being mistaken for one against a real deployment.

## Rollback Considerations

- **Application code**: redeploying the previous container image/build
  is the rollback path on every platform under consideration (Render,
  Railway, Vercel all support this natively) — no custom mechanism
  needed.
- **Database migrations**: every Alembic migration in this repo has a
  real `downgrade()` (inherited from Alembic's standard revision
  template); `alembic downgrade -1` reverts the most recent one. Treat
  this as a last resort for a genuinely broken migration, not a routine
  tool — a downgrade that drops a column the just-deployed code still
  expects to read will break that code just as badly as the forward
  migration failing did.
- **Never** roll back by manually editing production data to "undo" a
  transaction, snapshot, or notification — see FINANCIAL_RULES.md; the
  accounting model has no concept of an out-of-band correction, and
  Phase 23 introduces no exception to that.

## Web Deployment

No change to the web/PWA architecture — `npm run build` (a normal
Next.js server build, `/api/*` proxied to FastAPI via `next.config.ts`'s
`rewrites()`) remains exactly as Phase 16B left it. Deploy it to Vercel
(zero-config for a standard Next.js app) or containerize it alongside
the backend — both remain valid per the existing Target Topology; Phase
23 did not need to pick between them, since nothing about production
readiness depends on that choice.

**Required for production**: set `NEXT_PUBLIC_API_BASE_URL` (via the
hosting platform's environment variable configuration, e.g. Vercel's
project settings) to the real production FastAPI URL. Never leave it
defaulting to the relative `/api` path unless the frontend and backend
are actually deployed behind the same origin/reverse proxy.

**Verified in this session**: `npm run build` still succeeds (13 routes,
unchanged from Phase 22), with no Codespace dependency anywhere in the
build output — confirmed by the same automated scan that checks
Capacitor's build guard.

## Capacitor Production Configuration

Builds on Phase 22's integration; Phase 23 made its production API
configuration a hard requirement rather than a documented convention.

- **App ID**: `com.mizan.app` (unchanged, Phase 22).
- **No `server.url`, no development API fallback**: `capacitor.config.ts`
  has never set `server.url` — the app always ships the bundled static
  export, never loads a remote page. There is no "fallback" API URL of
  any kind; `lib/capacitor-build-guard.ts` makes the build **fail
  outright** rather than silently default to something unsafe if
  `NEXT_PUBLIC_API_BASE_URL` is missing, non-HTTPS, or looks like a
  Codespace/cloud-IDE preview URL.
- **HTTPS required**: enforced both by the build guard (rejects
  non-HTTPS unless the loopback-only local-dev escape hatch is used) and
  by Android/iOS platform defaults (`allowMixedContent: false`; no ATS
  exceptions in `Info.plist`) — audited again in Phase 23, unchanged
  from Phase 22 since nothing required changing.
- **Production build command**:
  ```
  NEXT_PUBLIC_API_BASE_URL=https://api.<your-production-domain>/api \
  BUILD_TARGET=capacitor npm run build:capacitor
  cd mobile/capacitor && npm run sync
  ```
  then `npm run open:android` / `npm run open:ios` for a real signed
  build on a machine with the Android SDK / Xcode respectively.
- **Service worker**: confirmed still correctly disabled inside the
  native shell (`isNativeApp()` check, Phase 22) — re-verified in this
  session's frontend test run (130/130 passing, including the
  Capacitor-specific suite).
- **Not App Store / Google Play ready**: no real Android Gradle build or
  signed iOS Xcode build has been performed (see "Backend/Docker" build
  status above and DECISIONS.md, Phase 22 for why) — only structural
  validation. This remains true after Phase 23; nothing in this phase
  changed that status, since neither an Android SDK nor an Xcode
  toolchain exists in this environment.

## Telegram Configuration

Unchanged Phase 20 architecture, re-verified rather than modified:

```
notifications (Phase 19, persisted)
      │
      ▼
alert_notify worker (Phase 20, out-of-band, scheduled externally)
      │  queries: telegram_sent_at IS NULL
      ▼
TelegramNotificationDispatcher
      │  sets telegram_sent_at only on confirmed success
      ▼
Telegram Bot API
```

- The worker still consumes only the persisted `notifications` table —
  Phase 23 did not add, remove, or bypass any step in this chain.
- `telegram_sent_at`, at-least-once retry semantics (a pending/failed
  notification remains eligible for the next scheduled run), the
  portfolio-level and alert-rule-level opt-in gates, and the
  recommendation-origin/alert-origin gating asymmetry are all unchanged
  — re-confirmed by the full backend suite (`test_alert_notify_worker.py`,
  `test_telegram_dispatcher.py`) still passing.
- **Production configuration**: set `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED=true`, enable the portfolio-level
  Telegram switch, and schedule
  `python -m app.workers.alert_notify` externally (platform cron/
  scheduled job — this project still has no in-repo scheduler).
- **No live Telegram delivery was verified in this session** — this
  sandboxed environment cannot reach `api.telegram.org` (a pre-existing,
  documented constraint from Phase 14/26 planning, unrelated to Phase
  23) and has no real bot token. Only the existing mocked-HTTP test
  suite was re-run.

## Error Handling

Unchanged: production responses never include stack traces or internal
exception details — only clear, safe `detail` messages (see API.md).
Debug output is gated behind `APP_DEBUG=false` in production (and
force-disabled whenever `APP_ENV=production`, regardless of that flag —
`app/main.py`'s `debug=settings.app_debug and not settings.is_production`).

## CI/CD

`.github/workflows/ci.yml` (new, Phase 23) — a test-only pipeline, no
deployment step and no secrets required:

- **`backend` job**: spins up a throwaway `postgres:16-alpine` service
  container, installs `requirements-dev.txt`, runs the full pytest
  suite.
- **`frontend` job**: `npm ci`, `tsc --noEmit`, `npm run lint`,
  `npm test`, `npm run build`.
- Runs on every push and pull request. Deliberately does not: deploy
  anywhere, run any migration against a real database, or require any
  repository secret — exactly the "do not over-engineer, do not deploy
  on every random branch, do not run destructive commands" boundary this
  phase's own instructions set.

Actual deployment (pushing a new image to Render/Railway, promoting a
Vercel build) remains a manual, external step until real cloud
credentials are available to wire up a deploy job safely.

## Troubleshooting

- **`alembic upgrade head` fails with a connection error** — check
  `DATABASE_URL_SYNC` is reachable from wherever the command is run
  (Supabase requires the connecting IP/network to be allowed, depending
  on its network restrictions setting).
- **`GET /api/health/ready` returns 503** — the database is unreachable
  from the API process specifically; check `DATABASE_URL` (async form),
  network/firewall rules between the API host and Postgres, and that
  migrations have actually been applied (`alembic check` from a host
  that can reach the same database).
- **CORS errors in the browser/WebView console** — confirm
  `BACKEND_CORS_ORIGINS` includes the exact origin making the request
  (scheme + host, no path) — see "CORS" above for the two origins a
  production deployment needs.
- **Capacitor build fails with a `NEXT_PUBLIC_API_BASE_URL` error** —
  intentional; read the error message, which names exactly which of the
  three checks (missing / not HTTPS / looks like a Codespace URL)
  failed, and see "Capacitor Production Configuration" above.
- **Telegram messages never arrive** — walk the AND-gate in order:
  `TELEGRAM_ENABLED=true` → real `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
  → the portfolio's own Telegram switch → (for alert-origin
  notifications only) that specific alert rule's own opt-in. Any one
  being off means silent, correct non-delivery, not a bug — see
  FINANCIAL_RULES.md, "Telegram Delivery (Phase 14)".
- **A worker "did nothing"** — check its own log output first (Phase 23
  gave every worker the same structured log format); most "nothing
  happened" runs are correct no-ops (e.g. `snapshot_eod` already ran
  today, or no notifications are pending delivery), not failures.

## Production Readiness Checklist

- [x] Production FastAPI container — Dockerfile hardened (non-root,
      minimal deps, `$PORT`-aware, healthcheck); a real `docker build`
      itself remains blocked in this sandboxed environment (re-verify
      elsewhere)
- [ ] Durable HTTPS API — **prepared, not provisioned** (no cloud
      account access here)
- [ ] Persistent PostgreSQL — **prepared, not provisioned** (Supabase
      project not created)
- [x] Alembic migrations — verified end-to-end against a clean, empty
      database in this session
- [x] Safe production initialization — seed script now refuses to run
      against `APP_ENV=production` without explicit override; no
      auto-migration on container boot
- [x] Environment/secrets management — audited; `.env.example` corrected
      (removed two unused variables, clarified the rest); no secret
      reaches the frontend bundle (automated test)
- [x] CORS — environment-driven, no wildcard, documented production
      values (web origin + Capacitor's `https://localhost`)
- [x] Health/readiness — `/api/health` (liveness, unchanged) and
      `/api/health/ready` (readiness, new) both implemented and tested
- [x] Production logging — shared structured format across the API and
      every worker; verified live; audited for secret leakage (none
      found)
- [x] Restart/recovery — audited; no state lives outside PostgreSQL,
      `pool_pre_ping`/`pool_recycle` handle reconnection
- [ ] Backup strategy — **documented, not configured** (requires an
      actual Supabase project/plan decision)
- [x] Production frontend API configuration — `NEXT_PUBLIC_API_BASE_URL`
      documented as an explicit, platform-set environment variable; no
      Codespace URL anywhere
- [x] Capacitor production API configuration — build-time guard enforces
      HTTPS + no Codespace URL; verified with real build attempts
      (success and every failure case)
- [x] No Codespace dependency — confirmed by inspection and by the
      automated build-guard tests; the Codespace URL named in this
      phase's instructions does not appear anywhere in committed source
- [x] Docker validation — `docker compose config` parses; Dockerfile
      manually reviewed; real `docker build` blocked by this
      environment's egress policy (re-verify elsewhere)
- [x] Backend tests — 607 passed (601 Phase-22 baseline + 6 new)
- [x] Frontend tests — 130 passed (unchanged from Phase 22; no frontend
      code changed this phase)
- [x] Production build — both the web build and the Capacitor static
      export build succeed
- [x] Security audit — no committed secrets, no wildcard CORS, no HTTP
      production default, debug/reload never enabled by default, no
      secret ever logged or exposed to the frontend
- [x] Documentation — this file, README.md, DECISIONS.md all updated
- [x] Git commit — see DECISIONS.md / the commit history for this phase
- [x] Git push — pushed to `claude/thndr-smart-portfolio-yhutj4`
