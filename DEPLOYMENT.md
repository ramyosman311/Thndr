# Deployment

## Status

This document specifies the intended deployment topology. No Dockerfiles,
docker-compose configuration, or hosted deployment exist yet — these are
introduced incrementally starting in **Phase 2** (backend Docker image) and
finalized in **Phase 13** (production deployment prep). This is the target
this project builds toward.

## Target Topology

| Component | Local Development | Production |
|---|---|---|
| Backend | Docker (docker-compose), FastAPI + Uvicorn | Container on Render/Railway (or equivalent) |
| Database | Dockerized PostgreSQL | Supabase-hosted PostgreSQL |
| Frontend | `next dev` | Deployed as a Next.js app (e.g. Vercel) or containerized alongside the backend |
| Workers (alerts, Telegram) | Runs alongside backend in dev | Scheduled/long-running process in production |

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
worker registration and installability). Static assets (manifest, icons,
service worker) are added in Phase 11 and must be cache-controlled
correctly so app updates propagate rather than being stuck behind a stale
cached service worker.

## Capacitor (Phase 12)

Capacitor iOS/Android wrapping is prepared but not required to deploy or
run the web/PWA version. Native builds (Xcode/Android Studio) are not
assumed to be available in this environment and are out of scope for
automated deployment here.

## Deployment Checklist (to be completed in Phase 13)

- [ ] Backend Docker image builds and runs migrations against Supabase
- [ ] Production environment variables set (no defaults/examples in use)
- [ ] `DEV_MODE=false`, real authentication boundary decided or explicitly
      accepted as an interim network-level protection
- [ ] CORS restricted to production frontend origin
- [ ] Telegram credentials configured server-side only
- [ ] Health check wired into hosting platform monitoring
- [ ] Frontend served over HTTPS with correct PWA caching headers
