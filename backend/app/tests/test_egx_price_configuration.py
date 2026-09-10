"""Phase 13 -- EGX price configuration correctness and financial integrity.

No PriceProvider adapter exists for EGID or EGXAPI (see DECISIONS.md,
"EGX Provider Decision (Phase 13)" for why both failed verification). A
Mubasher adapter was added later (see DECISIONS.md, "Mubasher Provider
Decision") and is now `primary_provider` for TMGH/ETEL/EFID, with Yahoo
(Phase 11) retained as `secondary_provider` -- the seed data wires this
onto the real EGX-equity assets, and corrects an asset-classification
error in the original Phase 13 task brief (BWA/AZN are FUND-type assets,
not EGX equities, and must never receive a stock-market provider). This
file locks in that correctness plus proves the seeding operation never
touches pre-existing financial history -- the same byte-for-byte proof
pattern as test_admin_financial_integrity.py (Phase 12), applied here to
`seed_asset_price_configs` specifically.

Provider-level behavior (HTTP error, timeout, malformed response, missing
price, invalid timestamp) and orchestrator-level behavior (primary ->
secondary fallback, manual precedence, batch isolation) are NOT
re-tested here: test_providers_yahoo.py, test_providers_mubasher.py, and
test_price_orchestrator.py already cover that generic machinery
completely, using fakes/mocks that are provider-name-agnostic.
Duplicating them here would test nothing new.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import AssetPriceConfig, Holding, PortfolioSnapshot, PortfolioSnapshotItem, Transaction, TransactionType
from app.models.enums import AssetType
from app.providers.registry import is_registered_provider_name
from app.seed.data import SEED_ASSET_PRICE_CONFIGS, SEED_ASSETS
from app.seed.seed import seed_asset_price_configs, seed_assets


# --- Provider registry sanity -------------------------------------------


async def test_no_egid_or_egxapi_provider_is_registered():
    """Neither candidate cleared verification (network-blocked, and for
    EGXAPI, an unresolved broker-scope/licensing concern -- see
    DECISIONS.md). The registry must not claim to support either, since
    that would let an admin configure a provider that silently does
    nothing (get_provider returns None -> "not registered" failure) or,
    worse, invite someone to implement a fabricated adapter later without
    revisiting the verification gate."""
    assert is_registered_provider_name("egid") is False
    assert is_registered_provider_name("egxapi") is False
    assert is_registered_provider_name("yahoo") is True
    assert is_registered_provider_name("mubasher") is True


# --- EGX symbol mapping is data-driven, never hardcoded in application code


async def test_seed_asset_price_configs_only_covers_egx_listed_equities():
    egx_symbols = {spec["symbol"] for spec in SEED_ASSETS if spec.get("market") == "EGX"}
    assert egx_symbols == {"TMGH", "ETEL", "EFID"}
    assert set(SEED_ASSET_PRICE_CONFIGS.keys()) == egx_symbols


async def test_fund_assets_are_never_assigned_an_egx_equity_provider():
    """BWA and AZN were listed as 'potential EGX assets' in the Phase 13
    brief, but the seed data classifies both as asset_type=FUND with no
    `market` set -- they are mutual-fund NAV holdings, not EGX-listed
    equities. Configuring a stock-exchange provider (Yahoo, or a future
    EGID/EGXAPI adapter) against a fund would silently misrepresent its
    price source. This is verified here, not just asserted in a comment."""
    fund_symbols = {spec["symbol"] for spec in SEED_ASSETS if spec["asset_type"] == AssetType.FUND}
    assert fund_symbols == {"BWA", "AZN"}
    assert fund_symbols.isdisjoint(SEED_ASSET_PRICE_CONFIGS.keys())


# --- Financial integrity: seeding price config never touches pre-existing
# --- holdings, transactions, or snapshots for the same assets.


async def test_seeding_egx_price_configs_does_not_alter_existing_holding(db_session):
    assets_by_symbol = await seed_assets(db_session)
    tmgh = assets_by_symbol["TMGH"]
    holding = Holding(asset_id=tmgh.id, quantity=Decimal("42"), average_cost=Decimal("55.30"))
    db_session.add(holding)
    await db_session.commit()

    await seed_asset_price_configs(db_session, assets_by_symbol)
    await db_session.commit()

    reloaded = (await db_session.execute(select(Holding).where(Holding.asset_id == tmgh.id))).scalar_one()
    assert reloaded.quantity == Decimal("42.00000000")
    assert reloaded.average_cost == Decimal("55.30000000")


async def test_seeding_egx_price_configs_does_not_alter_existing_transaction(db_session):
    assets_by_symbol = await seed_assets(db_session)
    etel = assets_by_symbol["ETEL"]
    txn = Transaction(
        asset_id=etel.id,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("100"),
        price=Decimal("32.77"),
        fees=Decimal("2.00"),
        transaction_date=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.add(txn)
    await db_session.commit()
    txn_id = txn.id

    await seed_asset_price_configs(db_session, assets_by_symbol)
    await db_session.commit()

    reloaded = (await db_session.execute(select(Transaction).where(Transaction.id == txn_id))).scalar_one()
    assert reloaded.quantity == Decimal("100.00000000")
    assert reloaded.price == Decimal("32.77000000")
    assert reloaded.fees == Decimal("2.00")


async def test_seeding_egx_price_configs_does_not_alter_existing_snapshot_item(db_session):
    from app.models import PortfolioConfig

    assets_by_symbol = await seed_assets(db_session)
    efid = assets_by_symbol["EFID"]
    config = PortfolioConfig(name="Snapshot Test Portfolio", base_currency="EGP")
    db_session.add(config)
    await db_session.flush()
    snapshot = PortfolioSnapshot(portfolio_config_id=config.id, snapshot_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(snapshot)
    await db_session.flush()
    item = PortfolioSnapshotItem(snapshot_id=snapshot.id, asset_id=efid.id, value=Decimal("999.99"))
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    await seed_asset_price_configs(db_session, assets_by_symbol)
    await db_session.commit()

    reloaded = (
        await db_session.execute(select(PortfolioSnapshotItem).where(PortfolioSnapshotItem.id == item_id))
    ).scalar_one()
    assert reloaded.value == Decimal("999.99")


async def test_seeding_egx_price_configs_is_additive_never_overwrites_an_existing_config(db_session):
    """If an admin has already hand-configured an asset's pricing (Phase
    12 UI), re-running the seed must not clobber it -- same 'create if
    missing' contract as every other seed function."""
    assets_by_symbol = await seed_assets(db_session)
    tmgh = assets_by_symbol["TMGH"]
    existing = AssetPriceConfig(
        asset_id=tmgh.id,
        primary_provider="yahoo",
        primary_provider_symbol="CUSTOM-OVERRIDE.CA",
        automated_fetching_enabled=False,
        lock_manual=True,
    )
    db_session.add(existing)
    await db_session.commit()

    await seed_asset_price_configs(db_session, assets_by_symbol)
    await db_session.commit()

    result = await db_session.execute(select(AssetPriceConfig).where(AssetPriceConfig.asset_id == tmgh.id))
    configs = result.scalars().all()
    assert len(configs) == 1
    assert configs[0].primary_provider_symbol == "CUSTOM-OVERRIDE.CA"
    assert configs[0].lock_manual is True
