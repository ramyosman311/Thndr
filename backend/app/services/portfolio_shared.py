"""Small helpers shared by the Portfolio, Strategy, and Smart Inflow
services, so the emergency-bucket lookup and position-building logic
exist in exactly one place (see Phase 7 approval, "Reuse Existing
Engines" — refactored here rather than left duplicated across
portfolio_service.py and strategy_service.py, and rather than adding a
third copy for the inflow service).

Phase 11: this is also the one place `holdings.current_price` would
have been read — it no longer is. Every position's price now comes from
services/price_service.py (the single price read path for the whole
system), already converted into the portfolio's base currency, so
`domain/portfolio_engine.py`'s pure math never has to know about
currencies or providers at all (see FINANCIAL_RULES.md, "Single Source
Of Truth For Current Price").
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.portfolio_engine import AssetPosition
from app.domain.price_types import PriceResult, PriceStatus
from app.models import Asset
from app.services import price_service


@dataclass(frozen=True)
class ResolvedValuation:
    """The price actually used to value one holding right now, plus
    whether that price is a live, trustworthy market price (Phase 16).

    `price` is `None` only in the true worst case: no live/stale price
    observation exists AND no safe same-currency cost-basis fallback is
    available either (see `resolve_valuation_price`) -- exactly the
    existing Phase 11 "never fabricate" contract for that one case.
    `is_live` is True only when `price` is a genuinely current market
    price (`PriceStatus.CURRENT`); it is False for a stale last-known
    price and for a cost-basis fallback alike, since neither should be
    presented to a user as a confirmed live price (see
    FINANCIAL_RULES.md, "Price Confidence: LIVE vs PENDING_SYNC")."""

    price: Decimal | None
    is_live: bool


def resolve_valuation_price(
    price_result: PriceResult | None,
    *,
    average_cost: Decimal,
    asset_currency: str,
    base_currency: str,
) -> ResolvedValuation:
    """Phase 16 missing-price fallback policy, used by every valuation
    consumer (portfolio totals AND the per-holding P/L card) so both
    always agree on the same number for the same holding (see
    FINANCIAL_RULES.md, "Portfolio Aggregation Consistency").

    Fallback priority:
    1. A genuinely current price (`PriceStatus.CURRENT`) -- LIVE.
    2. A real but stale last-known observation (`PriceStatus.LAST_KNOWN`)
       -- still a real, previously-recorded market price, just not live.
    3. The holding's own average cost, but ONLY when the asset is
       denominated in the portfolio's own base currency -- average_cost
       is stored in the asset's native currency (see
       domain/transaction_engine.py), so using it as a stand-in price
       across a currency boundary would silently mix currencies. Cross-
       currency assets with no usable price fall through to `None`
       instead (see FINANCIAL_RULES.md, "Base Currency & FX Conversion").
    Both (2) and (3) are reported as NOT live -- a caller must never
    compute a real unrealized P/L from either (see
    services/portfolio_service.py, "PENDING_SYNC never implies profit").
    """
    if price_result is not None and price_result.status == PriceStatus.CURRENT:
        return ResolvedValuation(price=price_result.price, is_live=True)
    if price_result is not None and price_result.is_usable:
        return ResolvedValuation(price=price_result.price, is_live=False)
    if asset_currency == base_currency and average_cost > 0:
        return ResolvedValuation(price=average_cost, is_live=False)
    return ResolvedValuation(price=None, is_live=False)


def find_emergency_bucket_id(assets: list[Asset], emergency_asset_id: UUID | None) -> UUID | None:
    """Which strategy bucket (if any) holds the configured emergency asset
    — determined purely from configuration relationships (portfolio_configs
    -> assets -> strategy_buckets), never from a bucket/asset name."""
    if emergency_asset_id is None:
        return None
    for asset in assets:
        if asset.id == emergency_asset_id:
            return asset.strategy_bucket_id
    return None


def build_positions(
    assets: list[Asset], emergency_asset_id: UUID | None, prices: dict[UUID, PriceResult], base_currency: str
) -> list[AssetPosition]:
    """Pure: assembles positions from already-resolved price results
    (each already converted into the portfolio's base currency by the
    caller — see `load_priced_positions` below), applying the Phase 16
    missing-price fallback (`resolve_valuation_price`) per asset so a
    position is excluded (`current_price=None`) only in the true
    worst case, never merely because no live price exists (see
    domain/portfolio_engine.py, "Never Fabricate A Price" — a fallback
    price is a real number, not a fabrication, and is never presented
    as live; see `resolve_valuation_price`)."""
    positions = []
    for asset in assets:
        holding = asset.holding
        quantity = holding.quantity if holding is not None else Decimal("0")
        average_cost = holding.average_cost if holding is not None else Decimal("0")
        price_result = prices.get(asset.id)
        resolved = resolve_valuation_price(
            price_result, average_cost=average_cost, asset_currency=asset.currency, base_currency=base_currency
        )
        positions.append(
            AssetPosition(
                asset_id=asset.id,
                symbol=asset.symbol,
                asset_type=asset.asset_type.value,
                is_emergency=emergency_asset_id is not None and asset.id == emergency_asset_id,
                strategy_bucket_id=asset.strategy_bucket_id,
                quantity=quantity,
                current_price=resolved.price,
            )
        )
    return positions


async def load_priced_positions(
    session: AsyncSession, assets: list[Asset], emergency_asset_id: UUID | None, base_currency: str
) -> list[AssetPosition]:
    """Fetches every asset's latest price (via the Price Service --
    never a live provider call, see FINANCIAL_RULES.md, "Non-Blocking
    Valuation") in one batch, converts into `base_currency`, and builds
    positions. This is the one call site every consumer of portfolio
    valuation (Dashboard, Allocation, Smart Inflow) should use, so they
    can never drift onto different pricing logic."""
    prices = await price_service.get_prices_for_assets_in_base_currency(session, assets, base_currency)
    return build_positions(assets, emergency_asset_id, prices, base_currency)
