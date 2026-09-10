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
  (in practice, `holdings.current_price` — the same field the Portfolio
  Engine already uses). No live market-data provider is invented for
  this: see "Market Data Integrity" above. A `None`/unknown price means
  the check reports `condition_met: false, reason: "current price
  unknown"` — never a fabricated value.
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
  notification_dispatcher.py`) is called only for new triggers, and no
  real delivery mechanism (Telegram or otherwise) exists yet — a
  `NullNotificationDispatcher` is the default. Domain code never imports
  or calls a dispatcher directly.

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

## Summary of Non-Negotiable Distinctions

- **Target ≠ Maximum**
- **Maximum ≠ Allow New Buy**
- **Emergency Cash ≠ Investment Cash**
- **Snapshot ≠ Transaction**
- **Current Price ≠ Transaction Price** (Phase 10/11)
- **Stale ≠ Live** (Phase 11 — a usable last-known price is never presented as a live one)
- **Unavailable ≠ Zero** (Phase 11 — an unpriced position is excluded from totals, never counted as worth nothing)
- **Manual Override ≠ silently overwritable** (Phase 11 — an automated fetch only supersedes a manual price with a strictly newer timestamp, or never, if locked)

These distinctions must be preserved end-to-end: in the database schema
(DATABASE.md), the domain logic (this document), the API contract
(API.md), and the UI (never collapsed into a single implied value).
