# API

## Status

This document specifies the planned REST API surface. Implemented so far:
`GET /api/health` (**Phase 2**), `GET /api/portfolio/summary` and
`GET /api/portfolio/allocation` (**Phase 5**),
`GET /api/portfolio/strategy/validation` (**Phase 6**),
`POST /api/cash-flow/allocate` (**Phase 7**), the full Watchlist +
Alerts surface (**Phase 8**), `GET /api/assets` (**Phase 9**, added to
support the frontend's Watchlist "add asset" picker — now also reused by
the Phase 10 transaction form's asset picker), `POST`/`GET
/api/transactions` (**Phase 10**, the Transaction + Holdings write path,
extended in **Phase 15** with DEPOSIT/WITHDRAWAL cash-flow semantics),
the price endpoints under `/api/assets/{id}/price...` (**Phase 11** —
see "Prices" below), and `GET /api/portfolio/analytics/history`
(**Phase 15** — see "Wealth Analytics" below). The rest arrive
incrementally with their owning phases. This is the contract those
phases implement against.

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
Reused unchanged by the Phase 10 transaction form's asset picker — never
duplicated. `POST`/`PATCH` remain unimplemented.

### Portfolio

```
GET /api/portfolio
GET /api/portfolio/summary          (implemented, Phase 5)
GET /api/portfolio/allocation       (implemented, Phase 5)
GET /api/portfolio/rebalancing      (implemented, Phase 17)
GET /api/portfolio/recommendations  (implemented, Phase 18)
```
All computed values (total value, P/L, allocation %) are calculated by the
backend domain layer — see [ARCHITECTURE.md](./ARCHITECTURE.md). All
endpoints below are read-only: calling them never modifies holdings,
transactions, snapshots, or configuration.

**`GET /api/portfolio/summary`** — `404` with a `detail` message if no
`portfolio_configs` row exists yet. Otherwise:

```jsonc
{
  "base_currency": "EGP",
  "total_value": "110000.00",       // "Portfolio Value": emergency_value + available_cash + invested_market_value, always
  "emergency_value": "100000.00",   // "Reserved/Emergency Cash": the one configured emergency asset, if any
  "investable_value": "10000.00",   // ONLY the allocation-% denominator basis — INCLUDES invested market value, NOT spendable cash
  "available_cash": "2000.00",      // Phase 16: "Available/Free Cash" — non-emergency CASH/SAVINGS holdings ONLY. This is what the product calls "Investable Cash"
  "invested_market_value": "8000.00", // Phase 16: investable_value - available_cash — every other non-emergency holding
  "denominator_basis": "investable", // "investable" | "total" — driven by portfolio_configs.emergency_excluded
  "denominator_value": "10000.00",
  "emergency_excluded": true,
  "is_complete": true,          // Phase 11/16: false only when a held asset has no live/stale price AND no same-currency average-cost fallback (see below)
  "unpriced_asset_ids": [],     // asset ids EXCLUDED from the totals above, never counted as 0
  "holdings_pnl": [
    {
      "asset_id": "...", "symbol": "BWA",
      "quantity": "100.00000000", "average_cost": "90.00000000", "asset_currency": "EGP",
      "current_price": "100.00000000",  // null only in the true worst case — no live/stale price AND no fallback (see below)
      "price_status": "LIVE",           // Phase 16: "LIVE" | "PENDING_SYNC" — NOT the same vocabulary as GET .../price (see below)
      "price_recorded_at": "2026-09-10T06:40:15Z",
      "price_is_stale": false,
      "market_value": "10000.00", "cost_basis": "9000.00",
      "unrealized_pnl": "1000.00", "unrealized_pnl_percent": "11.11"
      // market_value is null exactly when current_price is null.
      // unrealized_pnl is null only alongside a null market_value;
      // whenever a price is available it is a real Decimal, forced to
      // exactly 0 when price_status is "PENDING_SYNC" (see below) —
      // never fabricated either way.
    }
  ],
  "total_unrealized_pnl": "1000.00",       // added in Phase 9 — sum of holdings_pnl[].unrealized_pnl (PENDING_SYNC holdings contribute exactly 0)
  "total_unrealized_pnl_percent": "11.11"  // null when total cost basis is 0, never fabricated
}
```
All Decimal fields serialize as JSON **strings**, not numbers, so exact
precision survives the API boundary (see FINANCIAL_RULES.md,
"Precision"). Only holdings with `quantity != 0` appear in `holdings_pnl`.
`total_unrealized_pnl`/`total_unrealized_pnl_percent` (Phase 9) aggregate
the already-computed per-holding figures for the dashboard's headline P/L
— see FINANCIAL_RULES.md, "Portfolio-Level P/L Aggregation". Every price
field here comes from the Phase 11 Price Service (a DB read only — this
endpoint never calls a live provider, so its latency and success are
independent of any provider's — see FINANCIAL_RULES.md, "Non-Blocking
Valuation"); `current_price` is already converted into `base_currency`
when the asset's own currency differs (see "Base Currency & FX
Conversion").

**Phase 16 — six distinct value fields, never interchangeable** (see
FINANCIAL_RULES.md, "Portfolio Value vs Investable Value vs Available
Cash", for the full rationale): `total_value` ("Portfolio Value"),
`emergency_value` ("Reserved/Emergency Cash"), `investable_value` (the
allocation-% denominator basis ONLY — never label this "Investable
Cash" in a UI), `available_cash` (the actual spendable-cash field — this
IS "Investable Cash" in product language), `invested_market_value`, and
`denominator_value`/`denominator_basis` (unrelated to cash). By
construction: `total_value == emergency_value + available_cash +
invested_market_value`, and `investable_value == available_cash +
invested_market_value`.

**Phase 16 — missing-price fallback and `price_status`:** when no
current price exists, a real but stale last-known price is used if one
exists; otherwise the holding's own `average_cost` is used, but only
when the asset's currency matches `base_currency` (never mixing
currencies without an FX rate — see "Base Currency & FX Conversion").
`price_status` on `HoldingPnLOut` reflects this as a simple two-value
signal — `"LIVE"` for a genuinely current price, `"PENDING_SYNC"` for
either fallback case — deliberately simpler than, and NOT to be confused
with, the four-value `PriceStatus` vocabulary `GET /api/assets/{id}/price`
still returns unchanged (`CURRENT_PRICE_AVAILABLE`/`LAST_KNOWN_PRICE`/
`PRICE_UNAVAILABLE`/`CURRENCY_CONVERSION_UNAVAILABLE`). Whenever
`price_status` is `"PENDING_SYNC"`, `unrealized_pnl`/
`unrealized_pnl_percent` are always exactly `0`/`"0.00"` — a P/L
computed from a non-live price is never presented as a confirmed
profit/loss, even though `market_value` still shows the best available
estimate.

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
  "is_complete": true,        // Phase 11 — same meaning as PortfolioSummaryOut.is_complete
  "unpriced_asset_ids": [],
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
      "excluded_from_risk_allocation": false,
      "has_unpriced_positions": false   // Phase 11: true if actual_value excludes an unpriced position
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

No dedicated endpoint — a holding is always the automatic *result* of a
transaction (see below), never directly created or edited. Current
holdings (`quantity`/`average_cost`) are read via `holdings_pnl` in
`GET /api/portfolio/summary` (Phase 5); each entry's price now comes
from the Phase 11 Price Service (see "Prices" below), not from a
`holdings` column. `PATCH /api/holdings/{id}` remains unimplemented —
`quantity`/`average_cost` still can't be set directly (only
transaction-derived), and price is now set instead via
`POST /api/assets/{id}/price/manual` (Phase 11), which only ever writes
a price observation, never a holding field.

### Prices (implemented, Phase 11)

```
GET  /api/assets/{asset_id}/price
GET  /api/assets/{asset_id}/prices
POST /api/assets/{asset_id}/price/manual
POST /api/assets/{asset_id}/price/refresh
```

Every route here is served by `services/price_service.py` reading
`asset_prices` — a pure DB read, **except** `.../price/refresh`, the
one deliberate, user-initiated exception to the non-blocking valuation
rule (see FINANCIAL_RULES.md, "Non-Blocking Valuation"). No route here
exposes provider credentials or lets a client choose an arbitrary
provider/symbol for an asset — that remains configuration
(`asset_price_configs`), not request input.

**`GET /api/assets/{asset_id}/price`** — the asset's current price as
classified by the Price Service.
```jsonc
{
  "asset_id": "...",
  "status": "CURRENT_PRICE_AVAILABLE",  // | "LAST_KNOWN_PRICE" | "PRICE_UNAVAILABLE" | "CURRENCY_CONVERSION_UNAVAILABLE"
  "price": "9.25000000",                // null when status is *_UNAVAILABLE
  "currency": "EGP",
  "provider": "yahoo",
  "provider_symbol": "TMGH.CA",
  "recorded_at": "2026-09-10T06:40:15Z",
  "age_seconds": 300.0,
  "is_stale": false,
  "reason": null                        // set only for an unavailable/conversion-unavailable result
}
```
`404` if the asset doesn't exist. Never `200` with a fabricated price —
an asset with no observation on record returns `status:
"PRICE_UNAVAILABLE"`, `price: null`.

**`GET /api/assets/{asset_id}/prices`** — full observation history for
the asset (`PriceObservationOut[]`, most recent `recorded_at` first;
`?limit=` caps the count, default 100). Read-only.

**`POST /api/assets/{asset_id}/price/manual`** — records a new manual
price observation.
```jsonc
// request
{ "price": "18.75", "currency": "EGP" }   // currency MUST equal the asset's own currency
```
`400` if `currency` doesn't match the asset's own currency, or the
schema-level positive-price check fails (`422`). Returns the same
`PriceOut` shape as `GET .../price`, now reflecting the new
observation (`201`). Never alters any transaction, holding quantity, or
average cost — see FINANCIAL_RULES.md, "Manual Price Never Touches
Transaction History".

**`POST /api/assets/{asset_id}/price/refresh`** — synchronously fetches
this ONE asset's price from its configured provider right now. `409`
if the asset has no `asset_price_configs` row with
`automated_fetching_enabled=true` (nothing to refresh; the asset's last
known price is left untouched). This is the only endpoint in the
entire system allowed to call a live provider inline with a request —
every other read in the app is served purely from `asset_prices`.

### Transactions (implemented, Phase 10)

```
POST /api/transactions
GET  /api/transactions
```
`DELETE /api/transactions/{id}` and `GET /api/transactions/{id}` remain
unimplemented — transactions are immutable historical records (see
FINANCIAL_RULES.md, "Transaction Immutability"); ordinary deletion was
explicitly out of scope for Phase 10.

**`POST /api/transactions`** records an executed BUY/SELL/DEPOSIT/
WITHDRAWAL and atomically updates the resulting holding (average-cost
accounting for BUY/SELL; a pinned 1:1 cash balance for DEPOSIT/
WITHDRAWAL — see FINANCIAL_RULES.md, "Transaction Accounting" and "Cash
Flow Is Not Profit"). This is **not** a recommendation: unlike
`POST /api/cash-flow/allocate` (Smart Inflow), it writes a real,
permanent transaction row and changes the current holding. A DEPOSIT/
WITHDRAWAL additionally creates a post-flow `PortfolioSnapshot` in the
same atomic write (Phase 15 — see DATABASE.md, `portfolio_snapshots`).

Request:
```jsonc
{
  "asset_id": "...",
  "transaction_type": "BUY",   // "BUY" | "SELL" | "DEPOSIT" | "WITHDRAWAL" — see below
  "quantity": "10",
  "price": "100.00",
  "fees": "5.00",              // optional, defaults to "0"
  "transaction_date": "2026-01-01T00:00:00Z",
  "notes": "optional"
}
```
`quantity` must be `> 0`, `price` and `fees` must be `>= 0` — enforced by
Pydantic field validators, `422` on violation. `transaction_type` accepts
`BUY`/`SELL`/`DEPOSIT`/`WITHDRAWAL` (`422` for anything else, including
the model's remaining enum values `DIVIDEND`/`TRANSFER` — those have no
holding-update semantics defined yet and are rejected explicitly rather
than silently doing nothing; see DECISIONS.md, "Phase 15" for why
`TRANSFER` specifically was left unresolved). `DEPOSIT`/`WITHDRAWAL`
additionally require: `asset_id` must reference a `CASH`/`SAVINGS`-type
asset (`422` otherwise), `price` must be exactly `"1"`, and `fees` must
be `"0"` (`422` otherwise) — `quantity` IS the cash amount.

Response (`201`):
```jsonc
{
  "transaction": {
    "id": "...", "asset_id": "...", "asset_symbol": "TMGH", "transaction_type": "BUY",
    "quantity": "10.00000000", "price": "100.00000000", "fees": "5.00",
    "transaction_date": "2026-01-01T00:00:00Z", "notes": "optional", "created_at": "..."
  },
  "holding": {
    "quantity": "10.00000000", "average_cost": "100.50000000",
    "current_price": null, "price_status": "PRICE_UNAVAILABLE"  // Phase 11: from the Price Service, null when no observation exists
  },
  "realized_pnl": null   // a Decimal string for SELL only — see FINANCIAL_RULES.md, "Realized P/L"
}
```
Error responses: `404` if `asset_id` doesn't exist; `409` if a SELL's
quantity exceeds the currently held quantity (including selling an asset
with no holding at all) — the transaction is never recorded in this
case, and the holding is never touched.

**`GET /api/transactions`** returns the full transaction history
(`TransactionOut[]`, no holding-state fields), most recent
`transaction_date` first. Read-only.

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
      "current_value": "20.00", "threshold_value": "15.00",
      "bucket_name": "Individual Stocks"  // Phase 19: additive, null when unknown/no bucket
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

`PRICE_TARGET`/`DIP_BUY` compare against the asset's own native-currency
price from the Phase 11 Price Service (`services/price_service.py`,
batched across every candidate — a DB read only, never a live provider
call within this request). A `null` `current_value` means the Price
Service currently has no usable price for that asset
(`PRICE_UNAVAILABLE`), never a fabricated 0.

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

### Notification Center (implemented, Phase 19)

```
GET   /api/portfolio/notifications
PATCH /api/portfolio/notifications/{id}/read
POST  /api/portfolio/notifications/read-all
```

`GET /api/portfolio/notifications` evaluates the existing alert engine
(`alert_service.evaluate_alerts`, Phase 8) and Smart Recommendations
(`recommendation_service.get_portfolio_recommendations`, Phase 18) —
never recomputing either — persists any newly-triggered/newly-critical
condition as a `Notification` row (deduplicated; see FINANCIAL_RULES.md,
"Notification Layer Rules"), and returns the full, ordered
(newest-first) inbox. Never 404s for an unconfigured portfolio — with
nothing to notify, the list is simply empty.

```jsonc
{
  "unread_count": 2,
  "notifications": [
    {
      "id": "...",
      "category": "RECOMMENDATION_ALERT",  // | ALLOCATION_ALERT | PRICE_ALERT | PORTFOLIO_HEALTH_ALERT (reserved, never emitted)
      "severity": "CRITICAL",              // | WARNING | INFO
      "title": "الأسهم الفردية: تجاوز الحد الأقصى المسموح به",
      "message": "الأسهم الفردية تجاوزت الحد الأقصى المسموح به. يوصى بتقليل الاستثمار بحوالي 500.00.",
      "target_category": "الأسهم الفردية",
      "target_asset": null,
      "action": "REVIEW_RECOMMENDATIONS",  // | REVIEW_DISTRIBUTION | OPEN_ASSET — navigation only, never an execution
      "read": false,
      "created_at": "2026-01-01T10:00:00Z"
    }
  ]
}
```

A `RECOMMENDATION_ALERT` notification's `title`/`message`/`target_category`
are the exact strings/values from the matching `/portfolio/recommendations`
entry (Phase 18) — never reworded. An `ALLOCATION_ALERT`/`PRICE_ALERT`
notification's `title`/`message` are new, additive Arabic copy built from
the matching `/alerts/evaluate` check's own `current_value`/
`threshold_value` (never a new calculation).

**Deduplication is enforced at the database level.** A given underlying
condition (one alert-rule/alert-type pair, or one Phase 18 recommendation
id) can have at most one active (unresolved) notification row at a time —
calling this endpoint any number of times without a real state change
returns the identical set of notifications, never duplicates. Once a
condition clears, a later re-trigger creates a fresh notification (the
same edge-triggered idea `alert_rules.last_triggered_at` already uses).

**`PATCH /api/portfolio/notifications/{id}/read`** marks one notification
read (`404` if the id doesn't exist) — mutates only `notifications.read_at`.
**`POST /api/portfolio/notifications/read-all`** marks every currently
unread notification read and returns the refreshed list
(`unread_count: 0`). Neither endpoint ever creates a transaction, moves
cash, or modifies any holding/allocation-target/strategy-bucket/
portfolio-configuration row — the only mutation, in both cases, is
notification metadata (see FINANCIAL_RULES.md, "Notification Layer
Rules"). No automatic trade execution exists anywhere in this feature.

### Rebalancing (implemented, Phase 17)

```
GET /api/portfolio/rebalancing
```

Superseded an earlier placeholder (`POST /api/rebalancing/calculate`)
that predated implementation — the real endpoint is a `GET` under the
`/portfolio` prefix, alongside `/summary`/`/allocation`, since it is a
pure read/calculate operation with no request body, consistent with
those two. `404` with a `detail` message if no `portfolio_configs` row
exists yet. Otherwise:

```jsonc
{
  "available_cash": "2000.00",         // Phase 16's available_cash — the ONLY source of ordinary BUY funding here
  "total_recommended_buy": "500.00",   // sum of every recommendation's BUY amount; never exceeds available_cash
  "total_recommended_reduce": "8500.00",
  "is_complete": true,
  "recommendations": [
    {
      "strategy_bucket_id": "...", "bucket_name": "Growth",
      "actual_value": "1000.00", "current_percent": "33.33",
      "target_percent": "50.00", "maximum_percent": null,
      "difference_percent": "16.67", "target_value": "1500.00", "difference_value": "500.00",
      "action": "BUY", "recommended_value": "500.00",
      "priority": 1, "allow_new_buy": true,
      "status": "UNDERWEIGHT",
      "reason": "Growth is below its 50.00% target (currently 33.33%). Recommended purchase: 500.00."
    }
  ]
}
```

`action` is one of `BUY`/`REDUCE`/`HOLD`/`NO_CAPACITY`/`NO_TARGET` — a
new, small vocabulary distinct from `status`, which reuses
`TargetStatus`/`MaximumStatus` values verbatim (`MAXIMUM_BREACHED`
included) rather than inventing a second encoding of the same category
state. `recommended_value` is the BUY or REDUCE amount (never both for
the same category) — null for HOLD/NO_CAPACITY/NO_TARGET. `reason` is a
full English sentence generated by the backend (same precedent as
`StrategyValidationOut.explanation`) — the frontend still renders
`action`/`status` as Arabic badges via `lib/status-labels.ts`, but
displays `reason` verbatim.

**Reuses two existing engines rather than reimplementing their math**
(see FINANCIAL_RULES.md, "Rebalancing Engine Rules", and DECISIONS.md,
"Phase 17 — Smart Rebalancing"): the BUY side is literally
`domain/inflow_allocator.calculate_inflow_allocation` (Phase 7, the
Smart Inflow Allocator) fed `available_cash` instead of newly-deposited
cash — same target-gap math, same maximum capping, same
priority-ordered distribution so the same cash is never handed to two
categories at once. The REDUCE side (a category already
`MAXIMUM_BREACHED`, read from the unchanged Phase 5/6
`allocation_engine`) is the one new calculation this phase adds:
`required_reduction = actual_value - maximum_value`. A breached category
is never also considered for a BUY.

**Recommendation only — this endpoint never executes anything.** It
never writes to `transactions`, `holdings`, `allocation_targets`,
`strategy_buckets`, `portfolio_configs`, or any cash balance. Calling it
any number of times, in any order, changes nothing.

### Smart Recommendations (implemented, Phase 18)

```
GET /api/portfolio/recommendations
```

`404` with a `detail` message if no `portfolio_configs` row exists yet
(same as `/rebalancing`, whose loader this endpoint reuses directly).
Otherwise:

```jsonc
{
  "is_complete": true,
  "recommendations": [
    {
      "id": "CASH_DEPLOYMENT:2b1e...",  // deterministic — f"{type}:{bucket_id or 'portfolio'}", never a random UUID
      "type": "CASH_DEPLOYMENT",
      "severity": "INFO",
      "title": "Growth: فرصة لنشر السيولة المتاحة",
      "message": "Growth أقل من نسبتها المستهدفة. يمكن استخدام حوالي 500.00 من النقد المتاح لتقريبها من الهدف.",
      "suggested_action": "BUY",
      "target_category": "Growth",
      "amount": "500.00",   // sourced directly from the matching /rebalancing recommendation's recommended_value — never recomputed
      "evaluated_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

`type` is one unified vocabulary — `BREACH_RESOLUTION` / `CASH_DEPLOYMENT`
/ `REBALANCING_OPPORTUNITY` / `RESTRICTED_ACTION` / `PORTFOLIO_HEALTHY`.
`severity` is `CRITICAL` / `WARNING` / `INFO` / `SUCCESS`. `suggested_action`
is `BUY` / `REDUCE` / `HOLD` / `NO_ACTION`. `title`/`message` are natural,
user-facing Arabic composed by the backend — render verbatim, never
re-derive or translate client-side. `amount`, when present, is always the
exact same number as the corresponding `/rebalancing` recommendation's
`recommended_value` (see FINANCIAL_RULES.md, "Smart Recommendations
Engine Rules" — this endpoint never recalculates a BUY/REDUCE amount).
When no category needs attention, the response is a single
`PORTFOLIO_HEALTHY`/`SUCCESS` recommendation rather than an empty array.

**Reuses the Phase 17 Rebalancing Engine's output directly — this is
not a second rebalancing engine.** `services/recommendation_service.py`
calls `rebalancing_service.load_rebalancing_result()` (the same loader
`/rebalancing` itself calls) and passes its raw domain output into
`domain/recommendation_engine.build_recommendations()`, which only
classifies and composes Arabic text — every target/maximum/allow_new_buy/
priority value and every BUY/REDUCE amount is Phase 17's own, unchanged.

**Recommendation only — this endpoint never executes anything.** Same
read-only guarantee as `/rebalancing`: no transaction, holding,
allocation target, strategy bucket, portfolio configuration, or cash
balance is ever written. Deterministic for a given DB state (excluding
`evaluated_at`, which reflects when the calculation ran) — calling it
repeatedly with no state change returns identical `id`/`type`/`amount`
values every time.

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
  "is_complete": true,   // Phase 11: false if the investable value above excludes an unpriced position
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

## Administration (Phase 12)

Safe CRUD/activate-deactivate endpoints over configuration that
previously required a direct DB write. Every route here is
config-only: none computes a valuation, calls a `PriceProvider`, or
duplicates a rule owned by `strategy_service.py`/`price_service.py`.
Backend validation is authoritative in all cases — the frontend never
independently re-implements these checks.

### Assets

```
GET    /api/assets?include_inactive=false
POST   /api/assets
GET    /api/assets/{asset_id}
PATCH  /api/assets/{asset_id}
POST   /api/assets/{asset_id}/activate
POST   /api/assets/{asset_id}/deactivate
DELETE /api/assets/{asset_id}
```

`POST`/`PATCH` reject an unregistered `asset_type`, a blank `name`, an
invalid currency code, and a `strategy_bucket_id` that doesn't exist
(422/404). `PATCH` additionally rejects a `currency` change on an asset
that already has any transaction or price-observation history (409) —
changing an asset's currency after real financial history exists would
silently reinterpret that history. `DELETE` performs a **hard** delete
only when the asset has no holdings, transactions, watchlist entry,
snapshot items, or price observations; otherwise it returns 409 and the
caller is expected to deactivate instead (see FINANCIAL_RULES.md, "Asset
Deletion Policy").

### Asset Price Configuration

```
GET /api/assets/{asset_id}/price-config
PUT /api/assets/{asset_id}/price-config
```

`GET` always returns 200 (never 404) with `configured: false` and null
fields when no config row exists yet, so the frontend can render a form
immediately. `PUT` validates `primary_provider`/`secondary_provider`
against the actual registered provider registry (`providers/registry.py`)
— an unregistered provider name is rejected with 400, never silently
accepted. `automated_fetching_enabled=true` requires a `primary_provider`
to already be set. `stale_threshold_minutes` must be a positive integer
(422 otherwise). This endpoint only ever writes to `asset_price_configs`
— never to `asset_prices` — and never calls a provider.

### Portfolio Configuration

```
GET   /api/portfolio/config
POST  /api/portfolio/config
PATCH /api/portfolio/config
```

`POST` creates the (currently singleton) portfolio configuration; 409 if
one already exists. `PATCH` rejects an invalid currency code (422) and
an `emergency_asset_id` that doesn't reference a real asset (400). A
`base_currency` change is rejected with 409 the moment **any** transaction
exists anywhere in the system — see FINANCIAL_RULES.md, "Base Currency
Change Policy" — while every other field (name, emergency asset,
emergency exclusion, `telegram_enabled`) remains freely editable
regardless. `telegram_enabled` (Phase 14) is the portfolio-level master
switch gating Telegram delivery — see FINANCIAL_RULES.md, "Telegram
Delivery (Phase 14)"; this field existed since Phase 3 but only gained
an admin write path in Phase 14.

### Strategy Buckets and Allocation Targets

```
GET   /api/strategy/buckets?include_inactive=false
POST  /api/strategy/buckets
PATCH /api/strategy/buckets/{bucket_id}
POST  /api/strategy/buckets/{bucket_id}/activate
POST  /api/strategy/buckets/{bucket_id}/deactivate

GET   /api/strategy/targets?include_inactive=false
POST  /api/strategy/targets
PATCH /api/strategy/targets/{target_id}
```

A duplicate bucket name, or a second allocation target for a bucket
that already has one, returns 409. Percent fields are validated to the
same 0–100 range and `minimum ≤ maximum` relationship already enforced
by the DB's own CHECK constraints (422 on violation) — this is a
deliberate, narrow validation surface: **these endpoints never check
whether the portfolio's allocation totals 100%.** That aggregate
question remains exclusively `GET /api/portfolio/strategy/validation`'s
job (see "Strategy Engine" above); saving an incomplete or currently-
invalid-in-aggregate configuration always succeeds here and is reported,
never blocked or silently auto-corrected — see FINANCIAL_RULES.md,
"Strategy Validation Ownership".

## Wealth Analytics (Phase 15)

```
GET /api/portfolio/analytics/history?range=1M
```

Read-only. `range` is one of `1W`/`1M`/`3M`/`YTD`/`ALL` (default `1M`;
`422` for anything else). Derived exclusively from persisted
`PortfolioSnapshot` rows — never computed from today's live holdings,
never interpolated/extrapolated (see FINANCIAL_RULES.md, "Phase 15").
`404` if no portfolio configuration exists yet.

Response (`200`):
```jsonc
{
  "range": "1M",
  "base_currency": "EGP",
  "data": [
    {
      "date": "2026-09-01",
      "portfolio_value": "125000.00",
      "invested_capital": "110000.00",
      "total_pnl": "15000.00",
      "twr_percentage": "4.82"   // null when TWR is undefined up to this point — never a fabricated 0
    }
  ],
  "insufficient_history": false,
  "message": null
}
```
When fewer than two eligible historical observations exist for the
requested range, `data` is `[]` and `insufficient_history` is `true`
with an explanatory `message` — the frontend must render this as an
explicit "insufficient data" state, never as an empty/flat chart. Only
snapshots created under the Phase 15 lifecycle (i.e. with
`invested_capital` recorded) are eligible — the five original dev-seed
snapshots are excluded rather than assigned a guessed `invested_capital`
of `0`. No database IDs, `trigger_source`, or other internal metadata
are ever included in the response.

## Not Yet Specified

Endpoints for future tables (`cash_flows`, `alert_events`,
`scheduled_income`, `users`, `audit_logs`) are deferred until those tables
are introduced (see [DATABASE.md](./DATABASE.md)) and will be documented
here at that time. This now includes an income-maturity alert endpoint
(needs `scheduled_income`-like columns) and a per-condition-type alert
event history endpoint (needs `alert_events`) — see DATABASE.md, "Known
Schema Limitations (Phase 8)". (`market_quotes` was in this list through
Phase 10; Phase 11 implemented it as `asset_price_configs`/
`asset_prices`/`fx_rates` — see "Prices" above.)
