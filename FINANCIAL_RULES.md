# Financial Rules

## Status

This document specifies the financial domain rules the backend `domain/`
layer must implement (Phases 5–11). This is the specification those
phases are built and tested against.

## Core Principle: Database Is the Source of Truth

No allocation percentage, asset limit, or investment rule is hardcoded in
application code.

**Forbidden pattern:**

```
BWA_TARGET = 55
AZN_TARGET = 25
STOCK_LIMIT = 15
```

**Required pattern:** every such value is a row in `allocation_targets` or
`portfolio_configs`, read at runtime, editable via Settings. See
[DATABASE.md](./DATABASE.md).

## Target Allocation vs. Maximum Allocation vs. Allow New Buy

These are three **independent** settings per allocation category. None may
be derived from another.

| Concept | Meaning |
|---|---|
| **Target Allocation** | The long-term desired weight of a category. Used by rebalancing to measure deviation. |
| **Maximum Allocation** | A hard ceiling. Never exceeded by any recommendation, regardless of target. |
| **Allow New Buy** | Whether the Smart Inflow engine is permitted to allocate new cash into this category at all. |

**`maximum` is never assumed to equal `target`.** Example:

```
Individual Stocks:
  target = NULL         (no single long-term target weight; capped by max only)
  maximum = 15
  allow_new_buy = true

Gold:
  target = 0
  allow_new_buy = false  (even though target is 0, this is a separate flag)
```

A category can have `target = 0` and `allow_new_buy = false` (no new
buying) while still holding an existing position that must not be sold
(the engines never sell — see Smart Inflow Rules below).

## Allocation Target Validation

The sum of active `target_percent` values across `allocation_targets` must
be validated whenever settings are saved.

- This validation happens in the **service/domain layer**
  (`backend/app/domain/strategy_validation.py`, implemented in Phase 6),
  not solely via a database CHECK constraint — PostgreSQL cannot enforce
  an aggregate SUM constraint across rows with a simple column-level
  CHECK.
- If active targets **exceed 100%**, the configuration is
  `OVERALLOCATED_TARGET_ALLOCATION`.
- If active targets are **below 100%**, the configuration is
  `INCOMPLETE_TARGET_ALLOCATION` — values are **never silently
  normalized** to sum to 100%, and a maximum-only rule (e.g. Individual
  Stocks) is **never** treated as an implied target to close the gap.
- If no active, risk-participating rules exist at all, the configuration
  is `EMPTY_CONFIGURATION`.
- A structurally invalid rule (a percent outside `[0, 100]`, or
  `minimum_percent > maximum_percent`) is `INVALID_TARGET_VALUE` /
  `INVALID_MIN_MAX_CONFIGURATION` respectively, and takes priority over
  the aggregate diagnosis.
- Only `target_percent` is ever summed. `minimum_percent`,
  `maximum_percent`, and `allow_new_buy` never contribute to the sum —
  this is enforced structurally in the validator, not just by convention.
- The engine **only ever reports** a validation status
  (`GET /api/portfolio/strategy/validation`, `200` even when invalid —
  see API.md). It never auto-corrects a configuration: it does not change
  85% to 100%, does not convert a `maximum_percent` into a
  `target_percent`, and does not invent a missing target. Example: the
  seeded strategy (BWA 55% + AZN 25% + Free Cash 5% + Gold 0% = 85%,
  Individual Stocks maximum=15% contributing nothing) is reported as
  `INCOMPLETE_TARGET_ALLOCATION` at 85%, not silently treated as complete.
- A bucket holding the configured emergency asset is excluded from this
  validation entirely when `emergency_excluded=true` — determined via the
  `portfolio_configs.emergency_asset_id` → `assets.strategy_bucket_id`
  relationship, never by bucket name.

## Portfolio-Level P/L Aggregation

Implemented in `backend/app/domain/pnl_engine.py`'s
`calculate_portfolio_pnl_totals` (Phase 9). The Portfolio Dashboard needs
a single headline P/L figure, not just the per-holding breakdown
`calculate_holding_pnl` already produces — this function sums those
already-computed values, it never re-derives P/L itself:

- `total_market_value`, `total_cost_basis`, `total_unrealized_pnl` are
  plain Decimal sums across holdings.
- `total_unrealized_pnl_percent` is `total_unrealized_pnl /
  total_cost_basis * 100` — `None` (never a fabricated number) when the
  total cost basis is 0, the same "undefined denominator" rule already
  used per-holding.
- A holding with an undefined (`None`) P/L is **excluded** from the sums
  entirely, never counted as contributing 0 — that would silently
  understate the total for genuinely incomplete data instead of
  reporting the gap honestly.

This was added specifically so the frontend (Phase 9) never computes an
aggregate P/L itself in TypeScript — see ARCHITECTURE.md, "no P/L,
allocation, or rebalancing math is computed in React."

## Risk Allocation vs. Total Portfolio Percentage

Every bucket's allocation is reported with two distinct percentages
(`backend/app/domain/allocation_engine.py`, Phase 5/6):

- **`total_portfolio_percent`** — bucket value ÷ total portfolio value.
  Always well-defined, for every bucket, including the one holding the
  emergency asset.
- **`risk_allocation_percent`** — bucket value ÷ the risk/investable
  denominator (the same denominator described in "Emergency Cash" below).
  This is `null` — never a misleading number like 1000% — for the bucket
  excluded from risk allocation, since computing that bucket's own weight
  against a denominator that excludes its value is mathematically
  undefined, not merely large.

`target_status`/`minimum_status`/`maximum_status` are evaluated against
`risk_allocation_percent`; when it is `null` they report their "not
applicable" variant (`NO_TARGET`/`NO_MINIMUM`/`NO_MAXIMUM`) rather than
guessing.

## Emergency Cash

Any asset may be designated the **Emergency/Savings Asset** via
`portfolio_configs.emergency_asset_id`. This is a user-configurable
setting, never a hardcoded symbol check (e.g. never `if symbol == "Cloudz"`).

When `portfolio_configs.emergency_excluded = true`, the emergency asset's
value is **excluded** from:

- Risk Allocation calculations
- Investment Allocation calculations
- Rebalancing calculations
- Smart Inflow calculations

The emergency asset's value **remains visible** in the application UI,
labeled as **"النقد الاحتياطي"** (reserve/emergency cash) — it is hidden
from allocation math, not from the user.

## Smart Inflow Allocator Rules

Implemented in `backend/app/domain/inflow_allocator.py` (Phase 7).
**Smart Inflow Allocator ≠ Rebalancing Engine**: it only answers "if I
receive X EGP of new cash, where should it go?" — never "how should
existing holdings be sold to reach target?" It never sells, never
executes a trade, and never modifies holdings, targets, or configuration;
calling it is fully read-only (verified directly — row counts before and
after are identical).

**Inputs:** new cash amount (`Decimal`, must be `> 0`), the CURRENT
investable portfolio value (from the Portfolio Engine, Phase 5 — the
denominator used is the same `denominator_value` the Portfolio/Allocation
Engines already compute, so this never duplicates that logic), and one
`InflowCandidate` per active strategy bucket (current value,
target/maximum percent, `allow_new_buy`, priority, and whether it holds
the excluded emergency asset).

**Denominator treatment — the incoming cash is never added to the
denominator before target gaps are computed.** Target gaps and maximum
capacities are calculated against the investable value as it stood
*before* the new cash arrived; only after deciding where money goes is an
optional "projected" percentage computed, using investable value plus
whatever was actually allocated (never the requested amount, and never
the unallocated remainder — cash that wasn't placed anywhere doesn't
join any bucket's total).

**Eligibility and status, in this order** (see `InflowStatus` in
`inflow_allocator.py`):

1. The bucket holding the configured emergency asset (when
   `emergency_excluded=true`) → `EMERGENCY_EXCLUDED`, zero allocation,
   and no misleading percentage (its `current_percent` is `null`, not a
   number computed against a denominator that excludes it — same
   principle as the Phase 6 risk-allocation fix).
2. Zero/negative investable portfolio value → `NO_CAPACITY` (nothing to
   compute a gap against).
3. No `target_percent` configured at all → `NO_TARGET`. This is the
   **maximum-only case** (e.g. Individual Stocks: maximum=15%, no
   target): it is treated purely as a constraint, never a destination —
   no target is ever invented for it, even when well under its maximum.
4. `allow_new_buy = false` → `BUY_DISABLED`, regardless of any gap.
5. `target_gap = target_value - current_value <= 0` → `AT_TARGET`
   (exactly zero) or `OVER_TARGET` (negative); zero allocation either way.
6. A configured `maximum_percent` further caps the usable capacity: if
   `remaining_capacity = maximum_value - current_value <= 0` →
   `MAXIMUM_LIMIT`, zero allocation ("maximum already reached" and
   "maximum breached" both land here); if it's positive but less than
   the raw target gap, capacity is capped at `remaining_capacity` and
   still labeled `MAXIMUM_LIMIT`.
7. Otherwise the bucket has positive capacity, labeled `TARGET_GAP`.

**Allocation order:** eligible buckets (positive capacity) are sorted by
the configured `priority` ascending (lower number = higher priority),
then by `bucket_name` as a deterministic, data-driven tiebreaker — never
a hardcoded "this asset always wins." Cash is handed out greedily in that
order until either the cash runs out or every eligible bucket's capacity
is exhausted. A bucket that had positive capacity but didn't receive
money this run (cash ran out before its turn) keeps its `TARGET_GAP`/
`MAXIMUM_LIMIT` status rather than being relabeled — only a bucket that
actually received `allocated_amount > 0` is reported `ELIGIBLE`.

**Unallocated cash is never forced into a destination.** If eligible
target gaps and maximum capacities can't absorb the full requested
amount, the remainder is returned as `unallocated_cash` — never pushed
into Emergency Cash, Gold, or a maximum-only bucket just to make the
total add up. `requested_cash == allocated_cash + unallocated_cash`
holds exactly (Decimal arithmetic; presentation-layer rounding for
`allocated_cash` uses cumulative rounding across buckets so the rounded
amounts still sum exactly, and `unallocated_cash` is derived as
`requested - allocated` after rounding rather than rounded
independently, so the visible total never drifts by a rounding cent).

**Strategy validation is reused, not duplicated:** the allocator calls
the Strategy Engine's `validate_strategy` (Phase 6) directly and reports
its `status`/`is_valid` alongside the recommendations. The current seeded
strategy (targets summing to 85%) is reported as
`INCOMPLETE_TARGET_ALLOCATION` in the same response that still correctly
allocates cash to BWA, AZN, and Free Cash — the allocator never invents a
destination for the missing 15%, and never waits for the strategy to be
"complete" before doing its job on the buckets that are configured.

## Alert Engine Rules

Implemented in `backend/app/domain/alert_engine.py` (Phase 8), orchestrated
by `backend/app/services/alert_service.py`. Evaluates configured Watchlist
+ Alert Rule conditions against explicit, already-computed inputs — it is
**pure**: no I/O, no database session, no HTTP, no Telegram send, and it
never executes a trade.

**Five alert categories** (`AlertType`): `ALLOCATION_BREACH`,
`PRICE_TARGET`, `DIP_BUY`, `REBALANCE_SUGGESTED`, `INCOME_MATURITY`.

- **Allocation Breach and Rebalancing Suggestion reuse the Allocation
  Engine, never recompute it.** Both accept the already-computed
  `risk_allocation_percent`/`maximum_status`/`target_status` produced by
  `allocation_engine.evaluate_bucket_allocation` (Phase 5/6) — this module
  never calculates `current_value / portfolio_value` itself. The two
  checks use **independent thresholds**: `ALLOCATION_BREACH` compares
  against the alert rule's own `allocation_max_percent` (a personal
  early-warning level the user sets on the watchlist entry);
  `REBALANCE_SUGGESTED` compares against the bucket's own configured
  `allocation_targets.maximum_percent`/`target_percent` (the strategy's
  actual cap/target) — reaching one does not imply the other.
- **A rebalance suggestion is a suggestion, never a trade.** Per the
  Phase 8 approval: "A suggestion is NOT an automatic trade. No selling.
  No buying. No transaction creation." The result carries no field that
  could represent a sell, a buy, or a transaction — verified directly
  (`test_rebalance_suggestion_is_a_suggestion_only_no_trade_fields`,
  `test_evaluate_rebalance_suggestion_is_a_suggestion_never_a_trade`).
- **Price Target and Dip Buy take `current_price` as an explicit input**
  (in practice, sourced from the Phase 11 Price Service —
  `services/price_service.get_prices_for_assets`, the same DB-only,
  non-blocking read every other valuation path uses — not the legacy,
  no-longer-written `holdings.current_price` column; this note was
  corrected in Phase 14 to match the Phase 11 rewiring, which had made
  it stale). No live market-data provider is invented for this: see
  "Market Data Integrity" above. A `None`/unknown price means the check
  reports `condition_met: false, reason: "current price unknown"` —
  never a fabricated value.
- **Recurring Income Maturity is prepared but not wired to persistence.**
  `check_income_maturity` is a pure, fully tested standalone function
  (maturity date vs. a lookahead window), but no `alert_rules` column
  exists to configure it against a real watchlist entry yet — see
  DATABASE.md, "Known Schema Limitations (Phase 8)".
- **Deduplication is edge-triggered, never a permanent suppression.**
  Each check receives `previously_triggered: bool` (derived from whether
  `alert_rules.last_triggered_at` is currently set) and returns
  `is_new_trigger` (the condition just became true — the one moment a
  notification should fire) and `should_clear` (the condition just
  became false, re-arming the rule). The same condition can trigger
  again later after clearing — verified directly
  (`test_dedup_clears_and_can_re_trigger_after_condition_becomes_true_again`).
  Because `alert_rules` has one shared `last_triggered_at` column per
  row rather than one per condition type, a rule with more than one
  check enabled simultaneously shares a single latch across all of them
  — a disclosed simplification, not silently hidden (see DATABASE.md).
- **Watchlist + alert evaluation never modify financial positions.**
  Evaluating alerts (`POST /api/alerts/evaluate`) writes only to
  `alert_rules.last_triggered_at`; it never touches `holdings`,
  `transactions`, `portfolio_snapshots`, `allocation_targets`, or
  `portfolio_configs` — verified directly (row counts before/after are
  identical across repeated evaluation runs). Watchlist CRUD
  (add/remove/enable/disable an entry, create/update/delete a rule) is
  ordinary configuration management, not a read-only engine, and is
  expected to write to `watchlist`/`alert_rules` only.
- **Only an active, enabled watchlist entry with an enabled alert rule is
  ever evaluated.** A disabled watchlist entry, a disabled alert rule, or
  an asset with `is_active=false` is excluded from
  `POST /api/alerts/evaluate` — never silently evaluated as if still
  live.
- **Notification delivery is a separate concern.** The alert engine's
  job ends at "this condition is newly triggered"; a
  `NotificationDispatcher` abstraction (`backend/app/services/
  notification_dispatcher.py`, Phase 8) is called only for new triggers.
  Domain code (`domain/alert_engine.py`) never imports or calls a
  dispatcher directly — evaluation semantics are completely unchanged by
  Phase 14. A real delivery mechanism now exists
  (`TelegramNotificationDispatcher`, Phase 14, see "Telegram Delivery"
  below), but `NullNotificationDispatcher` remains the default whenever
  the caller passes no notifier — which the user-facing
  `POST /api/alerts/evaluate` route always does, so an on-demand
  evaluation request never depends on a live Telegram call.

### Telegram Delivery (Phase 14)

Real delivery exists but is deliberately never reachable from the
on-demand API route — see ARCHITECTURE.md, "Workers" and DECISIONS.md,
"Telegram Delivery Decision" for the full design. Summary:

- **Out-of-band only.** The only code path that ever constructs a
  live-HTTP-capable `TelegramNotificationDispatcher` is
  `app/workers/alert_notify.py`, a standalone script meant to be invoked
  periodically by an external scheduler (cron, a platform's
  scheduled-job feature) — never started by, or run inside, the
  FastAPI/Uvicorn process, exactly mirroring `app/workers/
  price_refresh.py`'s (Phase 11) existing execution model. This project
  has no in-repo scheduling infrastructure (no APScheduler, no Celery
  beat); none was added — the worker script is the minimum mechanism,
  identical in shape to the already-accepted price-refresh precedent.
- **Strict three-condition AND-gate**, checked in
  `alert_service.evaluate_alerts` regardless of which concrete notifier
  was supplied: (1) `TELEGRAM_ENABLED` plus both `TELEGRAM_BOT_TOKEN`/
  `TELEGRAM_CHAT_ID` actually set (deployment-level), (2)
  `portfolio_configs.telegram_enabled` (portfolio master switch), (3)
  `alert_rules.telegram_enabled` (per-rule opt-in). Any one false or
  missing means no delivery — a rule cannot receive Telegram messages
  merely because the portfolio switch is on, and vice versa.
- **A dispatch failure can never break evaluation.**
  `TelegramNotificationDispatcher.dispatch()` catches every failure mode
  (timeout, network error, non-200 HTTP, malformed JSON, a Telegram
  `{"ok": false}` response) internally and never raises; the call site
  in `evaluate_alerts` wraps it in a second try/except regardless, so
  even a future/alternate dispatcher implementation that didn't follow
  this contract still cannot break the alert-evaluation response.
- **The bot token is never logged, never in an exception message, never
  returned to any caller.** It is embedded only in the outbound request
  URL (Telegram's own API design); every log line references only the
  watchlist id, an HTTP status code, or Telegram's own non-secret
  `description` field.
- **Message content uses only fields that exist.** No "Change"/"Change
  %" line is included — no such field exists anywhere in
  `AlertCheckResult` or the Price Service, and none was invented for
  this feature (see `domain/notification_formatting.py`'s own
  docstring). The message uses `alert_type` (as a display label) and
  `reason` (already a complete, human-readable sentence produced by the
  pure domain check functions above), plus the asset symbol and the
  notification's own send timestamp.

## Transaction Accounting (Phase 10)

Implemented in `backend/app/domain/transaction_engine.py`, orchestrated by
`backend/app/services/transaction_service.py`. Makes `holdings` a fully
transaction-derived table: every BUY/SELL updates it deterministically,
and the existing Portfolio/P/L/Allocation Engines (Phase 5/6) see the
result automatically — Phase 10 introduces no second portfolio
calculation engine.

**Average-cost accounting, not FIFO/LIFO.** This module never tracks
individual purchase lots. It blends every purchase into one running
average cost per asset:

```
gross_cost = purchase_quantity * purchase_price
total_cost = gross_cost + fees                       # fees increase cost basis
new_quantity = current_quantity + purchase_quantity
new_cost_basis = (current_quantity * current_average_cost) + total_cost
new_average_cost = new_cost_basis / new_quantity
```

**SELL removes the sold quantity's cost at the *current* average cost**
— never at the sale price, never via FIFO/LIFO lot selection:

```
cost_removed = sell_quantity * current_average_cost
remaining_quantity = current_quantity - sell_quantity
remaining_cost_basis = (current_quantity * current_average_cost) - cost_removed
remaining_average_cost = remaining_cost_basis / remaining_quantity   # 0 when remaining_quantity == 0
```
Under this method the average cost of the remaining position is
mathematically unchanged by a partial sale — removing a proportional
slice of cost basis at the same per-unit cost cannot change the per-unit
cost of what's left. `transaction_engine.py` computes this explicitly
(rather than just carrying the old value over) so the invariant is
directly testable, and so a full sale lands on exactly `0` rather than a
value that merely happens to be very close to it.

**Oversell is rejected outright, before anything is written.** A SELL
whose `quantity` exceeds the currently held quantity (including selling
an asset with no holding row at all) raises before either the
`transactions` insert or the `holdings` update happens — the API returns
`409` and neither row is touched. There is no partial-fill behavior.

**Fees are never silently dropped.** BUY fees increase cost basis (shown
above); SELL fees reduce the immediate realized proceeds:

```
sale_proceeds_net_of_fees = (sell_quantity * sell_price) - fees
realized_pnl = sale_proceeds_net_of_fees - cost_removed
```

**Realized P/L is computed, never persisted as a ledger, and never mixed
with unrealized P/L.** `realized_pnl` is returned only in the response of
the specific SELL request that produced it (`POST /api/transactions`) —
it is not written to any column, and there is no running "total realized
P/L" anywhere in the schema. Unrealized P/L (`pnl_engine.py`, Phase 5)
is calculated independently, from the *resulting* holding's average cost
and a separately-supplied current price, exactly as before Phase 10 — a
SELL's realized result never feeds into it.

**Transactions are immutable.** `transactions` rows are never updated or
deleted by this feature. There is no correction/reversal mechanism in
Phase 10; a mis-entered transaction has no undo — this is a disclosed
limitation, not an oversight.

**Transaction Atomicity.** One `POST /api/transactions` call performs
exactly one `session.commit()` covering both the new `transactions` row
and the `holdings` row it updates (or creates, on a first BUY) — they are
the same database transaction, so they always succeed or fail together.
There is no state where a transaction is recorded without its holding
update, or vice versa.

**Transaction Concurrency.** Two concurrent BUY/SELL requests against the
*same* asset are serialized with `SELECT ... FOR UPDATE` on the existing
holding row: the second request's read blocks until the first commits,
so it always sees the post-first-transaction quantity — never a stale
value that could let two concurrent sells both succeed against the same
5 shares. Verified directly by firing two simultaneous SELL requests for
more than half the held quantity each: exactly one succeeds, the other
receives a `409` computed against the already-updated quantity, and the
final quantity is never negative. A brand-new asset's *first* BUY has no
existing row to lock; two fully concurrent first-BUY requests for the
same asset are resolved by `holdings`' `UNIQUE (asset_id)` constraint
(Phase 3) — one succeeds, the other fails outright rather than silently
creating a duplicate or corrupting state. This was judged a sufficient,
proportionate safeguard for a single-user application; a busier
multi-writer system would warrant a retry-on-conflict wrapper, which
Phase 10 does not add (no evidence it's needed yet).

**Current Price Is Not Set By Transactions.** The current price used for
valuation is a separate concept from `transaction.price` (the actual
executed price) — see "Snapshot ≠ Transaction" for the analogous
principle applied to snapshots. A BUY/SELL updates only `quantity` and
`average_cost`; it never writes a price anywhere. **As of Phase 11**,
current price is obtained from `services/price_service.py` (see "Price
Infrastructure (Phase 11)" below), not from `holdings.current_price`
(now dead/unread — see DATABASE.md). A holding with no usable price
reports `market_value: null`/`unrealized_pnl: null` (via
`price_status: "PRICE_UNAVAILABLE"`) rather than the pre-Phase-11
behavior of a fabricated `0`/`-cost_basis` — see "Never Fabricate A
Price" below. A price can be obtained either automatically (background
refresh from a configured provider) or manually
(`POST /api/assets/{id}/price/manual`).

**Storage precision boundary.** `holdings.average_cost` is `NUMERIC(20, 8)`
(Phase 3). `new_average_cost`/`remaining_average_cost` are computed as
exact Decimal divisions in `transaction_engine.py` and are not rounded
there — but a quotient that doesn't terminate within 8 decimal places
(e.g. `1600 / 15`) is rounded to 8 places by PostgreSQL itself when the
value is persisted, the same way any other value stored in this column
already is. The API always returns the value as actually stored (the
service re-reads the row after commit), never the pre-storage
full-precision Python result — so what a client sees always matches what
a subsequent read would show.

## Rebalancing Engine Rules

Implemented in `backend/app/domain/rebalancing_engine.py`.

Calculates, per category: current allocation %, target allocation %,
deviation, required contribution to reach target, overweight/underweight
status, and whether new buying should be frozen (e.g. at or above maximum).

**The rebalancing engine never executes trades.** It produces
recommendations only; the user decides and acts manually (or via a future,
explicitly separate execution feature outside this engine's scope).

## Snapshot ≠ Transaction

`portfolio_snapshots` / `portfolio_snapshot_items` records are **point-in-time
value observations**, not trade records.

- A snapshot records what a holding was *worth* at a moment in time.
- A transaction records an actual buy/sell/dividend/deposit/withdrawal
  event with quantity and price.
- **Quantities are never inferred from snapshot values.** A snapshot alone
  does not tell you how many shares were held or at what price — only the
  recorded value.

Phase 15 adds `trigger_source`, `source_transaction_id`, `total_cost_basis`,
`invested_capital`, and `realized_pnl_cumulative` to `portfolio_snapshots`
(all nullable/additive — see DATABASE.md and "Phase 15" below). These
remain point-in-time *observations*, computed once at write time from
already-persisted state; they never turn a snapshot into a second
transaction system, and the five original dev-seed snapshots correctly
keep all of them `NULL` (that context was genuinely never captured).

## Price Infrastructure (Phase 11)

Supersedes the earlier "Market Data Integrity" placeholder (a
`MarketDataProvider`/`MockMarketDataProvider` design that was never
actually built). What follows is the real, implemented architecture —
see ARCHITECTURE.md, "Price Infrastructure" for the component diagram,
and DATABASE.md for the `asset_price_configs`/`asset_prices`/`fx_rates`
schema.

**Non-Blocking Valuation (NON-NEGOTIABLE).** No request-time read —
`GET /api/portfolio/summary`, `.../allocation`, `POST
/api/alerts/evaluate`, `POST /api/transactions`'s response snapshot —
may ever synchronously call a live `PriceProvider`. Each reads only the
already-stored `asset_prices` history via `services/price_service.py`.
Fetching *new* data from a provider happens exclusively in
`services/price_orchestrator.py`, called only by the out-of-band
background worker (`app/workers/price_refresh.py`). This guarantees:
dashboard speed and success are independent of any provider's
latency/outage; valuation for a given DB state is deterministic; and
one asset's provider failure can never surface as a broken page.
Verified directly: `app/tests/test_non_blocking_valuation.py` monkeypatches
the provider registry to raise if ever called, then exercises every
request-time read path end-to-end against a real seeded database. The
ONE deliberate exception is `POST /api/assets/{id}/price/refresh` — an
explicit, user-initiated, single-asset synchronous fetch, never called
by any other code path.

**Provider Configuration Is Data, Not Code.** Which provider (if any)
prices an asset, and under what symbol, is a per-asset
`asset_price_configs` row — never inferred from the asset's own
`symbol`, `asset_type`, or market. A `PriceProvider` implementation
receives exactly the `provider_symbol` string configured for it; it
never guesses, transforms, or reverse-engineers a symbol.

**Unconfigured Providers Are Not Errors.** An asset with no
`asset_price_configs` row, or with `automated_fetching_enabled=false`,
is a normal, expected, permanent state — not a bug or a gap to silently
work around. EGX and generic fund-NAV providers have no dedicated
adapter (no genuinely documented/accessible API was available to
implement against without inventing endpoints or scraping) — such
assets simply rely on manual pricing, which remains fully first-class
(see below).

**Manual Pricing Is Not A Provider.** Manual price entry is a push (a
user submits a value right now); a `PriceProvider` is a pull
(`get_price(symbol) -> quote`). Forcing manual entry into the
`PriceProvider` Protocol would be a shape mismatch for no benefit, so it
isn't: manual submissions are written directly by
`services/price_service.record_manual_price`, identified in
`asset_prices` by `provider="manual"`, `is_manual=true`. A manual price
submission is always accepted as the new latest manual observation
(there is nothing to "supersede" — the precedence rule below only ever
gates an *automated* fetch against an existing manual price, never the
other way around), and it never alters any transaction, holding
quantity, or average cost.

**Price Observations Are Immutable.** `asset_prices` and `fx_rates` are
append-only history tables — a row is never updated or deleted once
inserted. "Current price" is always "the latest row for this asset",
computed at read time, never a separately maintained mutable field.

**Single Source Of Truth For Current Price.** Every current-price
consumer — Portfolio Summary, Portfolio Allocation, Smart Inflow
(via `portfolio_shared.load_priced_positions`), Alert evaluation, the
Transaction response snapshot — reads through
`services/price_service.py`. `holdings.current_price` (the pre-Phase-11
column) is no longer read or written anywhere in the codebase; it was
left in place rather than dropped because Phase 11's approved migration
was additive-only (see DATABASE.md). There is exactly one price
calculation path; Dashboard and Allocation can never disagree on an
asset's value because they are never computing it independently.

**Never Fabricate A Price.** An asset with no usable price observation
reports `PRICE_UNAVAILABLE` (`price: null`) — never a fabricated `0`,
never the last transaction's execution price, never a guessed value. A
zero-quantity position is the one exception that legitimately values at
exactly `0` — there's nothing to price, so there's no ambiguity to
report (see domain/portfolio_engine.py).

**Incomplete Valuation Is Not Zero Valuation.** A held (`quantity > 0`)
asset with `PRICE_UNAVAILABLE` is *excluded* from
`total_value`/`emergency_value`/`investable_value`/bucket
`actual_value` — never counted as worth `0`, which would silently
understate the portfolio. `PortfolioSummaryOut`/`PortfolioAllocationOut`/
`InflowAllocationOut` all expose `is_complete: false` plus (on the
first two) `unpriced_asset_ids` so the gap is visible, not hidden.
`BucketAllocationOut.has_unpriced_positions` does the same at the
bucket level.

**Stale Price Policy (NON-NEGOTIABLE): never one universal duration.**
`domain/stale_policy.py` resolves a staleness threshold per asset,
never a single hardcoded number for the whole system:
`asset_price_configs.stale_threshold_minutes` (if set) wins; otherwise
a per-`AssetType` default (`STOCK`/`ETF`: 60 min — intraday,
exchange-traded; `FUND`/`GOLD`/`SAVINGS`/`CASH`/`OTHER`: 24h — daily
NAV or daily reference pricing). An observation's age is computed with
weekend hours (Saturday/Sunday) excluded before comparing against the
threshold, so a Friday close checked on Saturday/Sunday/Monday morning
is correctly NOT stale purely because calendar time elapsed while
markets were closed — while an intraday price genuinely untouched since
Friday IS still correctly flagged stale once meaningful Monday trading
time has passed (the weekend adjustment keeps the reported *age*
honest; it never hides genuine staleness). **Disclosed limitation:** no
market-holiday trading calendar is implemented — a holiday adjacent to
a weekend could still be misclassified as stale. `PriceResult.status`
is `LAST_KNOWN_PRICE` (not `CURRENT_PRICE_AVAILABLE`) once stale; the
underlying price is still returned and usable for valuation — it is
simply never presented as live (see "Never Silently Present Stale As
Live" below).

**Never Silently Present Stale As Live.** A `LAST_KNOWN_PRICE` result
always carries `is_stale: true`, `recorded_at`, and `age_seconds` so a
caller (the frontend, in particular — see `PriceStateBadge`) can render
it distinctly from a `CURRENT_PRICE_AVAILABLE` result. A stale price is
still a usable price for valuation math (better than treating a held
asset as unavailable); it is only ever the *presentation* that must
distinguish it.

**Manual-vs-Automated Precedence (NON-NEGOTIABLE).**
`domain/manual_precedence.py`'s `may_automated_observation_supersede_manual`
is the one function this rule is decided by: an automated observation
may overwrite-as-latest a manual one only if its timestamp is *strictly
greater* than the manual observation's `recorded_at` — an automated
timestamp equal to or older than the manual one never supersedes it,
regardless of when the automated fetch actually ran. Independently,
`asset_price_configs.lock_manual`, when set, blocks ANY automated
supersession regardless of timestamp — a permanent manual lock, not a
one-time protection. This is enforced exclusively in
`services/price_orchestrator.py`, server-side, before a fetched
observation is ever stored — never left to client-side ordering or a
race between refresh and manual entry.

**Base Currency & FX Conversion (NON-NEGOTIABLE).** Every `Asset` has
its own `currency`; every `PortfolioConfig` has a `base_currency`. A
foreign-currency price is NEVER treated as if it were already in base
currency (e.g. 200 USD × quantity is never treated as 200 EGP ×
quantity). When `asset.currency != portfolio.base_currency`,
`services/price_service.get_asset_price_in_base_currency` (and its
batch form, used by portfolio valuation) looks up the latest `fx_rates`
row for that exact currency pair; with none on record, the result is
`CURRENCY_CONVERSION_UNAVAILABLE` (`price: null`) — never an assumed
1:1 rate, never a hardcoded rate, never the transaction's own currency
substituted in. A stale FX rate (same weekend-aware staleness algorithm
as asset prices, using a 24h default — most currency pairs relevant
here only meaningfully re-quote on business days) is still used for
conversion but marks the combined result `LAST_KNOWN_PRICE` rather than
`CURRENT_PRICE_AVAILABLE` — the same "still usable, never presented as
live" rule asset prices follow. FX is modeled generically
(`fx_rates.base_currency`/`quote_currency`, any pair) — there is no
hardcoded USD/EGP-only code path anywhere in this layer.

**Portfolio Valuation Formulas.** Same currency:
`value = quantity × market_price`. Different currency:
`value = quantity × asset_price × fx_rate`. A value is only ever
calculated when every required input is a real, valid, current-or-stale
observation — never when a price or FX rate is unavailable (that
position is excluded from sums per "Incomplete Valuation Is Not Zero
Valuation" above, not zeroed).

**P&L stays formula-unchanged, just optionally undefined.**
`domain/pnl_engine.py`'s `calculate_holding_pnl` already accepted
`current_price: Decimal | None` before Phase 11 (a Phase-5-proofed
signature) and returns `None` for
`market_value`/`unrealized_pnl`/`unrealized_pnl_percent` when price is
unavailable — Phase 11 needed no change here, only needed to actually
supply `None` sometimes. Realized P/L remains untouched by any of this
— it stays transaction-accounting-based (Phase 10), never affected by
current market prices.

**Allocation Shares Exactly One Valuation Path.** `domain/
allocation_engine.py`'s `calculate_bucket_value` excludes (never
zeroes) a position with no usable value, mirroring
`calculate_portfolio_totals`; `has_bucket_unpriced_positions` surfaces
which buckets are affected. Portfolio Summary and Portfolio Allocation
are computed from the identical `AssetPosition` list (built once via
`portfolio_shared.load_priced_positions`) — they can never disagree
about one asset's value due to different pricing logic, because there
is only one pricing logic.

## Administration Rules (Phase 12)

**Asset Deletion Policy.** An asset may be hard-deleted only when it has
*no* holding, transaction, watchlist entry, portfolio-snapshot item, or
price observation on record. If any exists, `DELETE /api/assets/{id}`
returns 409 and the caller must deactivate (`is_active=false`) instead —
deactivation preserves all historical rows and simply removes the asset
from active-selection lists (allocation targets, new transactions).
Deliberately stricter than the schema's own `ON DELETE CASCADE` on
`asset_prices`: even though the database *would* cascade-delete price
history, the application layer treats existing price observations as
historical data worth protecting anyway, and blocks the delete.

**Base Currency Change Policy.** `portfolio_configs.base_currency`
materially changes how every past and future value is interpreted
(valuation, allocation percentages, realized/unrealized P&L). Once even
one transaction exists anywhere in the system, `PATCH /api/portfolio/
config` rejects any `base_currency` change with 409 rather than
performing it — there is no currently-implemented mechanism to safely
reinterpret historical transaction amounts against a new base currency,
so the honest behavior is to refuse, not to silently reinterpret. Before
any transaction exists, the base currency may be changed freely (nothing
historical yet depends on it).

**Currency Change on an Existing Asset.** The same reasoning applies at
the asset level: `PATCH /api/assets/{id}` rejects a `currency` change
once that asset has any transaction or price-observation history (409).
An asset's currency is treated as fixed the moment real financial history
references it.

**Provider Validation Is Registry-Driven, Never Assumed.** `PUT /api/
assets/{id}/price-config` never accepts a `primary_provider`/
`secondary_provider` string merely because it looks plausible — it is
checked against `providers/registry.py`'s actual registered provider
set. There is no asset-specific hardcoded provider mapping anywhere in
the admin layer; a provider must be registered code, not a config-time
invention.

**Strategy Validation Ownership.** Bucket/target administration
(`strategy_admin_service.py`) validates only per-row invariants — percent
ranges, `minimum ≤ maximum`, duplicate bucket names, at most one target
per bucket — the same set the database's own CHECK/UNIQUE constraints
already enforce. It never calls, and never blocks a save on, the
aggregate "does the whole portfolio's target allocation sum to 100%"
question; that remains exclusively `strategy_service.py`'s read-only
`GET /api/portfolio/strategy/validation` responsibility (Phase 6,
unchanged). Saving a single 10% target when nothing else is configured
succeeds; the system then correctly reports
`INCOMPLETE_TARGET_ALLOCATION` on the next validation read. The admin
layer never auto-invents a target percentage to make a configuration
"add up."

**Administrative Changes Never Rewrite Financial History.** Every admin
write (asset update, price-config upsert, portfolio-config update,
bucket/target update) touches only its own configuration table. None of
them updates a `transactions` row, a `holdings` row, an existing
`asset_prices` row, or a `portfolio_snapshot_items` row. This is verified
directly, not just asserted: `test_admin_financial_integrity.py` performs
a real admin write and then re-queries the exact historical row by ID,
asserting every financial field (price, quantity, fees, timestamp,
average cost, realized P&L inputs) is byte-for-byte unchanged.

## EGX Provider Configuration (Phase 13)

Two candidate EGX-specific market-data providers (EGID/Ticker
DelayedFeed, EGXAPI) were investigated and **neither was implemented** —
one is not verifiably free, the other is architecturally a brokerage/
order-execution API rather than a market-data feed, and this sandbox's
network policy blocked live verification of either. No fabricated
adapter was written for either. See DECISIONS.md, "Phase 13 — EGX Market
Data Provider Integration" for the complete investigation.

A Mubasher Egypt adapter (`providers/mubasher_provider.py`) was added
later and is now `primary_provider` for the EGX-listed equities actually
present in this project (`TMGH`, `ETEL`, `EFID`), with the existing Phase
11 Yahoo Finance provider retained as `secondary_provider` for each —
the pre-existing primary→secondary→DB→`PRICE_UNAVAILABLE` fallback chain
is unchanged, just now trying Mubasher before Yahoo. Mubasher's payload
contract was verified via a live network test performed OUTSIDE this
sandbox (this sandbox's own network blocks `www.mubasher.info`, same as
Yahoo/EGID/EGXAPI); the adapter is therefore mock-tested against that
externally-reported shape, not live-tested from within this environment
— see DECISIONS.md, "Mubasher Provider Decision" for the full account,
including why its currency field (absent from Mubasher's schema) is a
disclosed fixed `"EGP"` rather than an inferred one, and why its
licensing is marked `LICENSING_NOT_VERIFIED`. `BWA` and `AZN` are
mutual-fund NAV assets, not EGX-listed equities, and are deliberately
never assigned any stock-exchange provider (Mubasher, Yahoo, or
otherwise) — a naive ticker-suffix assumption for both was checked and
rejected during the original Yahoo investigation, since it resolved to
unrelated foreign companies, not the Egyptian instruments of the same
short code. See `app/seed/data.py`'s `SEED_ASSET_PRICE_CONFIGS` for the
exact configuration and reasoning.

## Phase 15: Historical Snapshots, Cash Flow, and Time-Weighted Return

Implemented in `domain/twr_engine.py`, `domain/transaction_engine.py`
(DEPOSIT/WITHDRAWAL additions), `services/snapshot_service.py`,
`services/portfolio_analytics_service.py`, `workers/snapshot_eod.py`.

**Cash Flow Is Not Profit (NON-NEGOTIABLE).** A DEPOSIT/WITHDRAWAL is
external capital moving into or out of the portfolio — it must never be
counted as investment return, and TWR is specifically the mechanism that
guarantees this (see below). DEPOSIT/WITHDRAWAL are restricted to assets
whose `asset_type` is `CASH` or `SAVINGS`; for those, `quantity` IS the
cash balance and `average_cost` is pinned at exactly `1` (never blended
via `apply_buy`/`apply_sell`), so `cost_basis == quantity` always and no
artificial unrealized P/L is ever generated for holding cash. A
DEPOSIT/WITHDRAWAL requires `price == 1` and `fees == 0` — rejected
otherwise, rather than guessing what a non-1 price or a fee would mean
for "the amount." **`TRANSFER` remains unimplemented and rejected** — its
meaning (an external wire vs. an internal move between two of the user's
own holdings) is genuinely ambiguous in this system's data model, and
guessing wrong would silently corrupt TWR; this is a disclosed limitation
for a future phase, not a decision made here.

**Realized P/L Is Never A Running Ledger (still true).** The Phase 10
rule above is unchanged: no column on `transactions` or `holdings` is
incrementally updated on each SELL. `portfolio_snapshots.realized_pnl_cumulative`
is a different kind of thing — a point-in-time *observation*, computed
once at snapshot-write time by replaying every BUY/SELL transaction
in deterministic order through the exact same, unmodified
`apply_buy`/`apply_sell` math. It is a derived snapshot field, exactly
like `total_cost_basis`, not a maintained ledger column that `SELL`
itself writes to.

**Snapshot Lifecycle.** Two trigger sources exist, recorded on
`trigger_source`:
- **EOD** — created by the out-of-band `app/workers/snapshot_eod.py`
  worker (external scheduler, same execution model as
  `price_refresh.py`/`alert_notify.py`). Idempotent per portfolio per
  **UTC calendar day** — running the worker again the same day is a
  no-op, enforced both at the application level (a lookup before
  writing) and at the database level (a partial unique index,
  `uq_portfolio_snapshot_eod_per_day`).
- **TRANSACTION** — created synchronously, atomically, in the same
  database transaction as a DEPOSIT/WITHDRAWAL write (one
  `session.commit()` covers the transaction, the holding update, and the
  snapshot together — see "Transaction Atomicity"). BUY/SELL never
  trigger a snapshot (they change composition, not total value, in a way
  that needs a separate historical point). Idempotent per triggering
  transaction via `uq_portfolio_snapshot_source_transaction`.

**EOD Convention (explicit, deliberately narrow).** "End of day" means
**UTC calendar day** — every timestamp in this schema is already
`TIMESTAMP(timezone=True)` (UTC-normalized), and no other boundary
existed anywhere in the codebase before this phase. **This does NOT yet
represent Egypt-local EGX market close** — introducing Africa/Cairo
trading-day semantics is explicitly out of scope for this phase and is a
disclosed limitation, not an oversight.

**TWR Convention: Snapshot-After-Flow With Algebraic Pre-Flow
Reconstruction.** For a DEPOSIT/WITHDRAWAL, the snapshot records the
value *after* the flow has landed, together with the signed flow amount.
The pre-flow value is reconstructed exactly as
`pre_flow_value = post_flow_value − signed_flow` — exact, not assumed,
because the flow is defined to be the only thing that changed in that
instant. The sub-period ending at a flow is measured against this
reconstructed pre-flow value (so the flow itself contributes exactly 0%
return by construction), and the post-flow value becomes the new
baseline for whatever comes next. This is standard sub-period TWR; see
`domain/twr_engine.py`'s module docstring for the full derivation and
`test_domain_twr_engine.py` for 16 mathematically verified fixtures
(flat market + deposit → 0%, growth alone → the exact market return,
consecutive deposits/withdrawals net to 0% absent real growth, a
zero-starting-balance case resolves to a defined 0% rather than
NaN/Infinity, insufficient history is reported explicitly rather than as
a fabricated 0%, and so on).

**Deterministic Ordering.** Both snapshot replay (for TWR) and
transaction replay (for `realized_pnl_cumulative`/`invested_capital`) use
`(event_timestamp, created_at, id)` ascending as the sort key. `id` (a
random UUIDv4) is a final, stable tiebreaker for two events sharing an
identical timestamp down to stored precision — it makes the result
deterministic and reproducible, but it does **not** claim to reconstruct
a true real-world sub-instant order the system never actually captured.
This mirrors an existing, unremarked limitation already present in the
Phase 10 transaction write path (which also assumes transactions are
entered in real-world chronological order, with no support for
true historical backdating/replay) — Phase 15 does not change or fix
that pre-existing assumption, only makes its ordering rule explicit.

**Analytics never fabricates a data point.** `services/
portfolio_analytics_service.py` reads only persisted `PortfolioSnapshot`
rows — never today's live holdings, never an interpolated/extrapolated
point. Only snapshots with `invested_capital IS NOT NULL` (i.e. created
under this phase's lifecycle) are eligible; the five pre-Phase-15 seed
snapshots are excluded rather than assigned a guessed `invested_capital`
of `0`. A requested range with fewer than two eligible snapshots reports
`insufficient_history: true` with an empty `data` list — never a
misleading flat/empty chart presented as a real result.

**Known Limitations (disclosed, not silently worked around):**
- `TRANSFER` is unimplemented (see above).
- A CASH/SAVINGS asset used for DEPOSIT/WITHDRAWAL needs its own usable
  price (e.g. a manual price of `1`, via the existing Phase 11 manual
  price endpoint) to be included in a snapshot's `total_value`/items —
  Phase 15 does not special-case pricing for cash; it reuses the
  existing Price Service exactly as every other asset does.
- Mixing BUY/SELL and DEPOSIT/WITHDRAWAL on the *same* asset is undefined
  behavior and not guarded against (a DEPOSIT/WITHDRAWAL always pins
  `average_cost` to `1`, which would silently overwrite a
  BUY-established average cost on that same asset).
- Historical data predating this phase (the five original dev-seed
  snapshots) is excluded from analytics/TWR, not retroactively
  backfilled.

## Summary of Non-Negotiable Distinctions

- **Target ≠ Maximum**
- **Maximum ≠ Allow New Buy**
- **Emergency Cash ≠ Investment Cash**
- **Snapshot ≠ Transaction**
- **Current Price ≠ Transaction Price** (Phase 10/11)
- **Stale ≠ Live** (Phase 11 — a usable last-known price is never presented as a live one)
- **Unavailable ≠ Zero** (Phase 11 — an unpriced position is excluded from totals, never counted as worth nothing)
- **Manual Override ≠ silently overwritable** (Phase 11 — an automated fetch only supersedes a manual price with a strictly newer timestamp, or never, if locked)
- **Asset ≠ Holding ≠ Transaction ≠ Price Observation** (Phase 12 — an asset is an instrument; a holding and a transaction are portfolio-scoped facts about it; a price observation is neither — administration never collapses these into one editable record)
- **Configuration Change ≠ Historical Rewrite** (Phase 12 — an admin write changes future behavior only; it never alters a transaction's price/quantity/timestamp, a holding's quantity/average cost, a past price observation, or a snapshot value)
- **Evaluation ≠ Delivery** (Phase 14 — the alert engine decides a condition is newly true; a separate, isolated `NotificationDispatcher` decides whether/how to tell someone. A delivery failure never breaks evaluation, and evaluation never blocks on a live delivery call)
- **Cash Flow ≠ Investment Return** (Phase 15 — a DEPOSIT/WITHDRAWAL is external capital, never counted as market performance; Time-Weighted Return exists specifically to isolate the two)
- **A Snapshot Observation ≠ A Ledger** (Phase 15 — `realized_pnl_cumulative`/`total_cost_basis`/`invested_capital` on `portfolio_snapshots` are computed once at write time from already-persisted state; they are not incrementally-maintained columns that `transactions`/`holdings` themselves write to)

These distinctions must be preserved end-to-end: in the database schema
(DATABASE.md), the domain logic (this document), the API contract
(API.md), and the UI (never collapsed into a single implied value).
