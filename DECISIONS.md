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

## Phase 13 — EGX Market Data Provider Integration

Objective: a zero-cost, technically-verified EGX equity price feed,
integrated through the existing Phase 11 `PriceProvider` abstraction. The
two prioritized candidates — EGID/Ticker DelayedFeed and EGXAPI — were
both investigated to the fullest extent this environment allows and
**neither cleared verification**. This section documents exactly what was
checked, what was found, and why the conclusion is not fabricated.

### Network access: LIVE_PROVIDER_NETWORK_TEST = BLOCKED

This sandbox's outbound HTTPS egress proxy denies (`403`, organization
policy) every one of: `ticker.egidegypt.com`, all of `egidegypt.com`
(including `www.`), `egxapi.com`, and — re-confirmed here — `finance.yahoo.com`
/ `query1.finance.yahoo.com` (the same block already documented in
`providers/yahoo_provider.py`'s module docstring since Phase 11). This was
verified two independent ways: direct `curl` through the sandbox proxy
(`CONNECT tunnel failed, response 403` for every host) and the `WebFetch`
tool (`EGRESS_BLOCKED` for every host). Per this environment's own proxy
guidance, a `403` policy denial is reported, not retried or routed around.
**No real HTTP request could be executed against either candidate
provider, or against Yahoo, from this environment.**

### EGID / Ticker DelayedFeed — UNAVAILABLE

- **Identity (credible):** EGID is a real, wholly-owned subsidiary of the
  Egyptian Exchange (EGX) and has been described publicly as the
  exchange's exclusive/sole authorized market-data provider for roughly
  25 years. This is not a fly-by-night vendor.
- **Technical contract: UNVERIFIED.** No endpoint path, authentication
  scheme, request format, response JSON shape, symbol format, or
  timestamp format could be found anywhere public — not on the (blocked)
  `ticker.egidegypt.com` site, and not via web search, which surfaced only
  a marketing/company-overview page (`egidegypt.com/index.php/services/
  market-data/`), never a developer/API-reference page. Building an
  adapter would have meant inventing field names and an endpoint shape
  with zero verification — exactly what this phase's "do not fabricate"
  rule forbids.
- **Cost: likely NOT zero-cost. LICENSING_NOT_VERIFIED, leaning paid.**
  EGID's own public description of its "Delayed Data Feed" calls it "a
  cost-effective alternative to real-time data feeds" — language that
  describes a priced tier below a (also priced) real-time tier, not a
  free public API. There is no public self-serve signup or API-key flow;
  the only published contact path is a sales phone number and email.
  This is inconsistent with the phase's hard "zero monetary cost, no
  paid subscription" requirement.
- **Conclusion:** UNAVAILABLE for this phase. Not implemented. Revisit
  only if EGID confirms (in writing, to a human, since no API self-serve
  path exists) a genuinely free tier with a published technical contract.

### EGXAPI — UNAVAILABLE

- **Technical contract: PARTIALLY_VERIFIED, but wrong shape.** Public
  search results (no live site access) show EGXAPI is architected as a
  versioned REST trading API (e.g. `https://api.egxapi.com/v2/orders`)
  offering order placement/replacement/cancellation, a live order book,
  and a paper-trading account that can be flipped to a live trading
  account with one header change. It also advertises real-time/historical
  quotes as one of several features.
- **Scope conflict: this is a brokerage/order-execution API, not a
  market-data-only API.** Phase 13's own boundary explicitly excludes
  "broker integration," "order execution," and "auto trading." Even
  reading only its quote endpoint would mean depending on an SDK/account
  model built around live trading capability — the wrong foundation to
  build on for a market-data-only feature, and a real risk that a future
  maintainer extends the same integration into order placement by
  accident, which this project must never do.
- **Cost/licensing: advertised as free, but LICENSING_NOT_VERIFIED.**
  Marketing copy claims "free forever" / "no card required," but no
  terms-of-service text describing rights to consume its market-data feed
  independently of its trading platform could be found or verified.
  "Publicly advertised as free" is explicitly listed in this phase's own
  instructions as something that must never be assumed sufficient on its
  own.
- **Conclusion:** UNAVAILABLE for this phase, primarily on scope grounds
  (broker-API architecture) independent of the network block and the
  unverified licensing.

### Yahoo Finance (existing, Phase 11) — remains the sole implemented automated provider

No code changed in `providers/yahoo_provider.py`, `providers/registry.py`,
`services/price_orchestrator.py`, or `services/price_service.py` — the
generic primary→secondary→DB→`PRICE_UNAVAILABLE` fallback chain, the
manual-vs-automated precedence rule, and the weekend-aware stale-policy
classification are all unchanged and still fully covered by Phase 11's
own test suite.

What Phase 13 *did* do: verify, per-symbol, whether Yahoo actually covers
the real EGX equities already in this project's seed data, and configure
exactly those — using the existing `AssetPriceConfig` administration
layer (Phase 12), not new code.

- **Seed data has only three EGX-listed equities**, not five. `TMGH`,
  `ETEL`, and `EFID` are `asset_type=STOCK` with `market="EGX"`. `BWA`
  and `AZN` — despite being named as "potential EGX assets" in this
  phase's own instructions — are `asset_type=FUND` with no `market` set:
  they are mutual-fund NAV holdings (Beltone Wafra, Azimut Naqd), not
  exchange-traded equities. **This is a correction to the task brief, not
  an assumption followed blindly** — confirmed directly from
  `app/seed/data.py`, not guessed. No stock-exchange provider (Yahoo, or
  a future EGID/EGXAPI) is applied to `BWA`/`AZN`; a fund's price comes
  from its NAV, a different data domain entirely, out of scope here.
- **Per-symbol Yahoo verification, PARTIALLY_VERIFIED (not VERIFIED):**
  Yahoo itself is network-blocked in this sandbox (see above), so no live
  `v8/finance/chart` call could confirm any of these. Confidence instead
  comes from independently indexed public Yahoo Finance quote pages found
  via web search for the *exact* symbol-plus-company-name pair:
  - `TMGH` → `TMGH.CA` — a specific, unambiguous Yahoo Finance page for
    "Talaat Moustafa Group Holding (TMGH.CA)" was found, with a plausible
    EGP price. Configured with `automated_fetching_enabled=True`.
  - `ETEL` → `ETEL.CA` — same basis, a specific Yahoo Finance page for
    "Telecom Egypt Company S.A.E. (ETEL.CA)" with a plausible EGP price
    (Yahoo also separately lists it under a longer `EGS48031C016.CA`
    security code, but the simpler `ETEL.CA` form independently resolves
    too). Configured with `automated_fetching_enabled=True`.
  - `EFID` → no simple `.CA` ticker could be found at all; only a longer
    security-code symbol, `EGS305I1C011.CA` ("Edita Food Industries
    S.A.E."), was found. Configured with that `provider_symbol`, but
    **`automated_fetching_enabled=False`** — left off pending a human
    confirming it works via the existing single-asset
    `POST /api/assets/{id}/price/refresh` endpoint before it is trusted
    to run unattended in the background worker.
  - **A real, demonstrated reason for this per-symbol carefulness rather
    than assuming a shared `.CA`-suffix pattern:** naive pattern-following
    (`BWA` → `BWA.CA`, `AZN` → `AZN.CA`) was checked and rejected —
    `BWA.CA` on Yahoo Finance resolves to BorgWarner Inc. (an unrelated
    US auto-parts company) and `AZN.CA` resolves to AZN Capital Corp. (an
    unrelated Canadian company), not to the Egyptian funds of the same
    short symbol. Configuring either blindly would have silently stored
    a completely wrong instrument's price under the Egyptian asset's
    label — exactly the failure mode this phase's "no assumptions" rule
    exists to prevent. (This is moot in practice since `BWA`/`AZN` are
    funds and get no provider at all — see above — but it is the concrete
    evidence for why every other per-symbol mapping here was individually
    checked rather than inferred from a pattern.)
- **Observed delay: NOT MEASURED.** No live call was possible, so no
  actual delay figure is claimed. The existing generic `AssetType.STOCK`
  default stale threshold (60 minutes, `domain/stale_policy.py`, Phase 11,
  unchanged) is left as the authoritative threshold for all three — no
  EGX-specific number was fabricated.

### Database

**NO MIGRATION REQUIRED.** `alembic current` is unchanged at `7dbad9d06fb1`
(the Phase 11 head) before and after this phase. `asset_price_configs`
already had every column this integration needed (`primary_provider`,
`primary_provider_symbol`, `automated_fetching_enabled`); only rows were
added, via the existing idempotent seed module
(`seed_asset_price_configs`, keyed by `asset_id`, "create if missing" —
never overwrites a config an admin already hand-edited via the Phase 12
UI).

### Rejected alternatives and why (summary)

| Provider | Verdict | Primary reason |
|---|---|---|
| EGID / Ticker DelayedFeed | UNAVAILABLE | No verifiable technical API contract; publicly described as a paid tier, not a free API; network-blocked |
| EGXAPI | UNAVAILABLE | Architecturally a brokerage/order-execution API (scope conflict); licensing for market-data-only use unverified; network-blocked |
| Yahoo Finance (`BWA.CA`/`AZN.CA` naive pattern) | REJECTED | Resolves to unrelated foreign companies, not the Egyptian funds — confirmed via search, not assumed |
| Yahoo Finance (`TMGH.CA`, `ETEL.CA`, `EGS305I1C011.CA` for `EFID`) | PARTIALLY_VERIFIED, adopted | Existing Phase 11 provider; specific per-symbol web evidence found; fails safe (a wrong/absent quote is simply not stored, per Phase 11's existing provider-error handling) |

### What a future phase needs to do to actually integrate EGID or EGXAPI

1. Obtain real, human-confirmed API documentation or a working example
   request/response pair for whichever provider is pursued (this cannot
   be done from within this sandboxed environment).
2. Confirm, in writing, that the provider's terms permit using its
   market-data feed (not its trading/order functionality) at zero cost
   for a personal application.
3. Only then implement a `PriceProvider` adapter against the *actual*
   verified contract — never against an inferred/guessed one — following
   the exact pattern `providers/yahoo_provider.py` already establishes
   (raise the appropriate `ProviderError` subclass for every failure
   mode, never fabricate a partial quote).
4. Register it in `providers/registry.py`; no other file needs to change
   — the orchestrator, price service, and admin UI are already fully
   generic over provider name.
