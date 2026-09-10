"""Phase 15 wealth analytics: derives Portfolio Value / Invested Capital /
Total P&L / TWR history purely from already-persisted snapshots.

Read-only -- never writes to snapshots, transactions, or holdings. Never
computes a historical point from today's live holdings (see
FINANCIAL_RULES.md, "Non-Blocking Valuation"; DECISIONS.md, "Phase 15
Analytics API"): every point returned corresponds to one real, persisted
`PortfolioSnapshot` row. A range with fewer than two eligible snapshots is
reported as `insufficient_history=True` with an empty `data` list -- never
interpolated, extrapolated, or backfilled to make a chart look complete.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.twr_engine import TWRPoint, cumulative_returns
from app.models import PortfolioSnapshot
from app.repositories.portfolio_repository import get_portfolio_config
from app.repositories.snapshot_repository import list_snapshots_ordered
from app.schemas.analytics import AnalyticsPointOut, PortfolioAnalyticsHistoryOut

_VALID_RANGES = {"1W", "1M", "3M", "YTD", "ALL"}
_PRESENTATION_QUANT = Decimal("0.01")


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet."""


class InvalidRangeError(Exception):
    """Raised for a `range` query value outside 1W/1M/3M/YTD/ALL."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PRESENTATION_QUANT, rounding=ROUND_HALF_UP)


def _range_start(range_key: str, *, now: datetime) -> datetime | None:
    if range_key == "1W":
        return now - timedelta(days=7)
    if range_key == "1M":
        return now - timedelta(days=30)
    if range_key == "3M":
        return now - timedelta(days=90)
    if range_key == "YTD":
        return datetime(now.year, 1, 1, tzinfo=timezone.utc)
    return None  # ALL


@dataclass(frozen=True)
class _Eligible:
    snapshot: PortfolioSnapshot
    total_value: Decimal


def _eligible_snapshots(snapshots: list[PortfolioSnapshot]) -> list[_Eligible]:
    """Only snapshots created under the Phase 15 lifecycle carry the
    `invested_capital` field TWR/analytics need -- pre-Phase-15 rows
    (invested_capital IS NULL, e.g. the original dev seed snapshots) are
    excluded entirely rather than guessed at (see models/snapshot.py's
    docstring)."""
    result = []
    for snapshot in snapshots:
        if snapshot.invested_capital is None:
            continue
        total_value = sum((item.value for item in snapshot.items), Decimal("0"))
        result.append(_Eligible(snapshot=snapshot, total_value=total_value))
    return result


def _build_twr_points(eligible: list[_Eligible]) -> list[TWRPoint]:
    """The flow landing at each point is derived from the DELTA between
    consecutive `invested_capital` values -- not by re-joining the
    triggering transaction -- since `invested_capital` is already the
    cumulative net external capital as of that snapshot (see
    services/snapshot_service.py). This is exact: every DEPOSIT/WITHDRAWAL
    creates its own snapshot (Phase 15 design), so at most one flow can
    separate two consecutive eligible snapshots."""
    points = []
    previous_invested_capital: Decimal | None = None
    for entry in eligible:
        invested_capital = entry.snapshot.invested_capital
        flow = Decimal("0") if previous_invested_capital is None else invested_capital - previous_invested_capital
        points.append(TWRPoint(at=entry.snapshot.snapshot_at, total_value=entry.total_value, external_flow=flow))
        previous_invested_capital = invested_capital
    return points


async def get_portfolio_analytics_history(
    session: AsyncSession, *, range_key: str, now: datetime | None = None
) -> PortfolioAnalyticsHistoryOut:
    if range_key not in _VALID_RANGES:
        raise InvalidRangeError(f"Unsupported range: {range_key}. Must be one of {sorted(_VALID_RANGES)}.")

    config = await get_portfolio_config(session)
    if config is None:
        raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")

    now = now or datetime.now(timezone.utc)
    snapshots = await list_snapshots_ordered(session, config.id)
    eligible = _eligible_snapshots(snapshots)
    twr_points = _build_twr_points(eligible)
    # Cumulative return computed over the WHOLE eligible history (since
    # inception), never just the requested window -- a window is applied
    # only afterward, by rebasing (dividing through) the already-correct
    # since-inception chain. This keeps the underlying math identical
    # regardless of which range the user happens to be viewing.
    cumulative = cumulative_returns(twr_points)

    range_start = _range_start(range_key, now=now)
    if range_start is None:
        start_index = 0
    else:
        start_index = next(
            (i for i, entry in enumerate(eligible) if entry.snapshot.snapshot_at >= range_start), len(eligible)
        )

    in_range = eligible[start_index:]
    in_range_cumulative = cumulative[start_index:]

    if len(in_range) < 2:
        return PortfolioAnalyticsHistoryOut(
            range=range_key,
            base_currency=config.base_currency,
            data=[],
            insufficient_history=True,
            message="Insufficient historical data for this range.",
        )

    anchor = in_range_cumulative[0]
    data = []
    for entry, cum in zip(in_range, in_range_cumulative):
        rebased: Decimal | None
        if anchor is None or cum is None or (Decimal("1") + anchor) == 0:
            rebased = None
        else:
            rebased = (Decimal("1") + cum) / (Decimal("1") + anchor) - Decimal("1")
        invested_capital = entry.snapshot.invested_capital
        total_pnl = entry.total_value - invested_capital
        data.append(
            AnalyticsPointOut(
                date=entry.snapshot.snapshot_at.date().isoformat(),
                portfolio_value=_round(entry.total_value),
                invested_capital=_round(invested_capital),
                total_pnl=_round(total_pnl),
                twr_percentage=_round(rebased * Decimal("100")) if rebased is not None else None,
            )
        )

    return PortfolioAnalyticsHistoryOut(
        range=range_key, base_currency=config.base_currency, data=data, insufficient_history=False, message=None
    )
