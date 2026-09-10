# Architectural Decision Log

This document records domain-model decisions that are not obvious from
the schema or code alone — what is intentionally global vs.
portfolio-specific, what single-portfolio assumptions remain, and why.
It exists so a future phase does not have to re-derive these decisions
by reverse-engineering the code, and does not accidentally "fix" a
deliberate simplification into a regression.

## Phase 12 — Domain Readiness Audit

Performed before any Phase 12 code was written, per the explicit
instruction to inspect and audit before designing or implementing.

### 1. Entities confirmed global/shared (not portfolio-specific)

- **Asset** (`assets`) — an investment instrument, independent of any
  portfolio. No `portfolio_id` column, and none should be added: the
  same asset (e.g. a stock) is meant to be referenceable by more than
  one future portfolio without being duplicated.
- **AssetPriceConfig** (`asset_price_configs`) — provider/symbol/
  staleness configuration is a property of the asset itself, not of any
  portfolio that happens to hold it. Correctly 1:1 with `assets`.
- **AssetPrice** (`asset_prices`) — a market/NAV price observation.
  Prices are a fact about the asset in the world, not about a specific
  portfolio's holding of it. Correctly keyed by `asset_id` only.
- **FxRate** (`fx_rates`) — a currency-pair observation, independent of
  both asset and portfolio.
- **Watchlist** (`watchlist`) — currently scoped only by `asset_id`
  (globally unique per asset), with no portfolio or user scoping.
  **Decision: left as global for Phase 12, not arbitrarily changed.**
  This mirrors how `holdings`/`transactions` are scoped today (see
  finding #3 below) and a real design choice here (global vs.
  portfolio-specific vs. future-user-specific) should be made
  deliberately, with the multi-portfolio/multi-user migration it would
  require, not as an incidental side effect of an administration phase.
- **AlertRule** (`alert_rules`) — 1:1 with `watchlist_id`, so it
  inherits Watchlist's current global scoping. Not redesigned.

### 2. Entities confirmed correctly portfolio-specific

- **Portfolio Config** (`portfolio_configs`) — name, base currency,
  emergency asset, emergency exclusion, Telegram settings. The table
  itself has no singleton constraint (structurally supports multiple
  rows already); see finding #4 for the one place the *application*
  currently treats it as a singleton.
- **Strategy Bucket** (`strategy_buckets`) — `portfolio_config_id` FK
  with `ON DELETE CASCADE`, `UniqueConstraint(portfolio_config_id, name)`.
  Correctly scoped; a bucket named "Growth" in one future portfolio
  would not collide with a "Growth" bucket in another.
- **Allocation Target** (`allocation_targets`) — `portfolio_config_id` +
  `strategy_bucket_id` FKs, `UniqueConstraint(portfolio_config_id,
  strategy_bucket_id)`, CHECK constraints for percent ranges and
  `minimum_percent ≤ maximum_percent`. Correctly scoped.
- **PortfolioSnapshot / PortfolioSnapshotItem** (`portfolio_snapshots`,
  `portfolio_snapshot_items`) — scoped via `portfolio_config_id`.
  Correctly scoped.

### 3. The deepest single-portfolio assumption found: Holding and Transaction have no portfolio scope at all

`holdings` and `transactions` are keyed only by `asset_id` — neither
table has a `portfolio_config_id` column. `holdings` additionally has a
`UniqueConstraint` on `asset_id` alone, meaning the schema allows
exactly **one holding per asset in the entire system**, not one per
`(portfolio, asset)` pair.

**This is a real architectural blocker for future multi-portfolio
support** (the same asset could not be held independently by two
portfolios), but fixing it requires:
- adding a `portfolio_config_id` column to both tables,
- changing `holdings`' unique constraint to `(portfolio_config_id,
  asset_id)`,
- backfilling every existing row with a `portfolio_config_id`,
- and updating every repository/service query that reads or writes
  `holdings`/`transactions` to filter by portfolio.

Per the explicit Phase 12 instruction — "if full multi-portfolio support
requires a broad migration, DO NOT perform it in Phase 12; document it
as a Phase 15+ requirement" — **this was identified and documented, not
fixed.** No code change was made to either table or to any of the
services that read them.

### 4. The one genuine single-portfolio code-level assumption: `get_portfolio_config()`

`app/repositories/portfolio_repository.py`'s `get_portfolio_config`
executes `SELECT ... FROM portfolio_configs LIMIT 1`. Its own existing
docstring already states: "The schema supports multiple
portfolio_configs, but the application is single-portfolio for now."
This is the *only* code-level place that assumes exactly one portfolio.
It was **not changed** in Phase 12 — every new admin service (portfolio
config, strategy buckets, allocation targets) resolves "the" portfolio
through this same existing function, consistent with how
`strategy_service.py` (Phase 6, unchanged) already does. Introducing a
second, different way to resolve "the current portfolio" would have
created inconsistency without actually delivering multi-portfolio
support.

A grep across `app/services/`, `app/repositories/`, and
`app/api/routes/` for `.limit(1)`, `scalar_one_or_none()`, and
`get_portfolio_config` found no other hidden portfolio-singleton
assumption — every other occurrence is a legitimate unique-lookup-by-key
or latest-observation query (e.g. "the most recent price for this
asset"), not a masked multi-portfolio bug.

### 5. Future multi-user blockers (not addressed, per explicit scope boundary)

- No `users` table exists, and none was added. Every entity implicitly
  belongs to "the" single operator of this deployment.
- `Asset.strategy_bucket_id` is a single-value foreign key. If a future
  phase introduces multiple portfolios that both reference the same
  asset, that asset could only ever have one strategy-bucket assignment
  shared across every portfolio holding it — a real conceptual mismatch
  worth flagging now, since a bucket assignment is arguably a
  portfolio-specific strategy decision, not a property of the asset
  itself. **Documented, not fixed** — resolving it cleanly likely means
  moving bucket assignment from `Asset` to a join entity keyed by
  `(portfolio_config_id, asset_id)`, which is itself entangled with
  finding #3's larger holdings/transactions migration.
- `AlertRule`/`Watchlist` global scoping (finding #1) would need a
  deliberate decision — global, per-portfolio, or per-user — before a
  multi-user phase could proceed; no such decision was forced in Phase
  12.

### 6. Changes genuinely required now (and made)

- None to the schema. The audit's conclusion was that the existing
  schema already supported everything the Phase 12 administration layer
  needed (Asset, AssetPriceConfig, PortfolioConfig, StrategyBucket,
  AllocationTarget were all already correctly modeled for CRUD
  administration). See DATABASE.md, "Phase 12: Domain Readiness Audit —
  No Migration Required."

### 7. Changes deliberately deferred

- Adding `portfolio_config_id` to `holdings`/`transactions` (finding #3)
  — Phase 15+.
- Resolving `Asset.strategy_bucket_id`'s single-value-FK conflict with
  future multi-portfolio bucket assignment (finding #5) — coupled to the
  same future migration.
- Deciding Watchlist/AlertRule's scoping model (global vs.
  portfolio-specific vs. user-specific) — deferred until a concrete
  multi-user or multi-portfolio phase forces the decision; a decision
  under Phase 12 would have been speculative.
- Introducing a `users` table or any authentication/authorization
  primitive — explicitly out of scope for Phase 12 per the task's own
  scope boundary.

## Asset Deletion Policy (Decision)

Hard deletion is permitted only when an asset has zero holdings,
transactions, watchlist entries, snapshot items, and price observations.
Otherwise, the caller must deactivate (`is_active=false`) instead. This
is intentionally **stricter** than the database's own `ON DELETE
CASCADE` on `asset_prices` (a Phase 11 decision to treat price history
as safely cascade-able pricing metadata) — Phase 12's business-layer
rule treats existing price observations as historical data worth
protecting regardless of what the schema alone would allow. See
FINANCIAL_RULES.md, "Asset Deletion Policy."

## Base Currency Change Policy (Decision)

Once any transaction exists anywhere in the system, `base_currency`
becomes immutable through the admin API (409 on attempted change). There
is no implemented mechanism to safely reinterpret historical transaction
values under a new base currency, so the system refuses rather than
silently reinterpreting financial history. See FINANCIAL_RULES.md, "Base
Currency Change Policy."

## Strategy Validation Ownership (Decision)

Per-row constraints (percent ranges, min ≤ max, duplicate names/targets)
are enforced at write time by the new admin service, mirroring the
database's own CHECK/UNIQUE constraints. The aggregate "does this
portfolio's allocation sum to 100%" question is never checked or
enforced by a write — it remains exclusively the job of the existing
read-only `GET /api/portfolio/strategy/validation` endpoint
(`strategy_service.py`, Phase 6). This preserves the system's existing,
correct behavior of reporting an incomplete configuration rather than
blocking or silently completing it. See FINANCIAL_RULES.md, "Strategy
Validation Ownership."

## Price Configuration Ownership (Decision)

`price_config_service.py` (Phase 12) owns only `asset_price_configs`
CRUD. It never writes to `asset_prices` and never calls a
`PriceProvider`. Reading current prices remains `price_service.py`'s job
(Phase 11); fetching new prices remains `price_orchestrator.py`'s job
(Phase 11, background-only, plus the one explicit user-initiated
exception at `POST /api/assets/{id}/price/refresh`). Three services,
three non-overlapping responsibilities.
