import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.portfolio_config import PortfolioConfig
    from app.models.transaction import Transaction


class PortfolioSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A point-in-time record of portfolio composition value.

    Snapshots represent historical VALUE only — never quantities, purchase
    prices, or a substitute for transaction history (see FINANCIAL_RULES.md,
    "Snapshot != Transaction"). Quantities must never be inferred from a
    snapshot's recorded values.

    Phase 15 additions (all nullable/additive -- see DECISIONS.md, "Phase 15
    Snapshot Schema"): trigger_source/source_transaction_id identify why a
    snapshot exists (never inferred after the fact), and total_cost_basis/
    invested_capital/realized_pnl_cumulative capture the financial context
    AS OF that instant, computed once at write time (never re-derived
    retroactively for older rows). The five pre-Phase-15 seed rows keep all
    of these NULL -- that history was genuinely never captured, and is
    never backfilled or guessed.
    """

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("ix_portfolio_snapshots_config_snapshot_at", "portfolio_config_id", "snapshot_at"),
        CheckConstraint(
            "trigger_source IS NULL OR trigger_source IN ('EOD', 'TRANSACTION')",
            name="ck_portfolio_snapshots_trigger_source",
        ),
        # Idempotency (EOD): at most one EOD-triggered snapshot per
        # portfolio per UTC calendar day. Partial -- rows with
        # trigger_source NULL/'TRANSACTION' are untouched, so the five
        # pre-Phase-15 seed rows (all NULL) can never violate this.
        Index(
            "uq_portfolio_snapshot_eod_per_day",
            "portfolio_config_id",
            text("((snapshot_at AT TIME ZONE 'UTC')::date)"),
            unique=True,
            postgresql_where=text("trigger_source = 'EOD'"),
        ),
        # Idempotency (post-transaction): at most one snapshot per
        # triggering DEPOSIT/WITHDRAWAL transaction.
        Index(
            "uq_portfolio_snapshot_source_transaction",
            "source_transaction_id",
            unique=True,
            postgresql_where=text("source_transaction_id IS NOT NULL"),
        ),
    )

    portfolio_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_configs.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Phase 15: why this snapshot exists. NULL for the pre-Phase-15 seed
    # rows (unknown -- never assumed to be 'EOD' after the fact).
    trigger_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Phase 15: set only for trigger_source='TRANSACTION' -- the DEPOSIT/
    # WITHDRAWAL that produced this snapshot, doubling as the idempotency
    # key (see the partial unique index in the migration). ON DELETE SET
    # NULL rather than CASCADE: a snapshot is a historical observation and
    # must never disappear merely because its triggering transaction row
    # were ever removed.
    source_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    # Phase 15: sum(quantity * average_cost) across all held positions at
    # snapshot time -- independent of price availability (see
    # domain/pnl_engine.py). Never re-derived for historical rows.
    total_cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Phase 15: cumulative net external capital (DEPOSIT minus WITHDRAWAL)
    # as of snapshot time -- the TWR baseline input, computed by summing
    # recorded cash-flow transactions, never guessed.
    invested_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Phase 15: cumulative realized P/L across all-time SELL activity as of
    # snapshot time, derived by replaying transaction history through the
    # existing, unmodified apply_buy/apply_sell math (domain/
    # transaction_engine.py) -- never a separately maintained ledger.
    realized_pnl_cumulative: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    portfolio_config: Mapped["PortfolioConfig"] = relationship(back_populates="snapshots")
    source_transaction: Mapped["Transaction | None"] = relationship()
    items: Mapped[list["PortfolioSnapshotItem"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class PortfolioSnapshotItem(UUIDPrimaryKeyMixin, Base):
    """One asset's recorded value within a snapshot.

    Assets are referenced dynamically by foreign key rather than as fixed
    columns (never `snapshot.cloudz`, `snapshot.bwa`, ...) so new assets
    never require a schema change (see DATABASE.md).

    Numeric precision: value uses NUMERIC(18, 2) — a plain currency amount
    in the portfolio's base currency, 2 decimal places.
    """

    __tablename__ = "portfolio_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "asset_id", name="uq_snapshot_item_snapshot_asset"),
        CheckConstraint("value >= 0", name="ck_snapshot_item_value_non_negative"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    snapshot: Mapped["PortfolioSnapshot"] = relationship(back_populates="items")
    asset: Mapped["Asset"] = relationship(back_populates="snapshot_items")
