"""phase_15_snapshot_lifecycle

Revision ID: 3210d10067b1
Revises: 7dbad9d06fb1
Create Date: 2026-09-10 19:56:32.729049

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3210d10067b1'
down_revision: Union[str, None] = '7dbad9d06fb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 15: additive-only -- new nullable columns plus two idempotency
    # indexes on portfolio_snapshots. Nothing existing is dropped, renamed,
    # or backfilled; the five pre-Phase-15 seed rows keep every new column
    # NULL (see models/snapshot.py's docstring and DECISIONS.md, "Phase 15
    # Snapshot Schema").
    op.add_column('portfolio_snapshots', sa.Column('trigger_source', sa.String(length=20), nullable=True))
    op.add_column('portfolio_snapshots', sa.Column('source_transaction_id', sa.UUID(), nullable=True))
    op.add_column('portfolio_snapshots', sa.Column('total_cost_basis', sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column('portfolio_snapshots', sa.Column('invested_capital', sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column('portfolio_snapshots', sa.Column('realized_pnl_cumulative', sa.Numeric(precision=18, scale=2), nullable=True))
    op.create_check_constraint(
        'ck_portfolio_snapshots_trigger_source',
        'portfolio_snapshots',
        "trigger_source IS NULL OR trigger_source IN ('EOD', 'TRANSACTION')",
    )
    op.create_foreign_key(
        'fk_portfolio_snapshots_source_transaction_id',
        'portfolio_snapshots',
        'transactions',
        ['source_transaction_id'],
        ['id'],
        ondelete='SET NULL',
    )
    # Idempotency (EOD): at most one EOD-triggered snapshot per portfolio
    # per UTC calendar day. A partial index -- rows with trigger_source
    # NULL or 'TRANSACTION' are untouched by it, so the five pre-existing
    # seed rows (all NULL) cannot violate it.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_portfolio_snapshot_eod_per_day
        ON portfolio_snapshots (portfolio_config_id, ((snapshot_at AT TIME ZONE 'UTC')::date))
        WHERE trigger_source = 'EOD'
        """
    )
    # Idempotency (post-transaction): at most one snapshot per triggering
    # DEPOSIT/WITHDRAWAL transaction. Partial on IS NOT NULL, so existing
    # rows (source_transaction_id always NULL today) are unaffected.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_portfolio_snapshot_source_transaction
        ON portfolio_snapshots (source_transaction_id)
        WHERE source_transaction_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_portfolio_snapshot_source_transaction")
    op.execute("DROP INDEX IF EXISTS uq_portfolio_snapshot_eod_per_day")
    op.drop_constraint('fk_portfolio_snapshots_source_transaction_id', 'portfolio_snapshots', type_='foreignkey')
    op.drop_constraint('ck_portfolio_snapshots_trigger_source', 'portfolio_snapshots', type_='check')
    op.drop_column('portfolio_snapshots', 'realized_pnl_cumulative')
    op.drop_column('portfolio_snapshots', 'invested_capital')
    op.drop_column('portfolio_snapshots', 'total_cost_basis')
    op.drop_column('portfolio_snapshots', 'source_transaction_id')
    op.drop_column('portfolio_snapshots', 'trigger_source')
