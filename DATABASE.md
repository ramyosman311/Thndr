# Database

## Status

Implemented as of **Phase 3**: all core tables below exist as SQLAlchemy
2.x models (`backend/app/models/`) and a real Alembic migration
(`backend/alembic/versions/ac3c275604cd_phase_3_core_portfolio_schema.py`),
applied and verified against a real PostgreSQL database. Phases 4-10 built
seed data and business/calculation logic against this schema **without
requiring any further migration** — Phase 8 (Watchlist + Alerts)
confirmed the `watchlist`/`alert_rules` tables were sufficient as-is (see
"Known Schema Limitations (Phase 8)" below for the two gaps it disclosed
rather than worked around), and Phase 10 (Transaction + Holdings Engine)
confirmed `holdings`/`transactions` were already exactly what
transaction-derived positions require.

## Engine

- **Production:** PostgreSQL (Supabase-hosted).
- **Local development:** dockerized PostgreSQL, matching production engine.
- **Testing:** a real PostgreSQL database (a `_test`-suffixed sibling of the
  configured database), migrated via the actual `alembic upgrade head`
  command in a session-scoped test fixture — not SQLite. PostgreSQL-specific
  behavior (native ENUM types, `NUMERIC` precision, `ON DELETE` semantics)
  is exercised directly in tests (`backend/app/tests/test_models.py`).
- SQLite is never used as a production database, and is not used for model
  tests either — see FINANCIAL_RULES.md and the testing plan.

## Core Principle: Database as Source of Truth

No allocation percentage, asset limit, or investment rule is hardcoded in
application code. All such values live in `portfolio_configs` and
`allocation_targets` rows, editable via Settings. See
[FINANCIAL_RULES.md](./FINANCIAL_RULES.md).

## Numeric Precision (chosen in Phase 3)

No financial value uses a binary floating-point type. All money/quantity/
percentage columns are PostgreSQL `NUMERIC` (SQLAlchemy `Numeric`):

| Kind | Precision/scale | Used by | Why |
|---|---|---|---|
| Quantity | `NUMERIC(20, 8)` | `holdings.quantity`, `transactions.quantity` | supports fractional shares/fund units exactly |
| Unit price | `NUMERIC(20, 8)` | `holdings.average_cost`, `holdings.current_price`, `transactions.price`, `alert_rules.price_target`, `alert_rules.dip_buy_price` | precise even for low-priced assets; matches quantity precision for averaging math |
| Currency amount | `NUMERIC(18, 2)` | `transactions.fees`, `portfolio_snapshot_items.value` | a plain monetary total, 2 decimal places |
| Percentage | `NUMERIC(5, 2)` | `allocation_targets.target_percent`/`minimum_percent`/`maximum_percent`, `alert_rules.allocation_max_percent` | range 0.00–100.00, hundredths-of-a-percent precision |

## Deletion Behavior

Every foreign key to `assets` from a table that carries historical or
current financial data uses `ON DELETE RESTRICT`: `holdings`,
`transactions`, `watchlist`, `portfolio_snapshot_items`. Attempting to
delete an asset that is still referenced by any of these fails outright
(an `IntegrityError`), rather than cascading and silently destroying
records or leaving orphaned rows. This was verified directly (Phase 3
tests `test_deleting_asset_with_transaction_history_is_blocked` and
`test_deleting_asset_with_snapshot_history_is_blocked`).

Purely organizational/config references use softer behavior instead:
`assets.strategy_bucket_id → strategy_buckets` and
`portfolio_configs.emergency_asset_id → assets` are `ON DELETE SET NULL`
(losing a category or emergency-asset designation isn't destructive).
Parent-owns-child tables cascade: `strategy_buckets`, `allocation_targets`,
and `portfolio_snapshots` are `ON DELETE CASCADE` from `portfolio_configs`;
`portfolio_snapshot_items` cascades from `portfolio_snapshots`; `alert_rules`
cascades from `watchlist`. `allocation_targets.strategy_bucket_id` is
`ON DELETE RESTRICT` (a bucket with an active rule can't be removed out
from under it).

## Core Tables (implemented in Phase 3)

### `assets`

| Field       | Type      | Notes |
|-------------|-----------|-------|
| id          | UUID (PK) | |
| symbol      | string, **unique** | e.g. `BWA`, `AZN`, `ETEL` — a data row, never a hardcoded constant |
| name        | string    | |
| asset_type  | native enum | `STOCK`, `FUND`, `GOLD`, `CASH`, `SAVINGS`, `ETF`, `OTHER` |
| market      | string, nullable | e.g. EGX, or null for non-market assets |
| currency    | string    | ISO currency code |
| strategy_bucket_id | UUID (FK → strategy_buckets, nullable, `ON DELETE SET NULL`) | which configurable category this asset belongs to |
| is_active   | boolean   | |
| created_at  | timestamp | |
| updated_at  | timestamp | |

### `strategy_buckets` (new in Phase 3)

Not present in the original Phase 1 sketch — added per the Phase 3
approval to keep **Asset**, **Asset Class / Strategy Bucket**, and
**Allocation Rule** as distinct concepts (see FINANCIAL_RULES.md). A
bucket is a configurable category (e.g. "Individual Stocks", "Gold",
"Cash") that assets belong to and that `allocation_targets` rules target —
never a hardcoded grouping around specific ticker symbols.

| Field                | Type      | Notes |
|----------------------|-----------|-------|
| id                   | UUID (PK) | |
| portfolio_config_id  | UUID (FK → portfolio_configs, `ON DELETE CASCADE`) | |
| name                 | string    | unique per portfolio_config |
| description          | text, nullable | |
| is_active            | boolean   | |
| created_at, updated_at | timestamp | |

### `holdings`

| Field         | Type      | Notes |
|---------------|-----------|-------|
| id            | UUID (PK) | |
| asset_id      | UUID (FK → assets, **unique**, `ON DELETE RESTRICT`) | one holding row per asset |
| quantity      | `NUMERIC(20,8)` | |
| average_cost  | `NUMERIC(20,8)` | cost basis per unit |
| current_price | `NUMERIC(20,8)` | last known price (from market data provider) |
| updated_at    | timestamp | |

CHECK constraints: `quantity >= 0`, `average_cost >= 0`, `current_price >= 0`.

`quantity` and `average_cost` are, as of Phase 10, always the *derived
result* of transaction history (`POST /api/transactions` — see
FINANCIAL_RULES.md, "Transaction Accounting") — this table's own schema
needed no change to support that; it was already exactly what a
transaction-derived position requires. `current_price` remains untouched
by transactions (a separate concept — see FINANCIAL_RULES.md, "Current
Price Is Not Set By Transactions"); nothing in Phase 10 writes it.

### `transactions`

| Field             | Type      | Notes |
|-------------------|-----------|-------|
| id                | UUID (PK) | |
| asset_id          | UUID (FK → assets, `ON DELETE RESTRICT`) | |
| transaction_type  | native enum | `BUY`, `SELL`, `DIVIDEND`, `DEPOSIT`, `WITHDRAWAL`, `TRANSFER` |
| quantity          | `NUMERIC(20,8)` | |
| price             | `NUMERIC(20,8)` | |
| fees              | `NUMERIC(18,2)` | |
| transaction_date  | timestamp | |
| notes             | text, nullable | |
| created_at        | timestamp | |

Indexed on `(asset_id, transaction_date)`. CHECK constraints:
`quantity >= 0`, `price >= 0`, `fees >= 0`. Only `BUY`/`SELL` are
writable via `POST /api/transactions` as of Phase 10 — the other enum
values exist for a future phase and have no defined holding-update
behavior yet. Rows are immutable once written: Phase 10 adds no
update/delete path for this table (see FINANCIAL_RULES.md, "Transaction
Accounting").

### `portfolio_configs`

| Field                | Type      | Notes |
|----------------------|-----------|-------|
| id                   | UUID (PK) | |
| name                 | string    | |
| base_currency        | string    | |
| emergency_asset_id   | UUID (FK → assets, nullable, `ON DELETE SET NULL`) | which asset is the emergency/savings asset |
| emergency_excluded   | boolean   | if true, excluded from risk/investment/rebalancing/inflow calcs |
| telegram_enabled     | boolean   | |
| created_at           | timestamp | |
| updated_at           | timestamp | |

### `allocation_targets`

| Field                 | Type      | Notes |
|-----------------------|-----------|-------|
| id                    | UUID (PK) | |
| portfolio_config_id   | UUID (FK → portfolio_configs, `ON DELETE CASCADE`) | |
| strategy_bucket_id    | UUID (FK → strategy_buckets, `ON DELETE RESTRICT`) | the rule targets a bucket, not a freeform name string |
| target_percent        | `NUMERIC(5,2)`, nullable | long-term target weight (may be NULL, e.g. "Individual Stocks") |
| minimum_percent       | `NUMERIC(5,2)`, nullable | |
| maximum_percent       | `NUMERIC(5,2)`, nullable | hard cap, independent of target |
| allow_new_buy         | boolean   | whether the inflow engine may buy into this category |
| priority              | integer   | used by the inflow engine to order underweight categories |
| is_active             | boolean   | |
| created_at            | timestamp | |

Unique per `(portfolio_config_id, strategy_bucket_id)`. CHECK constraints
enforce each percent field is within `[0, 100]` (when not NULL) and
`minimum_percent <= maximum_percent` (when both set) — all at the row
level. **Validation rule (service/domain layer, not a DB constraint):** the
sum of `target_percent` across active targets must be validated when
settings are saved (Phase 6) — PostgreSQL cannot enforce that aggregate
rule with a column-level CHECK. See [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).

### `watchlist`

| Field       | Type      | Notes |
|-------------|-----------|-------|
| id          | UUID (PK) | |
| asset_id    | UUID (FK → assets, **unique**, `ON DELETE RESTRICT`) | one row per asset — re-adding re-enables it |
| enabled     | boolean   | |
| notes       | text, nullable | |
| added_at    | timestamp | |
| removed_at  | timestamp, nullable | logical removal, not physical delete |

### `alert_rules`

| Field                      | Type      | Notes |
|----------------------------|-----------|-------|
| id                         | UUID (PK) | |
| watchlist_id               | UUID (FK → watchlist, **unique**, `ON DELETE CASCADE`) | |
| enabled                    | boolean   | |
| allocation_alert_enabled   | boolean   | also drives the Phase 8 rebalance-suggestion check — see FINANCIAL_RULES.md, "Alert Engine Rules" |
| allocation_max_percent     | `NUMERIC(5,2)`, nullable | |
| price_target_enabled       | boolean   | |
| price_target               | `NUMERIC(20,8)`, nullable | |
| dip_buy_enabled            | boolean   | |
| dip_buy_price              | `NUMERIC(20,8)`, nullable | |
| telegram_enabled           | boolean   | |
| last_triggered_at          | timestamp, nullable | Phase 8 dedup latch — one shared column per row, see "Known Schema Limitations" below |
| created_at                 | timestamp | |
| updated_at                 | timestamp | |

Used as-is in Phase 8 (Watchlist + Alerts): no migration was required.
Both `watchlist` and `alert_rules` (Phase 3) turned out sufficient for
watchlist CRUD, four DB-backed alert checks (allocation breach, price
target, dip buy, rebalance suggestion), and edge-triggered
enable/disable-safe deduplication. Two genuine gaps were identified and
are disclosed rather than worked around — see the next section.

### Known Schema Limitations (Phase 8)

Two gaps were identified while implementing the Watchlist + Alerts
feature. Per the Phase 8 approval ("if the existing schema is
insufficient, STOP and report the deficiency — do not create an
unrelated migration"), neither was worked around with a speculative
migration; both are reported here with the minimal addition each would
need, and both align with tables already listed as deferred above.

**1. No income/recurring-payment maturity date anywhere.** `alert_rules`
has no column that could represent a maturity or due date (not even an
`_enabled` flag for it), so the "Recurring Income Maturity" alert
category (`check_income_maturity` in
`backend/app/domain/alert_engine.py`) is implemented and unit-tested as a
pure, standalone domain function, but is not wired into a persisted
`AlertRule` or the `/api/alerts/evaluate` endpoint. The minimal schema
addition would be the already-deferred **`scheduled_income`** table
(one row per recurring payment/maturity: `asset_id` or a free-text label,
`maturity_date`, `recurrence` if any, `lookahead_days`, `enabled`), plus
a way for `alert_rules` to reference it (or an
`income_maturity_enabled`/`income_maturity_watchlist_id` pair) — not a
change to `watchlist`/`alert_rules` themselves.

**2. `alert_rules.last_triggered_at` is one shared column per row, not
one per condition type.** When a single alert rule has more than one
check enabled at once (e.g. both `allocation_alert_enabled` and
`price_target_enabled`), Phase 8's deduplication necessarily latches on
whether *any* enabled check was last known to be triggered, aggregated
across the row — accurate for the common case of one check type per
rule, but not independently correct when several are combined. The
minimal schema addition would be the already-deferred
**`alert_events`** table (one row per `(alert_rule_id, alert_type)` pair
with its own `last_triggered_at`/`cleared_at`), which Phase 8's
edge-triggered logic (`is_new_trigger`/`should_clear` in
`alert_engine.py`) is already structured to slot into unchanged — only
the persistence key would change, from "the rule row" to "the
`(rule, alert_type)` pair."

### `portfolio_snapshots` / `portfolio_snapshot_items`

Rather than a wide table with one hardcoded column per asset
(`snapshot.cloudz`, `snapshot.bwa`, `snapshot.azn`, ...), snapshots use a
normalized parent/child structure so new assets never require a schema
change:

**`portfolio_snapshots`**

| Field                | Type      | Notes |
|----------------------|-----------|-------|
| id                   | UUID (PK) | |
| portfolio_config_id  | UUID (FK → portfolio_configs, `ON DELETE CASCADE`) | |
| snapshot_at          | timestamp | when the snapshot represents |
| label                | string, nullable | |
| created_at           | timestamp | |

Indexed on `(portfolio_config_id, snapshot_at)`.

**`portfolio_snapshot_items`**

| Field        | Type      | Notes |
|--------------|-----------|-------|
| id           | UUID (PK) | |
| snapshot_id  | UUID (FK → portfolio_snapshots, `ON DELETE CASCADE`) | |
| asset_id     | UUID (FK → assets, `ON DELETE RESTRICT`) | |
| value        | `NUMERIC(18,2)` | recorded value at snapshot time |

Unique per `(snapshot_id, asset_id)`; CHECK `value >= 0`.

Snapshots are point-in-time value records, distinct from transactions —
see "Snapshot ≠ Transaction" in [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).
Quantities are never inferred from snapshot values.

## A Circular Foreign Key, and How the Migration Handles It

`assets.strategy_bucket_id → strategy_buckets`,
`strategy_buckets.portfolio_config_id → portfolio_configs`, and
`portfolio_configs.emergency_asset_id → assets` form a 3-table reference
cycle — no linear `CREATE TABLE` order satisfies all three inline. The
migration creates `assets` without the `strategy_bucket_id` foreign key
inline, creates `portfolio_configs` and `strategy_buckets` normally (each
of their FKs is satisfied by then), and adds the deferred
`assets.strategy_bucket_id → strategy_buckets.id` constraint via a
separate `ALTER TABLE` once all three tables exist. `downgrade()` drops
that constraint before dropping `strategy_buckets`. This was verified with
multiple full `alembic upgrade head` / `alembic downgrade base` cycles
against a real database.

## Future Tables (not built yet, architecture must not preclude them)

`portfolio_snapshots` / `portfolio_snapshot_items` were brought forward
from this list and implemented in Phase 3 (see above). Still deferred:

- `cash_flows`
- `alert_events`
- `market_quotes`
- `scheduled_income`
- `users`
- `audit_logs`

These are deferred until their owning phase (or later) unless a dependency
forces earlier introduction. The schema above avoids decisions that would
require rewriting existing tables to add them later (e.g. UUID primary
keys throughout, no assumption of a single implicit user).
`alert_events` and `scheduled_income` were evaluated during Phase 8
(Watchlist + Alerts) and remain deferred — see "Known Schema Limitations
(Phase 8)" above for exactly what each would unlock and why Phase 8
didn't introduce either speculatively.

## Identifiers

All entities use UUID primary keys, not auto-incrementing integers, to
support future multi-user/multi-device sync without key collisions.

## Seed Data

No seed data is included in the Alembic migration. The migration only
creates schema (tables, types, constraints, indexes) — it contains no
`INSERT` statements and no assumptions about which assets, buckets, or
percentages a user's portfolio actually has.

Development seed data is implemented separately, in `backend/app/seed/`
(Phase 4), run explicitly via `python -m app.seed` — never automatically,
and never as part of a migration:

- `app/seed/data.py` — plain constants: 7 initial assets, 6 strategy
  buckets, 1 portfolio configuration, 5 allocation targets, 5 historical
  snapshots. Data only, read once by the seed script; never referenced
  from `domain/`, `services/`, or any future engine.
- `app/seed/seed.py` — idempotent "create if missing" logic, keyed on
  stable identifiers (asset `symbol`; portfolio config `name`;
  `(portfolio_config, strategy_bucket)` pairs; `(portfolio_config,
  snapshot_at)` pairs) rather than generated UUIDs. Running it any number
  of times produces the same rows — verified with three consecutive runs
  against a real database and an automated idempotency test
  (`test_seed_is_idempotent_when_run_twice`).
- Cloudz is wired as the emergency asset, and Individual Stocks/Gold get
  their maximum-vs-target/allow_new_buy treatment, entirely through these
  seeded configuration rows — never through an `if symbol == "..."` check
  anywhere in application code.

## Known Warning: Circular-Dependency Sort

Running `alembic check` or `alembic revision --autogenerate` prints:

```
SAWarning: Cannot correctly sort tables; there are unresolvable cycles
between tables "assets, portfolio_configs, strategy_buckets" ...
```

This comes from SQLAlchemy's metadata reflection/comparison step noticing
the same 3-table cycle described above. It is expected, benign, and does
not affect migration correctness — `alembic upgrade head`,
`alembic downgrade base`, and `alembic check` all complete successfully
despite it (verified directly). It would only matter if a future
autogenerate needs to reason about ordering across these three tables
again; if so, the same deferred-constraint pattern applies.
