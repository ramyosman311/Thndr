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

## Mubasher Provider Decision (Phase 13 follow-up)

A newly discovered Mubasher Egypt public market-data endpoint
(`https://www.mubasher.info/api/1/stocks/prices?symbol={symbol}&country=eg`)
was investigated and, unlike EGID/EGXAPI, resulted in an actual
implemented `PriceProvider` adapter (`providers/mubasher_provider.py`,
registered as `"mubasher"`). This section documents exactly what was
verified, by whom, and what was not.

**Endpoint reachability from this sandbox: BLOCKED, same as every other
external provider host.** A direct diagnostic test from inside this
environment (`httpx`/`curl` against `www.mubasher.info`) failed with the
identical default-deny egress-proxy `403 connect_rejected` pattern that
also blocks `query1.finance.yahoo.com`, `ticker.egidegypt.com`, and
`egxapi.com` — confirmed as a policy denial (not DNS, not TLS, not a
Mubasher-side rejection) via a control request to an arbitrary
unrelated host (`example.com`, also rejected) alongside a request to an
explicitly allowlisted host (`pypi.org`, succeeded).

**Payload contract: independently verified OUTSIDE this sandbox, by the
user, not by this environment.** The response shape below was reported
as the result of a live network test performed from a real
Internet-connected device, not derived from documentation, search
snippets, or inference:

```json
[{"symbol": "TMGH", "name": "Talaat Moustafa Group Holding",
  "lastPrice": 58.50, "price": 58.50, "change": 1.25,
  "changePercentage": 2.18, "updatedAt": "2026-09-10T11:30:00.000Z"}]
```

This environment could not independently re-verify that payload (see
above), so the adapter's parsing logic is **mock-tested against this
externally-reported shape, not live-tested**. This distinction is
deliberate and load-bearing:

- `tests/test_providers_mubasher.py` (22 tests) and
  `tests/test_orchestrator_mubasher_integration.py` (3 tests) prove the
  adapter and the real registry/orchestrator correctly parse this exact
  shape, its single-object variant, and every documented failure mode —
  using `httpx.MockTransport`, never a real network call.
- No claim of measured latency, rate limits, uptime, or live pricing
  accuracy is made anywhere in this codebase or its docs. `DECISIONS.md`
  and code comments explicitly say `LIVE_NETWORK_STATUS: BLOCKED_BY_
  SANDBOX_EGRESS` rather than reporting a number that was never observed.

**Currency: not part of Mubasher's schema — a disclosed adapter decision,
not a fabricated field.** The verified payload has no currency field at
all. Because this endpoint is architecturally Egypt-only by construction
(the request always sends `country=eg`, a fixed property of the URL
template, not something looked up per-asset), the adapter reports a
fixed `"EGP"` currency for every quote. This is documented in the
adapter's own module docstring as a deliberate provider-level decision,
distinct from inferring a currency from any specific asset's
configuration.

**Naming convention: `"mubasher"` (lowercase), not `"MUBASHER"`.** The
existing registry already established an all-lowercase convention
(`"yahoo"`); introducing an uppercase name for only this one provider
would have been exactly the kind of "invent a new configuration pattern"
the project's own conventions warn against. Both the registry key and
every seeded `asset_price_configs` row use `"mubasher"`.

**Fallback ordering: Mubasher primary, Yahoo secondary — the existing
two-slot mechanism, not a new one.** `TMGH`, `ETEL`, and `EFID` are
configured with `primary_provider="mubasher"` and `secondary_provider=
"yahoo"` (retaining each asset's already-configured Yahoo symbol), so
the pre-existing primary→secondary→DB→`PRICE_UNAVAILABLE` chain
(`price_orchestrator.py`, unchanged) now tries Mubasher first and Yahoo
second, rather than requiring a new fallback concept.

**Licensing: NOT independently verified.** No terms-of-service,
attribution requirement, or redistribution policy for Mubasher's data
was found or confirmed by this environment or supplied by the user.
This is explicitly marked `LICENSING_NOT_VERIFIED` rather than assumed
free-to-use merely because the endpoint has no visible paywall — the
same standard applied to EGID and EGXAPI above.

**BWA/AZN/GOLD: unchanged, still manual-only.** Confirmed directly
against the database before and after this change — no price-config row
exists for any of the three, consistent with them being FUND/GOLD-type
assets rather than EGX-listed equities (see the EGX Provider Integration
section above).

## Telegram Delivery Decision (Phase 14)

Phase 14's own approval carried explicit, non-negotiable architectural
decisions rather than leaving them to be inferred; this section records
what was implemented and why, and the two places a deviation from the
literal instructions was necessary and disclosed.

### Alert lifecycle trace (performed before writing any code)

- **Who triggers evaluation today?** Only a human, via the Watchlist
  screen's "Evaluate" button (`components/watchlist/evaluate-panel.tsx`)
  → `POST /api/alerts/evaluate` → `alert_service.evaluate_alerts()`.
  Confirmed by grepping every caller of `evaluate_alerts` in the
  codebase: the only production call site is that one route.
- **Who creates/queues notification work?** Nobody, before Phase 14 —
  `evaluate_alerts()` calls `notifier.dispatch()` synchronously inline
  for each `is_new_trigger`, using whatever `notifier` was passed
  (default: `NullNotificationDispatcher`, a no-op).
- **Who delivered Telegram before Phase 14?** Nobody — no such
  dispatcher existed.
- **Scheduler mechanism:** none exists in this repository. Confirmed:
  no APScheduler, Celery beat, or cron dependency anywhere in
  `requirements.txt`; `app/workers/price_refresh.py` (Phase 11) is
  itself only a standalone script meant for an *external* scheduler to
  invoke — the same disclosed limitation applies here. No scheduling
  infrastructure was invented for Phase 14; `app/workers/alert_notify.py`
  follows the identical shape.

### Delivery model implemented

The on-demand `POST /api/alerts/evaluate` route was left completely
unchanged — it still calls `evaluate_alerts(session)` with no notifier
argument, which still defaults to `NullNotificationDispatcher`. This is
what guarantees the route can never depend on a live Telegram call,
without needing any special-casing in the route itself.

A new worker, `app/workers/alert_notify.py`, mirrors
`price_refresh.py`'s exact shape (`python -m app.workers.alert_notify`,
standalone, meant for external-scheduler invocation, never started by
the API process). It is the *only* code path that ever constructs a
live-HTTP-capable `TelegramNotificationDispatcher` (via its
`_build_notifier()`, which returns `NullNotificationDispatcher` unless
`TELEGRAM_ENABLED` and both credentials are set) and passes it into the
same `evaluate_alerts()` function the on-demand route also calls —
evaluation logic itself is identical either way; only which notifier
object is supplied differs.

### Enablement semantics implemented exactly as specified

Strict AND across three conditions, evaluated in
`alert_service.evaluate_alerts` itself (not delegated to the notifier),
so the gate applies regardless of which concrete `notifier` object was
passed in:

1. `TELEGRAM_ENABLED=true` AND both `TELEGRAM_BOT_TOKEN`/
   `TELEGRAM_CHAT_ID` non-empty (read via `core/config.Settings`).
2. `portfolio_configs.telegram_enabled == true` (fetched once per
   evaluation run via the existing `portfolio_repository.
   get_portfolio_config`).
3. `alert_rules.telegram_enabled == true` (per rule, already a model
   column since Phase 3).

Any one false/missing → `notifier.dispatch()` is never called for that
trigger. This was previously untested and unenforced: the pre-Phase-14
code ignored both DB flags entirely and dispatched unconditionally on
every new trigger. The one pre-existing test asserting that behavior
(`test_evaluate_dispatches_notification_only_for_new_triggers`) was
updated (not deleted) to explicitly enable all three conditions, plus
four new tests were added proving each condition independently blocks
delivery when false.

### Message format: one disclosed, necessary deviation from the literal template

The approved template specified a `Change: {change} ({change_percentage}%)`
line. No such data exists anywhere in this pipeline —
`AlertCheckResult` (the only object passed to a dispatcher) carries only
`alert_type`, `condition_met`, `is_new_trigger`, `should_clear`,
`reason`, and unitless `current_value`/`threshold_value` Decimals (a
percent for `ALLOCATION_BREACH`/`REBALANCE_SUGGESTED`, a native-currency
price for `PRICE_TARGET`/`DIP_BUY`, `None`/`None` for
`REBALANCE_SUGGESTED`). No prior/previous-close price is computed or
stored anywhere in the Price Service or alert engine. Per the phase's
own overriding instruction ("Only include fields actually available...
Do not invent market data... Do not introduce a new financial
calculation layer just for notifications"), the Change line was
**omitted** rather than fabricated. The final format instead uses
`reason` — already a complete, human-readable sentence the pure domain
check functions produce (e.g. "price 58.50 >= target 55.00") — as the
"human-readable alert condition" the template asked for, alongside the
asset symbol, an `alert_type` display label, and the notification's own
send timestamp. See `domain/notification_formatting.py`'s own docstring
for the same rationale, kept next to the code it documents.

### Provider naming and module placement (consistency, not new patterns)

`TelegramNotificationDispatcher` lives in `services/telegram_dispatcher.py`,
not `providers/` — the `providers/` package is an established, narrower
convention specifically for `PriceProvider` implementations (a data
*source*); Telegram is a data *sink*, and `notification_dispatcher.py`
(the Protocol it implements) already lives in `services/`. Placing the
implementation elsewhere would have split one concern across two
directories for no reason.

### Security

The bot token is embedded in the Telegram Bot API's own URL scheme
(`https://api.telegram.org/bot{TOKEN}/sendMessage`) — this is Telegram's
design, not a choice made here. `TelegramNotificationDispatcher.dispatch()`
never raises (every HTTP/timeout/malformed-response/API-error failure is
caught and logged internally), and every log line references only the
watchlist id, an HTTP status code, or Telegram's own non-secret
`description` field — never the request URL or the token. Verified
directly: `test_bot_token_never_appears_in_logs_on_any_failure_path`/
`..._on_http_error` assert the literal token string is absent from every
captured log record across both failure paths.

### Licensing / cost

Telegram's Bot API is free to use for a bot you create; no payment or
subscription is involved in sending messages via `sendMessage`. This is
a different situation from the paid/unverified-licensing candidates in
the EGX Provider Integration section above and is not marked
`LICENSING_NOT_VERIFIED`.

### Live network status

`api.telegram.org` was directly tested from this environment (`curl`
against `getMe`) and confirmed **BLOCKED_BY_SANDBOX_EGRESS**: DNS
resolves correctly, but the CONNECT tunnel is rejected with `403
connect_rejected` — the identical default-deny policy that independently
blocked `query1.finance.yahoo.com`, `ticker.egidegypt.com`,
`egxapi.com`, and `www.mubasher.info` (see the EGX Provider Integration
and Mubasher Provider Decision sections above). A control request to an
arbitrary unrelated host (`example.com`) was rejected identically in the
same test, confirming this is a general egress policy, not anything
specific to Telegram. No live Telegram call was attempted or claimed;
`TelegramNotificationDispatcher` is verified exclusively via mocked HTTP
transport (`test_telegram_dispatcher.py`, 13 tests) against Telegram's
real, publicly documented `sendMessage` request/response shape. The
`app.workers.alert_notify` worker was, however, run end-to-end against
the real dev database (Telegram unconfigured, so `_build_notifier()`
correctly resolved to `NullNotificationDispatcher` — zero HTTP attempts,
zero financial data changed), proving the non-Telegram parts of the
pipeline work for real.
