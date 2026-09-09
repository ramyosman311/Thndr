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

- This validation happens in the **service/domain layer**, not solely via
  a database CHECK constraint — PostgreSQL cannot enforce an aggregate
  SUM constraint across rows with a simple column-level CHECK.
- If active targets **exceed 100%**, the save is **rejected**.
- If active targets are **below 100%**, the UI must either show an
  explicit warning or require the user to configure an explicit
  "unallocated percentage" — values are **never silently normalized** to
  sum to 100%.

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

Implemented in `backend/app/domain/inflow_allocator.py`.

**Inputs:** new cash amount, current holdings, current prices, allocation
targets, maximum allocations, `allow_new_buy` flags, priorities.

**Output per recommendation:** asset/group, recommended amount, current
weight, target weight, deficit, and a human-readable reason.

**Rules:**

1. Never sell. The allocator only distributes new incoming cash.
2. Never allocate above a category's `maximum_percent`.
3. Prioritize underweight categories (current weight furthest below target),
   using `priority` to break ties or order sequencing.
4. Respect `allow_new_buy` — a category with `allow_new_buy = false`
   receives zero, regardless of how underweight it is.
5. A category with `target = 0` and `allow_new_buy = false` (e.g. Gold in
   the example above) receives zero new cash.
6. Individual Stocks (or any grouped category) respect their **combined**
   maximum — the sum across the group's members must not exceed the
   group's `maximum_percent`.
7. The emergency asset is excluded from allocation when
   `emergency_excluded = true`.
8. A configured "free cash" / unallocated target is respected — cash is not
   force-allocated past it.
9. Every recommendation includes a reason explaining why that amount was
   chosen (e.g. "underweight vs target by X%", "at maximum, skipped").

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
