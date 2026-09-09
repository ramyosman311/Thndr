# Database

## Status

This document specifies the intended schema. No tables exist yet — models
and migrations are created in **Phase 3**. This is the design contract for
that phase.

## Engine

- **Production:** PostgreSQL (Supabase-hosted).
- **Local development:** dockerized PostgreSQL, matching production engine.
- **Testing:** SQLite may be used only where PostgreSQL-specific behavior is
  not under test; PostgreSQL-compatible test databases are preferred so
  tests reflect real behavior (see FINANCIAL_RULES.md and testing plan).
- SQLite is never used as a production database.

## Core Principle: Database as Source of Truth

No allocation percentage, asset limit, or investment rule is hardcoded in
application code. All such values live in `portfolio_configs` and
`allocation_targets` rows, editable via Settings. See
[FINANCIAL_RULES.md](./FINANCIAL_RULES.md).

## Phase 1 Entities (implemented in Phase 3)

### `assets`

| Field       | Type      | Notes |
|-------------|-----------|-------|
| id          | UUID (PK) | |
| symbol      | string    | e.g. `BWA`, `AZN`, `ETEL` |
| name        | string    | |
| asset_type  | enum      | `STOCK`, `FUND`, `GOLD`, `CASH`, `SAVINGS`, `ETF`, `OTHER` |
| market      | string    | e.g. EGX, or null for non-market assets |
| currency    | string    | ISO currency code |
| is_active   | boolean   | |
| created_at  | timestamp | |
| updated_at  | timestamp | |

### `holdings`

| Field         | Type      | Notes |
|---------------|-----------|-------|
| id            | UUID (PK) | |
| asset_id      | UUID (FK → assets, **unique**) | one holding row per asset |
| quantity      | numeric   | |
| average_cost  | numeric   | cost basis per unit |
| current_price | numeric   | last known price (from market data provider) |
| updated_at    | timestamp | |

### `transactions`

| Field             | Type      | Notes |
|-------------------|-----------|-------|
| id                | UUID (PK) | |
| asset_id          | UUID (FK → assets) | |
| transaction_type  | enum      | `BUY`, `SELL`, `DIVIDEND`, `DEPOSIT`, `WITHDRAWAL`, `TRANSFER` |
| quantity          | numeric   | |
| price             | numeric   | |
| fees              | numeric   | |
| transaction_date  | timestamp | |
| notes             | text, nullable | |
| created_at        | timestamp | |

### `portfolio_configs`

| Field                | Type      | Notes |
|----------------------|-----------|-------|
| id                   | UUID (PK) | |
| name                 | string    | |
| base_currency        | string    | |
| emergency_asset_id   | UUID (FK → assets, nullable) | which asset is the emergency/savings asset |
| emergency_excluded   | boolean   | if true, excluded from risk/investment/rebalancing/inflow calcs |
| telegram_enabled     | boolean   | |
| created_at           | timestamp | |
| updated_at           | timestamp | |

### `allocation_targets`

| Field                 | Type      | Notes |
|-----------------------|-----------|-------|
| id                    | UUID (PK) | |
| portfolio_config_id   | UUID (FK) | |
| name                  | string    | category/group name |
| target_percent        | numeric, nullable | long-term target weight (may be NULL, e.g. "Individual Stocks") |
| minimum_percent       | numeric, nullable | |
| maximum_percent       | numeric, nullable | hard cap, independent of target |
| allow_new_buy         | boolean   | whether the inflow engine may buy into this category |
| priority              | integer   | used by the inflow engine to order underweight categories |
| is_active             | boolean   | |
| created_at            | timestamp | |

**Validation rule (service/domain layer, not just DB constraints):** the
sum of `target_percent` across active targets must be validated when
settings are saved. A database CHECK constraint alone cannot enforce this
aggregate rule across rows — see [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).

### `watchlist`

| Field       | Type      | Notes |
|-------------|-----------|-------|
| id          | UUID (PK) | |
| asset_id    | UUID (FK → assets) | |
| enabled     | boolean   | |
| notes       | text, nullable | |
| added_at    | timestamp | |
| removed_at  | timestamp, nullable | logical removal, not physical delete |

### `alert_rules`

| Field                      | Type      | Notes |
|----------------------------|-----------|-------|
| id                         | UUID (PK) | |
| watchlist_id               | UUID (FK → watchlist) | |
| enabled                    | boolean   | |
| allocation_alert_enabled   | boolean   | |
| allocation_max_percent     | numeric, nullable | |
| price_target_enabled       | boolean   | |
| price_target               | numeric, nullable | |
| dip_buy_enabled            | boolean   | |
| dip_buy_price              | numeric, nullable | |
| telegram_enabled           | boolean   | |
| last_triggered_at          | timestamp, nullable | |
| created_at                 | timestamp | |
| updated_at                 | timestamp | |

### `portfolio_snapshots` / `portfolio_snapshot_items`

Rather than a wide table with one hardcoded column per asset
(`snapshot.cloudz`, `snapshot.bwa`, `snapshot.azn`, ...), snapshots use a
normalized parent/child structure so new assets never require a schema
change:

**`portfolio_snapshots`**

| Field                | Type      | Notes |
|----------------------|-----------|-------|
| id                   | UUID (PK) | |
| portfolio_config_id  | UUID (FK) | |
| snapshot_at          | timestamp | when the snapshot represents |
| label                | string, nullable | |
| created_at           | timestamp | |

**`portfolio_snapshot_items`**

| Field        | Type      | Notes |
|--------------|-----------|-------|
| id           | UUID (PK) | |
| snapshot_id  | UUID (FK → portfolio_snapshots) | |
| asset_id     | UUID (FK → assets) | |
| value        | numeric   | recorded value at snapshot time |

Snapshots are point-in-time value records, distinct from transactions —
see "Snapshot ≠ Transaction" in [FINANCIAL_RULES.md](./FINANCIAL_RULES.md).
Quantities are never inferred from snapshot values.

## Future Tables (not built in Phase 1, architecture must not preclude them)

- `portfolio_snapshots` / `portfolio_snapshot_items` *(brought forward to
  Phase 3 per the master instructions above; listed here for traceability
  with the original future-tables list)*
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

## Identifiers

All entities use UUID primary keys, not auto-incrementing integers, to
support future multi-user/multi-device sync without key collisions.
