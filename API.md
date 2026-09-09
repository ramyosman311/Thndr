# API

## Status

This document specifies the planned REST API surface. No endpoints exist
yet — the first endpoint (`GET /api/health`) is implemented in **Phase 2**;
the rest arrive incrementally with their owning phases. This is the
contract those phases implement against.

## Conventions

- Base path: `/api`
- JSON request/response bodies.
- Identifiers are UUIDs.
- Requests and responses are validated against Pydantic schemas in
  `backend/app/schemas/` — SQLAlchemy models are never returned directly.
- Standard HTTP status codes: `200` (OK), `201` (Created), `204` (No
  Content on delete), `400` (validation error), `404` (not found), `409`
  (conflict, e.g. duplicate watchlist entry or allocation totals invalid),
  `422` (schema validation, handled automatically by FastAPI/Pydantic).
- Error responses carry a clear, human-readable `detail` message and never
  leak stack traces or internal exception text in non-debug environments.
- Authentication: see "Authentication Boundary" in
  [ARCHITECTURE.md](./ARCHITECTURE.md). Endpoints below are unauthenticated
  only under `DEV_MODE`; this is a documented interim state, not a
  permanent design.

## Planned Endpoints

### Health

```
GET /api/health
```
Returns service status and (once implemented) database connectivity state.

### Assets

```
GET    /api/assets
POST   /api/assets
PATCH  /api/assets/{id}
```

### Portfolio

```
GET /api/portfolio
GET /api/portfolio/summary
GET /api/portfolio/allocation
```
All computed values (total value, P/L, allocation %) are calculated by the
backend domain layer — see [ARCHITECTURE.md](./ARCHITECTURE.md).

### Holdings

```
GET    /api/holdings
POST   /api/holdings
PATCH  /api/holdings/{id}
```

### Transactions

```
GET    /api/transactions
POST   /api/transactions
DELETE /api/transactions/{id}
```

### Settings — Portfolio Config

```
GET   /api/settings/portfolio
PATCH /api/settings/portfolio
```

### Settings — Allocation Targets

```
GET    /api/settings/targets
POST   /api/settings/targets
PATCH  /api/settings/targets/{id}
DELETE /api/settings/targets/{id}
```
Saving targets validates aggregate rules (sum of active target percentages)
in the service layer — see [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).
Invalid totals (over 100%) are rejected with `400`/`409`; under 100% either
warns or requires an explicit "unallocated percentage" acknowledgment —
values are never silently normalized.

### Watchlist

```
GET    /api/watchlist
POST   /api/watchlist
PATCH  /api/watchlist/{id}
DELETE /api/watchlist/{id}
```
Delete is logical (sets `removed_at`), not a physical row delete, per
[DATABASE.md](./DATABASE.md).

### Alerts

```
GET   /api/alerts
POST  /api/alerts
PATCH /api/alerts/{id}
```

### Rebalancing

```
POST /api/rebalancing/calculate
```
Returns recommendations only. Never executes trades.

### Cash Flow / Smart Inflow

```
POST /api/cash-flow/allocate
```
Returns a recommended allocation of new cash across assets/categories, with
a `reason` per recommendation. Never sells; never exceeds `maximum_percent`;
respects `allow_new_buy`; excludes the emergency asset when configured.

## Not Yet Specified

Endpoints for future tables (`cash_flows`, `alert_events`, `market_quotes`,
`scheduled_income`, `users`, `audit_logs`) are deferred until those tables
are introduced (see [DATABASE.md](./DATABASE.md)) and will be documented
here at that time.
