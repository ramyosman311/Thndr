# Deployment

## Status

This document specifies the intended deployment topology. No Dockerfiles,
docker-compose configuration, or hosted deployment exist yet — these are
introduced incrementally starting in **Phase 2** (backend Docker image) and
finalized in **Phase 15** (production deployment prep). This is the target
this project builds toward.

## Target Topology

| Component | Local Development | Production |
|---|---|---|
| Backend | Docker (docker-compose), FastAPI + Uvicorn | Container on Render/Railway (or equivalent) |
| Database | Dockerized PostgreSQL | Supabase-hosted PostgreSQL |
| Frontend | `next dev` | Deployed as a Next.js app (e.g. Vercel) or containerized alongside the backend |
| Workers (`price_refresh`, `alert_notify`) | Run manually/on-demand in dev | Scheduled process in production (no in-repo scheduler — external cron/platform feature required) |

**Price refresh worker (Phase 11):** `python -m app.workers.price_refresh`
is a standalone, idempotent, out-of-band process — invoke it on a
schedule (cron, the platform's scheduled-job feature, or a
long-running loop wrapped by the process manager) matched to how often
automated-fetching-enabled assets need refreshing. It is never started
by, or run inside, the FastAPI/Uvicorn process — see ARCHITECTURE.md,
"Price Infrastructure", and FINANCIAL_RULES.md, "Non-Blocking
Valuation" for why that separation is structural, not incidental.

**Alert notify worker (Phase 14):** `python -m app.workers.alert_notify`
follows the identical execution model — a standalone, out-of-band
process invoked on a schedule by the same external mechanism as
price refresh. It evaluates every configured alert rule (same logic as
the on-demand `POST /api/alerts/evaluate` route) and, for any rule/
portfolio that has opted in, delivers new triggers to Telegram. **This
project has no in-repo scheduling infrastructure** (no APScheduler, no
Celery beat, no cron) for either worker — the operator must configure
an external trigger; this is a disclosed, minimum-mechanism limitation,
not an oversight. See FINANCIAL_RULES.md, "Telegram Delivery (Phase 14)"
and DECISIONS.md, "Telegram Delivery Decision" for the full design,
including the strict AND-gate (`TELEGRAM_ENABLED` + credentials +
`portfolio_configs.telegram_enabled` + `alert_rules.telegram_enabled`)
that must all be true before any message is actually sent.

## Docker (Phase 2+)

> **Environment note (Phase 2 verification):** in this project's sandboxed
> Claude Code session, outbound HTTPS is routed through a policy-enforcing
> proxy that does not allow `docker.io`/CloudFront registry traffic. As a
> result, `docker pull python:3.12-slim` and `docker build` for the backend
> image were attempted but blocked with `403 Forbidden` at the proxy —
> confirmed as a persistent egress policy denial, not a transient failure
> or a Dockerfile defect. `docker-compose.yml` was validated with
> `docker compose config` (parses and resolves correctly). The Dockerfile
> and compose file are expected to build normally in any environment with
> standard Docker Hub access (a developer machine, GitHub Actions, or the
> target hosting platform's build step) — this should be re-verified there
> before production deployment.

- `backend/Dockerfile` — builds the FastAPI application image.
- `docker-compose.yml` (repo root) — orchestrates backend + PostgreSQL (+
  frontend, once containerized) for local development.
- The backend image must run database migrations (Alembic) as an explicit
  step, not silently on every boot in production.

## Database (Supabase)

- Production uses **Supabase PostgreSQL**, not a self-managed database, to
  minimize operational overhead for a personal project.
- Connection string supplied via `DATABASE_URL` (async, `asyncpg`) and
  `DATABASE_URL_SYNC` (for Alembic) — see `.env.example`.
- Migrations are run explicitly via Alembic against the Supabase instance
  as part of the deployment process, not auto-generated at runtime.

## Environment Variables

All configuration is via environment variables — see `.env.example` for
the authoritative list. Never committed to Git. Notably:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — backend-only, never exposed to
  the frontend bundle.
- `SECRET_KEY` — must be a strong, unique value in production, never the
  example default.
- `DEV_MODE` — must be `false` in any production deployment (see the
  Authentication Boundary section in ARCHITECTURE.md).

## CORS

Production CORS origins are restricted to the known frontend origin(s) via
`BACKEND_CORS_ORIGINS`. Wildcard origins are not used in production.

## Error Handling

Production responses never include stack traces or internal exception
details — only clear, safe `detail` messages (see API.md). Debug output is
gated behind `APP_DEBUG=false` in production.

## Health Monitoring

`GET /api/health` (Phase 2) is the baseline liveness/readiness check for
whatever hosting platform is used (Render/Railway health checks, uptime
monitoring, etc.).

## PWA Hosting Considerations

The frontend is served over HTTPS in production (required for service
worker registration and installability). Manifest/icon metadata and the
installable, offline-aware service worker were completed in **Phase 21**
— see ARCHITECTURE.md, "PWA and Capacitor Readiness" and DECISIONS.md,
"Phase 21 — PWA / Mobile App Experience". The service worker
(`public/sw.js`) never caches `/api/*` or non-GET requests, only the
static app shell, and updates are opt-in (a manual banner), never an
automatic reload — see that same DECISIONS.md entry for the full
cache-strategy rationale.

## Capacitor Native Builds (Phase 22)

MIZAN ships as a native Android/iOS shell — via [Capacitor](https://capacitorjs.com/)
— alongside the web/PWA build, from the same frontend codebase. See
DECISIONS.md, "Phase 22 — Capacitor Native Wrappers" for the full design
rationale; this section covers the operational build/deploy steps.

**Architecture:** native shell (Capacitor) + bundled frontend (a Next.js
*static export*, not a second frontend) + remote HTTPS FastAPI API.
Capacitor does not run a server inside the app — FastAPI and PostgreSQL
stay exactly where the rest of this document already puts them. The
native app is simply another HTTPS client of the same backend the
web/PWA build talks to.

### Building the native web bundle

The web/PWA build (`npm run build`) and the Capacitor build
(`npm run build:capacitor`) are two different output modes of the same
`frontend/` project, selected by the `BUILD_TARGET` environment variable
(see `frontend/next.config.ts`):

- `npm run build` (default, unchanged) — a normal Next.js server build;
  `/api/*` is proxied to FastAPI via `rewrites()`. This is what the
  web/PWA deployment always uses.
- `BUILD_TARGET=capacitor npm run build:capacitor` — a static export
  (`output: "export"`, no server, no rewrites — rewrites are not
  supported with static export) into `frontend/out/`, which
  `mobile/capacitor/capacitor.config.ts` (`webDir`) bundles into both
  native projects. Static export is safe here because every route in
  this app is a `"use client"` page with no server components, API
  routes, middleware, or dynamic segments — confirmed by inspection
  before Phase 22 began.

**A Capacitor build requires an explicit, durable, HTTPS
`NEXT_PUBLIC_API_BASE_URL`** — e.g.:

```
NEXT_PUBLIC_API_BASE_URL=https://api.<your-production-domain>/api BUILD_TARGET=capacitor npm run build:capacitor
```

The native app bundles static files with no server behind them, so the
web build's relative `"/api"` default (which only works because the dev/
production Next.js server rewrites it) cannot resolve inside a WebView.
`next.config.ts` enforces this at build time via
`lib/capacitor-build-guard.ts`: the build **fails fast** if
`NEXT_PUBLIC_API_BASE_URL` is missing, not HTTPS, or looks like an
ephemeral Codespace/cloud-IDE preview URL (`*.app.github.dev`,
`*.githubpreview.dev`, `*.gitpod.io`) — a Codespace preview URL stops
resolving once the session ends and must never become a shipped native
app's backend dependency. **No production FastAPI deployment exists yet**
(see the Deployment Checklist below) — provisioning one is a prerequisite
for a real Capacitor release build, not something this phase invents or
fakes.

### Local device/emulator development

For local testing against a dev backend that isn't HTTPS, set
`ALLOW_INSECURE_CAPACITOR_API=1` together with an emulator-reachable
loopback URL (never a real host): `http://10.0.2.2:8000/api` from the
Android emulator (its alias for the host machine's `localhost`), or your
LAN IP for a physical device. This escape hatch only accepts loopback-
shaped hosts; a real domain over plain HTTP is still always rejected.

### Building and syncing the native projects

From `mobile/capacitor/`:

- `npm run sync` (`cap sync`) — copies the frontend's `out/` into both
  native projects and updates native dependencies. Run this after every
  `build:capacitor`.
- `npm run generate-assets` — regenerates all Android/iOS launcher icons
  and splash screens from `assets/logo.png` (the MIZAN brand mark,
  transparent background) via `@capacitor/assets`. Only needs re-running
  if the brand mark changes.
- `npm run open:android` / `npm run open:ios` — open the native project
  in Android Studio / Xcode for a real signed build.
- `npm test` — structural checks (app id/name, no remote `server.url`,
  Android cleartext traffic disabled, native project identifiers match
  `capacitor.config.ts`).

`android/` and `ios/` are generated by `npx cap add android`/`ios` and
are **git-ignored** (see `.gitignore`, a decision already made in this
repository's Phase 1 scaffolding) — a fresh checkout must regenerate them
before syncing or building.

### Build status (this environment)

This Codespace/sandboxed environment could verify the following and no
further:

- **Android:** `cap add android` + `cap sync` succeed; the generated
  project structurally validated (manifest, `build.gradle`,
  `variables.gradle`, icons all correct and consistent with
  `capacitor.config.ts`). **A real Gradle build could not be completed**
  — `dl.google.com` (which serves the Android Gradle Plugin and every
  AndroidX/Google Maven artifact) is blocked by this environment's egress
  policy (`403 Forbidden`, confirmed directly, not assumed). This is an
  environment limitation, not a project defect — re-run
  `npm run build:android` (from `mobile/capacitor/`, requires Android
  SDK + a network with access to `dl.google.com`/`maven.google.com`) on a
  developer machine or CI runner with normal Android tooling access.
- **iOS:** `cap add ios` + `cap sync` succeed (this project uses Swift
  Package Manager, not CocoaPods, so `cap sync ios` needs no macOS-only
  tooling); the generated project structurally validated (`Info.plist`,
  `project.pbxproj`, bundle identifier, icons). **No Xcode build was
  performed** — this environment has no macOS/Xcode/Swift toolchain,
  full stop. A signed build and any App Store Connect step must happen on
  a Mac with Xcode and the relevant Apple Developer credentials.

### CORS for the native app

The native app's WebView still enforces CORS on its `fetch()` calls to
FastAPI, exactly like a browser. `BACKEND_CORS_ORIGINS` already supports
a comma-separated list (see Environment Variables above) — a production
deployment serving the Capacitor app must add its WebView origin
(`https://localhost`, since `capacitor.config.ts` sets
`server.androidScheme: "https"`) alongside the web frontend's real
origin.

## Deployment Checklist (to be completed in Phase 15)

- [ ] Backend Docker image builds and runs migrations against Supabase
- [ ] Production environment variables set (no defaults/examples in use)
- [ ] `DEV_MODE=false`, real authentication boundary decided or explicitly
      accepted as an interim network-level protection
- [ ] CORS restricted to production frontend origin
- [ ] Telegram credentials (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) configured server-side only, `TELEGRAM_ENABLED=true`
- [ ] `python -m app.workers.alert_notify` scheduled externally (cron/platform scheduled job) if Telegram delivery is wanted
- [ ] Health check wired into hosting platform monitoring
- [ ] Frontend served over HTTPS with correct PWA caching headers
- [ ] (If shipping the native app) A durable production FastAPI URL exists and `BACKEND_CORS_ORIGINS` includes `https://localhost` for the Capacitor WebView origin, before running `npm run build:capacitor`
- [ ] (If shipping the native app) A real Android build (Gradle + Android SDK) and a real signed iOS build (Xcode + Apple Developer credentials) completed outside this sandboxed environment
