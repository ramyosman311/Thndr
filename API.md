# API

## Status

This document specifies the planned REST API surface. Implemented so far:
`GET /api/health` (**Phase 2**), `GET /api/portfolio/summary` and
`GET /api/portfolio/allocation` (**Phase 5**),
`GET /api/portfolio/strategy/validation` (**Phase 6**),
`POST /api/cash-flow/allocate` (**Phase 7**), the full Watchlist +
Alerts surface (**Phase 8**), and `GET /api/assets` (**Phase 9**, added
to support the frontend's Watchlist "add asset" picker). The rest arrive
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
GET    /api/assets   (implemented, Phase 9 — read-only)
POST   /api/assets
PATCH  /api/assets/{id}
```
`GET /api/assets` lists active assets (`id`, `symbol`, `name`,
`asset_type`, `currency`, `is_active`) — read-only, reuses the exact same
repository query the Portfolio Engine already uses (never a duplicated
query). Added in Phase 9 to let the frontend's Watchlist "add asset"
picker resolve a symbol to an id, since no such listing existed yet.
`POST`/`PATCH` remain unimplemented — out of Phase 9 scope.

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
  ],
  "total_unrealized_pnl": "1000.00",       // added in Phase 9 — sum of holdings_pnl[].unrealized_pnl
  "total_unrealized_pnl_percent": "11.11"  // null when total cost basis is 0, never fabricated
}
```
All Decimal fields serialize as JSON **strings**, not numbers, so exact
precision survives the API boundary (see FINANCIAL_RULES.md,
"Precision"). Only holdings with `quantity != 0` appear in `holdings_pnl`.
`total_unrealized_pnl`/`total_unrealized_pnl_percent` (Phase 9) aggregate
the already-computed per-holding figures for the dashboard's headline P/L
— see FINANCIAL_RULES.md, "Portfolio-Level P/L Aggregation".

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

### Watchlist (implemented, Phase 8)

```
GET    /api/watchlist                    ?enabled_only=bool
POST   /api/watchlist
PATCH  /api/watchlist/{id}
DELETE /api/watchlist/{id}
GET    /api/watchlist/{id}/alerts
POST   /api/watchlist/{id}/alerts
```
`POST /api/watchlist` — `{"asset_id": "...", "notes": "optional"}` →
`404` if the asset doesn't exist, `409` if it's `is_active=false`, `409`
on a duplicate (asset already actively watched). Re-adding an asset whose
entry was previously removed re-enables that same row instead of creating
a duplicate.

`PATCH /api/watchlist/{id}` — `{"enabled": bool, "notes": "..."}`
(both optional) → `404` if the entry doesn't exist.

`DELETE /api/watchlist/{id}` is **logical** (sets `enabled=false` and
`removed_at`), never a physical row delete, per
[DATABASE.md](./DATABASE.md) — returns the updated entry, `200`.

Response shape (`WatchlistOut`):
```jsonc
{
  "id": "...", "asset_id": "...", "asset_symbol": "TMGH",
  "enabled": true, "notes": "worth watching",
  "added_at": "2026-01-01T00:00:00Z", "removed_at": null,
  "alert_rule": null // or the nested AlertRuleOut below, once configured
}
```

`GET /api/watchlist/{id}/alerts` / `POST /api/watchlist/{id}/alerts` read
or create the single alert rule for that watchlist entry (1:1 —
`409` on a second `POST`). `404` if the watchlist entry doesn't exist;
`GET` also `404`s if no rule has been configured yet.

### Alerts (implemented, Phase 8)

```
PATCH  /api/alerts/{id}
DELETE /api/alerts/{id}
POST   /api/alerts/evaluate
```
`POST /api/watchlist/{id}/alerts` and `PATCH /api/alerts/{id}` accept any
subset of: `enabled`, `allocation_alert_enabled` +
`allocation_max_percent`, `price_target_enabled` + `price_target`,
`dip_buy_enabled` + `dip_buy_price`, `telegram_enabled`. Enabling a check
without its required threshold is rejected with `400`
(`InvalidAlertRuleConfigurationError`) — e.g.
`{"dip_buy_enabled": true}` with no `dip_buy_price` fails; thresholds can
be changed at any time with no code change (dynamic configuration).

Response shape (`AlertRuleOut`):
```jsonc
{
  "id": "...", "watchlist_id": "...", "enabled": true,
  "allocation_alert_enabled": true, "allocation_max_percent": "20.00",
  "price_target_enabled": false, "price_target": null,
  "dip_buy_enabled": false, "dip_buy_price": null,
  "telegram_enabled": false, "last_triggered_at": null
}
```

**`POST /api/alerts/evaluate`** evaluates every enabled alert rule on
every enabled watchlist entry whose underlying asset is `is_active=true`.
Read-only with respect to holdings, transactions, snapshots,
`allocation_targets`, and `portfolio_configs`; the only write is to
`alert_rules.last_triggered_at` (the deduplication latch this endpoint
depends on — see FINANCIAL_RULES.md, "Alert Engine Rules"). Never creates
a transaction, never buys, never sells.

Response (one entry per check actually performed, not just new triggers):
```jsonc
{
  "results": [
    {
      "alert_rule_id": "...", "watchlist_id": "...", "asset_symbol": "TMGH",
      "alert_type": "ALLOCATION_BREACH", // | PRICE_TARGET | DIP_BUY | REBALANCE_SUGGESTED
      "condition_met": true,
      "is_new_trigger": true,   // true only the first evaluation where condition_met flips to true
      "should_clear": false,    // true the first evaluation where a previously-met condition becomes false
      "reason": "allocation 20.00% >= watch threshold 15.00%",
      "current_value": "20.00", "threshold_value": "15.00"
    }
  ]
}
```
`ALLOCATION_BREACH` and `REBALANCE_SUGGESTED` both reuse the Allocation
Engine's own computed `risk_allocation_percent`/`maximum_status`/
`target_status` (Phase 5/6) — this endpoint never recomputes an
allocation percentage itself. They are independent thresholds:
`ALLOCATION_BREACH` fires against this alert rule's own
`allocation_max_percent` watch level; `REBALANCE_SUGGESTED` fires when the
bucket's own configured `allocation_targets.maximum_percent` is breached
or it is `OVERWEIGHT` against its `target_percent` — a personal
early-warning threshold and the strategy's own configured cap are two
different numbers. `REBALANCE_SUGGESTED` is a **suggestion only**: no
sell, no buy, no transaction is ever created from it.

`PRICE_TARGET`/`DIP_BUY` compare against `holdings.current_price` (no
live market-data provider exists yet — see FINANCIAL_RULES.md,
"Market Data Integrity"); a `null` `current_value` means the price is
currently unknown (e.g. no `holdings` row yet), never a fabricated 0.

**Recurring Income Maturity** — a fifth alert category
(`check_income_maturity` in `backend/app/domain/alert_engine.py`) is
implemented and unit-tested at the domain layer, but is **not** wired
into this endpoint: `alert_rules` has no maturity-date/recurrence columns
today. See DATABASE.md, "Known Schema Limitations (Phase 8)" for the
minimal addition this would need.

**Deduplication** is edge-triggered per alert rule row: `is_new_trigger`
is true only the evaluation where a condition just became true;
re-running while it stays true reports `condition_met: true,
is_new_trigger: false` (no repeat notification); once the condition
clears, the next evaluation reports `should_clear: true`, and the
**same** rule can `is_new_trigger` again later if the condition becomes
true again — nothing is ever permanently suppressed. Because
`alert_rules` has a single shared `last_triggered_at` column (not one per
condition type), a rule with more than one check type enabled
simultaneously shares one latch across all of them — see DATABASE.md for
the disclosed limitation and the minimal schema addition that would make
dedup fully independent per condition type.

### Rebalancing

```
POST /api/rebalancing/calculate
```
Returns recommendations only. Never executes trades.

### Cash Flow / Smart Inflow

```
POST /api/cash-flow/allocate   (implemented, Phase 7)
```
Read-only: calculates a recommendation only — never creates a
transaction, never modifies a holding, never executes a trade. `404`
with a `detail` message if no `portfolio_configs` row exists yet; `422`
(standard FastAPI/Pydantic validation) if `amount` is missing, not a
valid decimal, or `<= 0`.

Request:
```json
{ "amount": "1000.00" }
```

Response (values shown are the exact result of running this against the
seeded strategy with a single 1000 EGP TMGH holding as investable value):
```jsonc
{
  "requested_cash": "1000.00",
  "allocated_cash": "850.00",
  "unallocated_cash": "150.00",
  "strategy_status": "INCOMPLETE_TARGET_ALLOCATION",  // reuses the Strategy Engine (Phase 6), not re-validated here
  "strategy_is_valid": false,
  "recommendations": [
    {
      "strategy_bucket_id": "...", "bucket_name": "Growth / Investment Funds",
      "current_value": "0.00", "current_percent": "0.00",
      "target_percent": "55.00", "maximum_percent": null, "allow_new_buy": true, "priority": 1,
      "target_gap": "550.00", "maximum_capacity": null,
      "eligible": true, "allocated_amount": "550.00", "status": "ELIGIBLE",
      "projected_value": "550.00", "projected_percent": "29.73"
    },
    {
      "strategy_bucket_id": "...", "bucket_name": "Individual Stocks",
      "current_value": "1000.00", "current_percent": "100.00",
      "target_percent": null, "maximum_percent": "15.00", "allow_new_buy": true, "priority": 3,
      "target_gap": null, "maximum_capacity": "-850.00",
      "eligible": false, "allocated_amount": "0", "status": "NO_TARGET",
      "projected_value": "1000.00", "projected_percent": "54.05"
    }
    // ... one entry per active strategy bucket
  ]
}
```

**Status codes** (`recommendations[].status`): `ELIGIBLE` (actually
funded this run), `TARGET_GAP` (positive gap, but not funded this run —
cash ran out first), `MAXIMUM_LIMIT` (a configured maximum caps or blocks
capacity), `BUY_DISABLED` (`allow_new_buy=false`), `EMERGENCY_EXCLUDED`,
`NO_TARGET` (no `target_percent` configured — includes maximum-only
buckets like Individual Stocks, which are a constraint, never a
destination), `AT_TARGET`, `OVER_TARGET`, `NO_CAPACITY` (investable value
is zero).

**Denominator:** target gaps and maximum capacities use the investable
portfolio value as it stood *before* this request's cash — the incoming
amount is never added to the denominator before deciding where it goes.
`projected_percent` is a separate, clearly distinct calculation using
investable value plus whatever ended up actually allocated.

**Unallocated cash is never forced into a destination** — see
`FINANCIAL_RULES.md`, "Smart Inflow Allocator Rules" for the full
rounding and ordering rules (priority ascending, then bucket name;
`requested_cash == allocated_cash + unallocated_cash` exactly, even after
presentation rounding).

## Not Yet Specified

Endpoints for future tables (`cash_flows`, `alert_events`, `market_quotes`,
`scheduled_income`, `users`, `audit_logs`) are deferred until those tables
are introduced (see [DATABASE.md](./DATABASE.md)) and will be documented
here at that time. This now includes an income-maturity alert endpoint
(needs `scheduled_income`-like columns) and a per-condition-type alert
event history endpoint (needs `alert_events`) — see DATABASE.md, "Known
Schema Limitations (Phase 8)".
