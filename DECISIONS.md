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

## Phase 15 — Historical Snapshots & Wealth Analytics

### Inspection findings (performed before writing any code)

The audit (see the full report exchanged with the user before
implementation) found: `portfolio_snapshots` existed only as a model,
populated exclusively by the one-time dev seed — no service, repository,
API route, or creation trigger existed anywhere. `domain/
snapshot_comparison.py` (a pure value-change utility) was already written
but wired into nothing. DEPOSIT/WITHDRAWAL/TRANSFER existed in the
Postgres native `transaction_type` enum since the original Phase 3
migration, but were unreachable at the application layer (`schemas/
transaction.py`'s `Literal["BUY","SELL"]` and `transaction_service.py`'s
two-branch if/else). No analytics endpoint, dashboard chart, or mock
chart data existed to remove — the task brief's premise that mock data
needed replacing did not match the repository's actual state, and this
was reported rather than fabricating a removal step.

### Cash Flow Semantics (approved design decision)

DEPOSIT/WITHDRAWAL are restricted to assets whose `asset_type` is `CASH`
or `SAVINGS`. This reuses the existing `transaction_type` enum values
(already present in the DB — no migration needed for this) rather than
inventing a new cash-flow representation. `average_cost` is pinned to
exactly `1` for these — never blended via the average-cost math BUY/SELL
use — so `cost_basis == quantity` trivially and no artificial unrealized
P/L appears for holding cash. A `price != 1` or `fees != 0` is rejected
outright rather than guessing what either would mean for "the deposited
amount." `TRANSFER` was explicitly NOT implemented: its meaning (external
wire vs. internal move between the user's own holdings) is genuinely
ambiguous in the existing data model, and the approved instruction was to
stop and report rather than invent a timing/semantic assumption — this
is a disclosed, deliberate gap for a future phase.

### TWR Convention (approved design decision)

"Snapshot-after-flow with algebraic pre-flow reconstruction": every
DEPOSIT/WITHDRAWAL triggers an atomic post-flow snapshot recording the
signed flow amount; the pre-flow value is reconstructed as
`post_flow_value − signed_flow` (exact, since the flow is defined as the
only thing that changed in that instant). The sub-period ending at a flow
is measured against this reconstructed value, so the flow itself
contributes exactly 0% return by construction — see
`domain/twr_engine.py` and its 16 fixture tests
(`test_domain_twr_engine.py`) for the full derivation and verification,
including the zero-starting-balance and insufficient-history edge cases
explicitly required by the approved spec.

### Deterministic Ordering (resolved without a design-review stop)

The approved instructions required the implementation to be
deterministic when multiple events share an identical or near-identical
timestamp, and to stop and report rather than invent ordering if the
existing model couldn't support it. Resolution: `(event_timestamp,
created_at, id)` ascending, using columns the schema already has
(`created_at` on every row, `id` as a final stable tiebreaker). This was
judged safely resolvable from the existing schema — not a new
architectural ambiguity requiring another stop — because it does not
assert a false real-world chronology beyond what the system actually
captured; it only guarantees the same input always produces the same
output. It also mirrors a pre-existing, unremarked limitation already in
the Phase 10 transaction write path (which likewise assumes real-world
chronological entry order, with no support for true historical
backdating/replay) — Phase 15 did not introduce or worsen that
assumption, only made its ordering rule explicit where snapshot/TWR
replay depends on it.

### EOD Convention (approved design decision)

UTC calendar day, matching every other timestamp already in this schema
(all `TIMESTAMP(timezone=True)`). Egypt-local EGX market-close semantics
were explicitly excluded from this phase's scope per the approval.

### Migration (approved, additive only)

`3210d10067b1`: five new nullable columns on `portfolio_snapshots`
(`trigger_source`, `source_transaction_id`, `total_cost_basis`,
`invested_capital`, `realized_pnl_cumulative`) plus two partial unique
indexes for idempotency (EOD-per-UTC-day, one-snapshot-per-triggering-
transaction). `total_value` was deliberately NOT added as a column — it
remains derivable as `SUM(items.value)`, per "don't duplicate
information unnecessarily." Verified before applying: the five existing
seed rows keep every new column `NULL` and violate neither partial
index (both are scoped to non-NULL/specific values the seed rows don't
have); the downgrade path was exercised (`alembic downgrade -1` /
`upgrade head` round-trip) and the full 535-test backend suite re-run
clean afterward.

### Known Limitations

See FINANCIAL_RULES.md, "Phase 15: Historical Snapshots, Cash Flow, and
Time-Weighted Return" — Known Limitations, for the full list (TRANSFER
unimplemented; a CASH/SAVINGS asset needs its own manually-set usable
price to be valued in a snapshot, since Phase 15 does not special-case
cash pricing; mixing BUY/SELL and DEPOSIT/WITHDRAWAL on the same asset is
undefined; pre-Phase-15 snapshots are excluded from analytics rather than
backfilled). Separately: the roadmap in README.md's Phase Plan originally
listed Phase 15 as "PWA" — this work was inserted under the same number
at the user's explicit direction; the original PWA/Capacitor/production-
deployment phases are renumbered further down rather than dropped (see
README.md's Phase Plan).

## Phase 16 — Financial Core & Cash Logic (P0)

### Inspection findings before implementation

Traced the full valuation data flow (`portfolio_shared.build_positions`
→ `domain/portfolio_engine.calculate_portfolio_totals` →
`portfolio_service.get_portfolio_summary`) before changing anything, per
this phase's explicit "do not invent a new accounting model blindly"
instruction. Two confirmed, distinct root causes, not one:

1. **The reported P0 bug is real and structural.** There was never a
   concept of "actual spendable cash" anywhere in the schema or domain
   layer — only `emergency_value` (one designated asset) and
   `investable_value` (`total_value - emergency_value`, an allocation-
   percentage denominator that INCLUDES every other holding, cash or
   not). The frontend displayed `investable_value` under the label
   "القيمة القابلة للاستثمار" ("Investable Value/Cash"), which is exactly
   how a user holding only stocks could see a large nonzero "investable
   cash" with literally zero free cash on hand.
2. **A previously-disclosed Phase 15 limitation compounds it.** A
   CASH/SAVINGS holding created purely via DEPOSIT/WITHDRAWAL (Phase 15)
   has no price observation unless one is manually recorded — before
   Phase 16, that meant the holding's value was silently EXCLUDED from
   every total rather than valued at its own quantity, which is worse
   for a cash-like asset than for a stock (a stock without a price is a
   genuine data gap; a CASH holding's value is definitionally its own
   quantity — cash + a note "value unknown" is nonsensical).

### Design decisions (why, not just what)

- **`investable_value`/`denominator_value`/`denominator_basis`/`total_value`/
  `emergency_value` are all UNCHANGED.** These are correctly-designed,
  already-tested Phase 5/6 concepts (the allocation-percentage
  denominator and its historical exclusion-of-emergency-cash rule) that
  have nothing wrong with them — the bug was purely that the wrong field
  was shown under the wrong label. Renaming or restructuring them would
  have been unnecessary churn across the Allocation/Strategy/Smart
  Inflow engines that already correctly depend on them.
- **`available_cash`/`invested_market_value` are NEW, additive fields**,
  computed from the exact same already-resolved positions
  (`domain/portfolio_engine.AssetPosition` gained an `asset_type` field
  purely to classify CASH/SAVINGS vs. everything else — no new I/O, no
  new query). `available_cash` uses the same CASH/SAVINGS classification
  Phase 15 already established for DEPOSIT/WITHDRAWAL eligibility,
  reusing an existing boundary rather than inventing a new one.
- **The missing-price fallback (`services/portfolio_shared.resolve_valuation_price`)
  is applied at the SAME shared position-building layer used by
  Portfolio Summary, Allocation, Smart Inflow, AND the Snapshot
  lifecycle** — not bolted on separately to just the P/L card — so a
  holding's value can never disagree between screens (an explicit
  requirement of this phase, "Portfolio Aggregation Consistency"). This
  was the highest-risk design choice: it changes `is_complete`/
  `unpriced_asset_ids` behavior for every existing consumer, so ~20
  existing tests that asserted the old "excluded, not fabricated"
  behavior for a plain missing price needed updating. Each was checked
  individually: either it needed only a mechanical constructor-signature
  fix (a new required `asset_type` field on `AssetPosition`), or it
  genuinely asserted the now-superseded exclusion policy — in the latter
  case (`test_portfolio_service.py`,
  `test_snapshot_service.py`) the test was rewritten to prove the NEW
  correct behavior (fallback used, `PENDING_SYNC`) while preserving a
  distinct case for the one scenario that is still genuinely excluded
  (no fallback price possible at all — see below).
- **The average-cost fallback is deliberately currency-gated.**
  `average_cost` is stored in the asset's own currency (never
  converted); using it as a stand-in price for an asset in a different
  currency than the portfolio's base currency, with no FX rate on hand
  to convert it, would silently produce a wrong-currency number
  presented as base-currency — exactly the class of bug
  "Base Currency & FX Conversion" already forbids. So the fallback only
  fires when `asset.currency == base_currency`; a genuinely
  cross-currency unpriced asset still falls through to the old
  exclusion behavior. This codebase is single-currency (EGP) in every
  seed/test asset today, so this gate has zero practical effect right
  now and exists purely to keep the FX guarantee intact if/when a second
  currency is ever introduced.
- **`PENDING_SYNC`/`LIVE` is a NEW, separate, two-value field — the
  existing 4-value `PriceStatus` enum (`CURRENT_PRICE_AVAILABLE`/
  `LAST_KNOWN_PRICE`/`PRICE_UNAVAILABLE`/`CURRENCY_CONVERSION_UNAVAILABLE`)
  is completely untouched** and still used, unchanged, by
  `/api/assets/{id}/price`, the admin price-config UI, and everywhere
  else it already applied. Only `HoldingPnLOut.price_status` (Portfolio
  Summary's per-holding field) changes to the simpler two-value
  vocabulary the phase's acceptance criteria explicitly require
  ("frontend should distinguish LIVE from PENDING_SYNC"). Collapsing a
  stale-but-real price and a pure cost-basis guess into the same
  `PENDING_SYNC` label was a deliberate simplification for this one
  field, not a claim that the two are equally reliable internally — the
  underlying `PriceResult`/`is_stale` distinction is preserved and still
  available via `price_is_stale`.
- **BUY/SELL were confirmed to NOT automatically move `available_cash`,
  and this was kept exactly as-is, not "fixed."** Inspecting
  `transaction_service.create_transaction` confirmed BUY/SELL only ever
  change the traded asset's own `Holding` row — there has never been an
  automatic link from a BUY/SELL to any cash balance in this codebase.
  The task's cash-accounting formulas (`Available Cash -= qty*price+fees`
  on BUY, etc.) describe a fully-integrated cash ledger that does not
  exist and was never approved — building it now would require answering
  unaddressed product questions (which CASH/SAVINGS asset gets
  debited when several exist? is a BUY rejected for insufficient cash?)
  that are exactly the kind of "invent a new accounting model blindly"
  this phase's own instructions forbid. Instead, the existing,
  already-correct scope boundary is now made explicit and tested
  (`test_phase16_financial_core.py::test_d_sell_proceeds_...`): a SELL's
  proceeds do not appear in `available_cash` until the user separately
  records a DEPOSIT for them, exactly mirroring how a DEPOSIT was already
  required to record cash at all. **This is flagged here explicitly as a
  scope decision made without a product conversation, in case the
  intended design was in fact the fully-integrated ledger** — if so, it
  is a materially larger, separate feature (a real cash-balance model
  spanning BUY/SELL/DEPOSIT/WITHDRAWAL together) that should be scoped
  and approved on its own, not inferred from formulas alone.

### A real bug found and fixed in passing (not originally in scope)

Live browser verification during this phase (screenshotting the
dashboard/portfolio pages with disposable test transactions) surfaced
that `components/portfolio/transaction-history.tsx` labeled every
non-BUY transaction "بيع" (SELL) — including a DEPOSIT, which rendered
with a red "SELL" badge. This predates Phase 16 (introduced when Phase
15 added DEPOSIT/WITHDRAWAL without updating this display) but sits
directly in the transaction-history component this phase already
touches for the newest-first ordering fix, so it was fixed alongside
rather than filed separately (`TRANSACTION_TYPE_META` now maps all four
types explicitly).

### Database / migration

None. Every field this phase reads (`asset_type`, `average_cost`,
`currency`) already existed; every new API field is a pure computation
over already-loaded data. No Alembic migration, no schema change, no
seed change.

### Regression

Full backend suite: 535 pre-existing tests, all still green (2 rewritten
to assert the new, correct fallback behavior instead of the superseded
exclusion behavior — see above; ~20 more needed only a mechanical
`asset_type` constructor argument, no assertion changes). 8 new tests
added (`test_phase16_financial_core.py`, cases A–H from the approved
spec) — 543 total. Frontend: 79 pre-existing tests green, 9 new
(`pnl-badge.test.tsx` x5, `transaction-history.test.tsx` x1, plus 3 new
`format.test.ts` cases) — 88 total.

## Phase 17 — Smart Rebalancing (P1)

### Inspection findings before implementation

Per this phase's explicit "do not invent new financial semantics"
instruction, `domain/rebalancing_engine.py` was checked first — it did
not exist yet, but FINANCIAL_RULES.md already had a "Rebalancing Engine
Rules" section written back in Phase 5/6 as a forward-looking
placeholder naming that exact file path and describing exactly this
phase's shape ("recommend, never execute"). Inspecting
`domain/allocation_engine.py` and `domain/inflow_allocator.py` (Phase
7's Smart Inflow Allocator) found that inflow_allocator ALREADY
implements almost the entire BUY side this phase asks for: target-gap
calculation, maximum-capped capacity, `allow_new_buy` gating,
emergency-bucket exclusion, `NO_TARGET`/`NO_CAPACITY`/`AT_TARGET`/
`OVER_TARGET` classification, and priority-ordered greedy distribution
across competing categories so the same cash is never double-spent —
its own module docstring already draws the line "Smart Inflow Allocator
!= Rebalancing Engine: this only answers 'if I receive X cash, where
should it go' — never 'how should existing holdings be sold to reach
target'." Given the approved spec's own BUY-side requirements (sections
7, 8, 10, 11) are word-for-word that same question — "if I have X
available cash right now, where should it go" — reusing
`calculate_inflow_allocation` directly, rather than reimplementing its
math a second time under a new name, was the only choice consistent
with "reuse existing financial rules wherever they already exist."

### Design decisions (why, not just what)

- **The REDUCE side is the one genuinely new calculation.** Nothing
  before this phase computed "how much to sell to return to maximum."
  It reads `MaximumStatus.MAXIMUM_BREACHED` directly from
  `allocation_engine.evaluate_bucket_allocation` (never re-derived) and
  applies exactly the formula the approved spec itself gives in section
  9: `required_reduction = actual_value - maximum_value`.
- **`available_cash` (Phase 16), never `investable_value` or
  `total_value`, funds the BUY side.** This was the single most
  important constraint given Phase 16 existed specifically to stop
  invested market value from being mistaken for spendable cash — the
  rebalancing engine would have silently reintroduced that exact bug if
  it funded BUYs from `denominator_value`/`investable_value` instead of
  `available_cash`.
- **`domain/inflow_allocator._capacity_and_status` was renamed to public
  `capacity_and_status`** (a pure rename, zero behavior change, existing
  call site updated, existing 25 inflow tests re-verified green) so the
  rebalancing engine could classify a category's structural eligibility
  (is there a gap, is buying permitted, is there room under the maximum)
  independent of any actual cash amount — needed specifically for the
  zero-available-cash case (Test B/I), since `calculate_inflow_allocation`
  itself refuses `new_cash_amount <= 0` (an existing, deliberately
  unchanged guard — `test_domain_inflow_allocator.py` already asserts
  `0` and negative amounts both raise `ValueError`, so that guard was
  never relaxed; the zero-cash case is instead handled by calling
  `capacity_and_status` directly and skipping the distribution pass
  entirely, since there is nothing to distribute).
- **A maximum-breached category and a BUY-eligible category are two
  disjoint lists, decided once, up front** (`breached`/`buyable` in
  `calculate_rebalancing`) — never a single list with an extra
  "unless breached" condition sprinkled into the BUY logic. This makes
  "maximum has priority over target" structurally guaranteed rather
  than a rule that could be accidentally bypassed by a future edit.
- **`RebalancingAction` (BUY/REDUCE/HOLD/NO_CAPACITY/NO_TARGET) is one
  new, small enum** — the `status` field on each recommendation reuses
  `TargetStatus`/`MaximumStatus` values verbatim instead of inventing a
  competing vocabulary for the same underlying category state (section
  15's own instruction: "do not duplicate existing enums where
  equivalent ones already exist").
- **`reason` is a full English sentence generated in the backend**,
  matching the exact precedent already set by
  `domain/strategy_validation.py`'s `explanation` field (itself English
  prose in an otherwise-Arabic-UI product) — not a new inconsistency
  introduced by this phase. The `action`/`status` badges shown in the
  UI are still translated to Arabic client-side via
  `lib/status-labels.ts`, consistent with every other enum in the app.
- **No asset-level SELL selection was built** (section 12's fallback
  explicitly allowed this): a REDUCE recommendation is category-level
  only, matching what the rest of the allocation/strategy system already
  operates on. Building "which specific asset(s) within an overweight
  category to sell" would require a new asset-selection algorithm this
  phase's own instructions forbid inventing without a product decision.

### No open scope question this phase

Unlike Phase 16 (which flagged an ambiguous BUY/SELL-vs-cash-ledger
question), Phase 17 required no new financial policy decision — every
rule it needed (target/maximum/priority/emergency/cash semantics) was
already established and simply reused.

### Database / migration

None. Every input this phase reads (`AllocationTarget.priority`/
`target_percent`/`maximum_percent`/`allow_new_buy`, `Holding`,
`AssetPosition.asset_type`) already existed; the recommendation itself
is a pure, stateless calculation — nothing is persisted.

### Regression

Full backend suite: 543 Phase-16 tests, all still green (only the
existing inflow-allocator/allocation-engine test files needed a
mechanical import-path fix from the `capacity_and_status` rename — no
assertion changed). 17 new tests (13 domain-level in
`test_domain_rebalancing_engine.py` covering scenarios A–K, 4
service/API-level in `test_rebalancing_service.py` covering real
`available_cash`-funded BUYs, REDUCE end-to-end, and Test L's no-
mutation guarantee) — 560 total. Frontend: 88 pre-existing tests green,
plus the existing `allocation-page.test.tsx` fixture extended to mock
the new endpoint and assert the recommendation renders contextually on
the bucket card.

## Phase 18 — Smart Recommendations (P1)

### Inspection findings before implementation

Per this phase's explicit "do not duplicate rebalancing mathematics"
instruction, `domain/rebalancing_engine.py` and
`services/rebalancing_service.py` (Phase 17) were inspected before
writing any new code. Two gaps were found that made direct reuse
incomplete, both resolved with minimal, additive changes rather than by
inventing a workaround inside the new engine:

1. **No existing field reliably signals "this category is the emergency
   reserve"** on a `RebalancingRecommendation`. `target_percent=None`
   combined with `allow_new_buy=None` looked at first like it could
   substitute for it, but that same combination also describes an
   ordinary, simply-unconfigured bucket with no target — the two cases
   are indistinguishable from the existing output alone. Fix: added
   `is_emergency_excluded: bool` to the domain `RebalancingRecommendation`
   dataclass (populated from the already-computed
   `RebalancingCandidate.is_emergency_excluded`, threaded through both
   `_reduction_recommendation` and `_buy_side_recommendation`). This is
   NOT added to the Pydantic `RebalancingRecommendationOut` API schema —
   Phase 18 consumes the domain layer directly, so no API contract
   change was needed or made.
2. **`rebalancing_service.get_rebalancing_recommendations` did the
   DB-fetch, candidate-building, and `calculate_rebalancing()` call all
   inline**, with no way for another service to get the same raw domain
   `RebalancingResult` without either duplicating that logic or making
   an internal HTTP call to its own endpoint. Fix: extracted that body,
   unchanged, into a new public `load_rebalancing_result()` function
   (mirroring the `services/portfolio_shared.load_priced_positions`
   naming precedent); `get_rebalancing_recommendations` is now a thin
   wrapper that rounds and shapes its output into `RebalancingOut`. This
   is a pure extraction — verified via the full pre-existing Phase 17
   test suite (`test_domain_rebalancing_engine.py`,
   `test_rebalancing_service.py`) staying green, unchanged, byte-for-byte
   assertion-for-assertion.

### Design decisions (why, not just what)

- **One decision table, applied once, in `domain/recommendation_engine.
  build_recommendations`.** Every `RebalancingAction`/`status`/
  `allow_new_buy`/`is_emergency_excluded` combination maps to at most one
  `RecommendationType`, or is silently skipped (`NO_TARGET`, emergency-
  excluded, and `ON_TARGET` all produce no recommendation — see
  FINANCIAL_RULES.md, "Smart Recommendations Engine Rules" for the full
  table). No amount, percent, or status is recomputed anywhere in this
  module — every one is read verbatim off the Phase 17
  `RebalancingRecommendation` it was given.
- **`OVERWEIGHT`-but-not-breached is `REBALANCING_OPPORTUNITY`, not
  `RESTRICTED_ACTION` or silence.** This is the one place this phase
  had to decide which *existing* signal counts as "drift beyond the
  existing configured tolerance semantics" (spec section 3). No new
  tolerance threshold was invented: `TargetStatus.OVERWEIGHT` already
  means "outside the existing `ON_TARGET_TOLERANCE_PERCENT` band,
  configured allocation_engine-side" — reusing it here rather than
  picking an arbitrary new percentage was the only choice consistent
  with "do not invent a new tolerance threshold."
- **`PORTFOLIO_HEALTHY` is a fallback, not a category-by-category
  label.** If every category resolves to a skip (`ON_TARGET`,
  `NO_TARGET`, or emergency-excluded), the *portfolio* is healthy and a
  single all-clear recommendation is returned instead of an empty list —
  but if even one category is `NO_CAPACITY` (underweight with no
  fundable cash), the result is `RESTRICTED_ACTION`, never
  `PORTFOLIO_HEALTHY`, exactly per spec section 12's explicit warning
  not to call a portfolio healthy merely because a BUY can't currently
  be funded.
- **Deterministic `id` = `f"{type.value}:{bucket_id or 'portfolio'}"`,
  explicitly excluding `evaluated_at`.** `evaluated_at` is the one field
  on `PortfolioRecommendation` that is expected to differ between two
  calls made moments apart; the "verify deterministic output" test
  requirement (Phase 18 Test J) is scoped to exclude it by design, the
  same way a timestamp column on an otherwise-idempotent record is
  routinely excluded from an equality check elsewhere in this codebase.
  `evaluated_at` itself is threaded in as an explicit parameter to
  `build_recommendations` (never `datetime.now()` called inside the pure
  domain function), following the same testable-time-injection
  precedent as `portfolio_analytics_service.get_portfolio_analytics_history`'s
  `now` parameter (Phase 15).
- **Arabic `title`/`message` are new, additive fields — never a
  translation of Phase 17's `reason`.** Phase 17's `reason` is
  deliberately English prose (matching `strategy_validation.py`'s
  existing `explanation` precedent). Rather than translate that string
  or repurpose it, Phase 18 composes its own natural Arabic copy
  straight from the same underlying numbers (`bucket_name`,
  `recommended_value`, target/maximum context) — the two fields serve
  different audiences (English reasoning trace vs. Arabic user-facing
  guidance) and are allowed to diverge in wording without either one
  being wrong.
- **No currency literal is hardcoded into the Arabic message text**
  (e.g. never "... 500 جنيه" baked into the backend string) — the amount
  is returned as a plain number in the `amount` field and the frontend
  formats it with the portfolio's actual `base_currency` via the
  existing `formatCurrency` helper, consistent with how every other
  amount in this app is presented. This is a minor, non-financial
  formatting choice, noted here rather than silently made without
  comment.

### No new financial semantics

No new target/maximum/tolerance/priority/cash/allocation/trading rule
was introduced. Every number and status this phase presents is read,
unchanged, from Phase 17's own output; the only genuinely new backend
logic is classification (Phase-17-state → user-facing type/severity) and
Arabic text composition, both pure presentation concerns.

### Database / migration

None. `is_emergency_excluded` is an addition to a domain (in-memory)
dataclass, not a database column — nothing new is persisted, and no
existing table changed shape. `alembic check` confirms no new upgrade
operations are needed.

### Regression note: pre-existing flaky test made deterministic, not

### caused, by this phase

Adding the two new Phase 18 test files shifted pytest's collection
order enough that a **pre-existing** latent bug in
`test_snapshot_service.py` (present since Phase 16, previously observed
only as a rare one-off `MissingGreenlet` failure and dismissed at the
time as transient) began failing on every run instead of occasionally.
Root cause, confirmed by bisection (`git stash -u` back to the Phase 17
baseline, deselecting the new test file, and reading the actual
traceback): two tests fetched a `PortfolioSnapshot` via a plain
`select(PortfolioSnapshot)...` and then accessed the lazily-loaded
`.items` relationship synchronously — safe only when SQLAlchemy's
identity map happens to still hold the same, already-populated Python
object from its creation earlier in the same test; unsafe (a genuine
`MissingGreenlet` under async SQLAlchemy) whenever a fresh instance is
constructed instead, which is exactly the kind of thing GC/allocation-
order timing can flip either way. The real repository code
(`snapshot_repository.py`) already avoids this by eager-loading via
`selectinload(PortfolioSnapshot.items)`; the two affected test queries
did not, and were fixed to match that same, already-established
pattern. This is a test-infrastructure fix only — no production code,
financial rule, or existing assertion changed.

### Regression

Full backend suite: 573 passed (560 Phase-17 baseline + 3 new Phase-18
service/integration tests + 10 new Phase-18 domain tests), confirmed
green across three consecutive full-suite runs after the
`test_snapshot_service.py` eager-load fix above. Frontend: 88 tests
green (one dashboard test extended to mock and assert the new
recommendations card), lint clean, `tsc --noEmit` clean, production
build clean. `alembic check`: no new upgrade operations detected.

## Phase 19 — Alerts & Notifications (P1)

### Inspection findings before implementation

Per this phase's explicit "inspect first, do not silently change the
activation hierarchy" instruction, the existing alert/watchlist/
notification code was read in full before writing anything new:

- `domain/alert_engine.py` (Phase 8) already implements five alert
  types (`ALLOCATION_BREACH`, `PRICE_TARGET`, `DIP_BUY`,
  `REBALANCE_SUGGESTED`, `INCOME_MATURITY`) with a pure, already-tested
  edge-triggered dedup mechanism (`is_new_trigger`/`should_clear`,
  latched on `alert_rules.last_triggered_at`) — a fully-built alert
  engine already existed. Phase 19 needed a persistence/inbox layer on
  top of it, not a second alert engine.
- The "both an individual asset-level activation and a main rule
  activation" behavior the task flagged is real and deliberate:
  `watchlist_service.list_evaluation_candidates` only returns entries
  where `Watchlist.enabled=True` AND `asset.is_active=True`, and
  `alert_service.evaluate_alerts` additionally skips any row where
  `rule is None or not rule.enabled`. This is confirmed, tested,
  pre-existing behavior (`test_evaluate_skips_disabled_watchlist_entries`,
  `test_evaluate_skips_disabled_alert_rules`) — not a bug. **This
  hierarchy was left completely unchanged.** The only change made was a
  frontend one: `components/watchlist/entry-card.tsx`'s
  `AlertRuleSummary` now shows one explicit, combined "التنبيهات
  نشطة/متوقفة" line plus, when off, WHICH layer is the reason (asset not
  watched, rule disabled, or both) — never altering which flag controls
  what.
- No persisted, user-facing notification/event table existed anywhere.
  `POST /api/alerts/evaluate` recomputes and returns its check results
  fresh every call — nothing is stored, so there was no way to build an
  unread/read inbox without new persistence. `alert_engine.py`'s own
  docstring already anticipated a *different* deferred table for a
  *different* problem (`alert_events`, to fix the "one shared
  `last_triggered_at` column per rule, not per condition type"
  limitation — see DATABASE.md, "Known Schema Limitations (Phase 8)").
  That is a distinct, still-unfixed, still-disclosed limitation this
  phase did not touch — the new `notifications` table serves a
  different purpose (a read/unread user inbox with severity, title,
  message, and a navigation action) and was not shaped to double as a
  fix for the shared-latch problem.
- Phase 18's `recommendation_engine.py`/`recommendation_service.py`
  were reused exactly as Phase 18 built them — `get_portfolio_recommendations`
  is called unmodified; nothing about its decision table, severities, or
  Arabic copy was touched.

### Design decisions (why, not just what)

- **A new `notifications` table was the only genuinely-required schema
  addition.** No existing table could represent "read/unread, with a
  severity/title/message/action, deduplicated across repeated
  evaluation" — see "Database / migration" below for the minimal shape
  chosen.
- **Two different sources, two different "is this new" mechanisms, by
  necessity — not by choice of elegance.** Alert-engine checks already
  carry persisted trigger state (`alert_rules.last_triggered_at`); Phase
  18 recommendations are deliberately pure/stateless (never persisted,
  recomputed fresh on every call — a Phase 18 design choice this phase
  respects rather than retrofits). Rather than adding new persisted
  state to the recommendation engine itself (which would have meant
  Phase 18's pure functions gaining a database dependency, violating its
  own "no I/O" contract), the notification layer derives "new vs. still
  active" by diffing the current notify-worthy recommendation ids
  against which `RECOMMENDATION_ALERT` notifications are already active
  in the `notifications` table. This keeps `recommendation_engine.py`
  untouched and pure, at the cost of the dedup logic living one layer
  higher than the alert-engine case — an explicit, deliberate asymmetry,
  not an oversight.
- **A partial unique index (`source_id` WHERE `resolved_at IS NULL`)
  enforces duplicate protection at the database level**, not only in
  application code — the same category of guarantee `uq_alert_rules_watchlist_id`
  already provides elsewhere in this schema, applied to a new problem.
- **Only `BREACH_RESOLUTION` (CRITICAL) and `RESTRICTED_ACTION`
  (WARNING) recommendations become notifications.** The Phase 19
  objective itself says "tell the user when something important
  happens — without creating noise." `CASH_DEPLOYMENT`/
  `REBALANCING_OPPORTUNITY` (INFO) and `PORTFOLIO_HEALTHY` (SUCCESS) are
  already visible on the Dashboard's Recommendations card (Phase 18);
  duplicating every INFO-level recommendation into the Notification
  Center as well would be exactly the noise the objective warns against.
  This is a scope decision, documented here rather than silently made.
- **`PORTFOLIO_HEALTH_ALERT` (`NotificationCategory`) is defined but
  never emitted.** The task's spec asked for four conceptual categories;
  inspection found no existing signal that distinctly means "portfolio
  health" without already being covered by `RECOMMENDATION_ALERT` or
  `ALLOCATION_ALERT`. Rather than inventing a synthetic "portfolio health
  score" with no upstream financial basis, the category is reserved in
  the enum (so a real future signal has somewhere to go) but the current
  engine never produces one — a documented decision boundary per this
  phase's own "if ambiguous, STOP and document" instruction, not a
  silently-invented financial concept.
- **In-app visibility is deliberately never gated by the Phase 14
  Telegram AND-gate.** That gate answers "should an external Telegram
  message be sent" — a question about a specific delivery channel a user
  may never configure. In-app notifications answer a different question
  ("does the user see this at all"), which should not depend on whether
  they've set up Telegram. `notification_service.py` calls
  `evaluate_alerts()` with no notifier, exactly as the existing
  `POST /api/alerts/evaluate` route already does, so the AND-gate is
  never even evaluated on this path.
- **Evaluation happens synchronously on `GET /api/portfolio/notifications`**,
  not via a new background worker. The task explicitly said "prefer the
  simplest architecture... do not introduce Celery, Redis, queues, cron
  infrastructure... unless genuinely required and already supported."
  This project's only existing scheduled mechanism
  (`app/workers/alert_notify.py`, Phase 14) is a standalone external-cron
  script solely for Telegram delivery — extending its scope to also
  populate the Notification Center would have coupled two independent
  concerns (external delivery timing vs. in-app data freshness) for no
  real benefit, since a synchronous evaluate-then-list on read is exactly
  as simple and already the established pattern for
  `POST /api/alerts/evaluate`. The new worker script was not touched.
- **No new API surface beyond what was actually needed.** Three
  endpoints only: `GET /api/portfolio/notifications` (evaluate + list),
  `PATCH /api/portfolio/notifications/{id}/read`, and
  `POST /api/portfolio/notifications/read-all`. No separate
  `GET /api/portfolio/alerts` was added — the existing
  `POST /api/alerts/evaluate` already serves the raw, ephemeral
  diagnostic listing; adding a second read-only alerts endpoint would
  have duplicated it for no new capability.
- **`AlertEvaluationEntryOut.bucket_name` was added as one additive,
  nullable field** so an allocation-related notification can reference
  the actual bucket name instead of only the asset symbol — the smallest
  change that let the new Arabic copy read naturally
  ("Individual Stocks: تجاوز نسبة التنبيه المحددة" rather than always
  falling back to the ticker). Every existing test against this schema
  remained green unchanged, confirming the field is genuinely additive.

### Database / migration

One new table, `notifications` (migration `c49911658945_phase_19_notifications`):
`id` (UUID PK), `source_id` (indexed, dedup key), `category`/`severity`/
`action` (native Postgres enums — `notification_category`/
`notification_severity`/`notification_action`, matching this schema's
existing convention for `asset_type`/`transaction_type`), `title`,
`message`, `target_category`, `target_asset`, `read_at` (nullable —
`NULL` = unread, avoiding a redundant separate boolean), `resolved_at`
(nullable — `NULL` = the underlying condition is still active), and
`created_at`. A partial unique index enforces at most one active row per
`source_id`. No existing table's shape changed. `alembic check` confirms
no further upgrade operations are needed after this migration.

### Regression

Full backend suite: 586 passed (573 Phase-18 baseline + 13 new Phase-19
tests: 10 domain-adjacent/service-level scenarios A–J plus 3 read-state
tests), confirmed green across three consecutive full-suite runs.
Frontend: 98 tests passed (88 Phase-18 baseline + 10 new: the
Notification Center page and the header bell), lint clean, `tsc --noEmit`
clean, production build clean (new `/notifications` route generated).
`alembic check`: no unexpected migration after `c49911658945`.
