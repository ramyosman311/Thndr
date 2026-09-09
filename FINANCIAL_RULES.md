# Financial Rules

## Status

This document specifies the financial domain rules the backend `domain/`
layer must implement (Phases 5–8). No calculation logic exists yet in
Phase 1. This is the specification those phases are built and tested
against.

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

## Market Data Integrity

Market data flows only through the `MarketDataProvider` abstraction
(`get_quote`, `get_quotes`, `get_gold_price`). Until a real provider is
configured, `MockMarketDataProvider` is used and is **explicitly marked as
mock** in code, logs, and (where surfaced) the UI. Mock data must never be
presented to the user as real market data.

## Summary of Non-Negotiable Distinctions

- **Target ≠ Maximum**
- **Maximum ≠ Allow New Buy**
- **Emergency Cash ≠ Investment Cash**
- **Snapshot ≠ Transaction**

These distinctions must be preserved end-to-end: in the database schema
(DATABASE.md), the domain logic (this document), the API contract
(API.md), and the UI (never collapsed into a single implied value).
