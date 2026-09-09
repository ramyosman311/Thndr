# API

## Status

This document specifies the planned REST API surface. Implemented so far:
`GET /api/health` (**Phase 2**), `GET /api/portfolio/summary` and
`GET /api/portfolio/allocation` (**Phase 5**). The rest arrive
incrementally with their owning phases. This is the contract those phases
implement against.

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
GET /api/portfolio/summary   (implemented, Phase 5)
GET /api/portfolio/allocation (implemented, Phase 5)
```
All computed values (total value, P/L, allocation %) are calculated by the
backend domain layer — see [ARCHITECTURE.md](./ARCHITECTURE.md). Both
endpoints are read-only: calling them never modifies holdings,
transactions, snapshots, or configuration.

**`GET /api/portfolio/summary`** — `404` with a `detail` message if no
`portfolio_configs` row exists yet. Otherwise:

```jsonc
{
  "base_currency": "EGP",
  "total_value": "110000.00",       // emergency_value + investable_value, always
  "emergency_value": "100000.00",
  "investable_value": "10000.00",
  "denominator_basis": "investable", // "investable" | "total" — driven by portfolio_configs.emergency_excluded
  "denominator_value": "10000.00",
  "emergency_excluded": true,
  "holdings_pnl": [
    {
      "asset_id": "...", "symbol": "BWA",
      "quantity": "100.00000000", "average_cost": "90.00000000", "current_price": "100.00000000",
      "market_value": "10000.00", "cost_basis": "9000.00",
      "unrealized_pnl": "1000.00", "unrealized_pnl_percent": "11.11"
      // unrealized_pnl_percent is null when cost_basis is 0 (division is
      // undefined, never fabricated) — see FINANCIAL_RULES.md.
    }
  ]
}
```
All Decimal fields serialize as JSON **strings**, not numbers, so exact
precision survives the API boundary (see FINANCIAL_RULES.md,
"Precision"). Only holdings with `quantity != 0` appear in `holdings_pnl`.

**`GET /api/portfolio/allocation`** — same `404` behavior. Otherwise, one
entry per active strategy bucket (all of them — a bucket with no
allocation rule still appears, with `NO_TARGET`/`NO_MINIMUM`/`NO_MAXIMUM`
and `allow_new_buy: null`):

```jsonc
{
  "denominator_basis": "investable",
  "denominator_value": "10000.00",
  "emergency_excluded": true,
  "buckets": [
    {
      "strategy_bucket_id": "...", "bucket_name": "Individual Stocks",
      "actual_value": "0.00", "actual_percent": "0.00",
      "target_percent": null, "minimum_percent": null, "maximum_percent": "15.00",
      "allow_new_buy": true,
      "target_status": "NO_TARGET", "minimum_status": "NO_MINIMUM", "maximum_status": "WITHIN_MAXIMUM",
      "buy_allowed": true
    }
  ]
}
```
`buy_allowed` combines the configured `allow_new_buy` flag with whether
`maximum_status` is `MAXIMUM_BREACHED` — reaching a maximum freezes new
buying regardless of the flag, but this field (like the whole endpoint)
only ever reports a status; nothing here sells, buys, or rebalances (see
FINANCIAL_RULES.md, "Rebalancing Engine Rules").

**Known caveat:** a bucket excluded from the allocation denominator (e.g.
"Emergency Cash" when `emergency_excluded=true`) still gets an
`actual_percent` computed against that same (smaller) denominator, which
can read as more than 100%. This is mathematically consistent with the
documented formula — the exclusion only ever changes the denominator used
for *other* buckets' percentages — and is harmless in practice because
such a bucket has no `allocation_targets` row to compare against
(`NO_TARGET`/`NO_MINIMUM`/`NO_MAXIMUM`), so no status is ever misjudged
from it.

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
