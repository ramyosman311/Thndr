# API

## Status

This document specifies the planned REST API surface. Implemented so far:
`GET /api/health` (**Phase 2**), `GET /api/portfolio/summary` and
`GET /api/portfolio/allocation` (**Phase 5**), and
`GET /api/portfolio/strategy/validation` (**Phase 6**). The rest arrive
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
  "total_portfolio_value": "110000.00",
  "risk_denominator_basis": "investable",
  "risk_denominator_value": "10000.00",
  "emergency_excluded": true,
  "buckets": [
    {
      "strategy_bucket_id": "...", "bucket_name": "Individual Stocks",
      "actual_value": "0.00",
      "total_portfolio_percent": "0.00",     // value / TOTAL portfolio value — always defined
      "risk_allocation_percent": "0.00",     // value / the risk/investable denominator — null if this bucket is excluded from risk allocation
      "target_percent": null, "minimum_percent": null, "maximum_percent": "15.00",
      "allow_new_buy": true,
      "target_status": "NO_TARGET", "minimum_status": "NO_MINIMUM", "maximum_status": "WITHIN_MAXIMUM",
      "buy_allowed": true,
      "excluded_from_risk_allocation": false
    }
  ]
}
```
`buy_allowed` combines the configured `allow_new_buy` flag with whether
`maximum_status` is `MAXIMUM_BREACHED` — reaching a maximum freezes new
buying regardless of the flag, but this field (like the whole endpoint)
only ever reports a status; nothing here sells, buys, or rebalances (see
FINANCIAL_RULES.md, "Rebalancing Engine Rules").

**Two distinct percentages, resolved in Phase 6:** every bucket carries
both `total_portfolio_percent` (bucket value ÷ total portfolio value —
always a well-defined number, for every bucket, including the one holding
the emergency asset) and `risk_allocation_percent` (bucket value ÷ the
risk/investable denominator). The bucket excluded from risk allocation
(the one holding the configured emergency asset, when
`emergency_excluded=true`) gets `risk_allocation_percent: null` and
`excluded_from_risk_allocation: true` instead of a misleading number like
1000% — computing that bucket's own weight against a denominator that
excludes its value is mathematically undefined, so it is reported as
such rather than guessed. `target_status`/`minimum_status`/`maximum_status`
are evaluated against `risk_allocation_percent` and report their "not
applicable" variant (`NO_TARGET`/`NO_MINIMUM`/`NO_MAXIMUM`) when it is
null.

### Strategy Validation

```
GET /api/portfolio/strategy/validation   (implemented, Phase 6)
```
Read-only; never modifies `allocation_targets`, `strategy_buckets`, or
`portfolio_configs`. `404` with a `detail` message if no
`portfolio_configs` row exists yet. Otherwise **always `200`** — an
incomplete or overallocated strategy is a normal, successful response
with a diagnostic status, never a `4xx`/`5xx` for a business-rule
mismatch:

```jsonc
{
  "status": "INCOMPLETE_TARGET_ALLOCATION",
  "is_valid": false,
  "total_target_percent": "85.00",
  "expected_target_percent": "100.00",
  "explanation": "Configured target allocation totals 85.00%, which is below the expected 100%. ...",
  "target_rows": [ /* buckets with a configured target_percent, e.g. Growth/Investment Funds, Gold (target=0) */ ],
  "maximum_only_rows": [ /* buckets with only a maximum_percent, e.g. Individual Stocks — never counted as a target */ ],
  "excluded_emergency_rows": [ /* would list the emergency bucket's rule if it had one; empty in the seeded config */ ],
  "field_errors": [],
  "priority_order": [ /* all participating rules, sorted by priority */ ]
}
```
`status` is one of: `VALID`, `INCOMPLETE_TARGET_ALLOCATION`,
`OVERALLOCATED_TARGET_ALLOCATION`, `EMPTY_CONFIGURATION`,
`INVALID_TARGET_VALUE`, `INVALID_MIN_MAX_CONFIGURATION` — see
FINANCIAL_RULES.md for the exact rule these encode. Only
`target_percent` ever contributes to `total_target_percent`;
`minimum_percent`, `maximum_percent`, and `allow_new_buy` never do. The
engine never auto-corrects a configuration to make it valid — it only
reports.

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
