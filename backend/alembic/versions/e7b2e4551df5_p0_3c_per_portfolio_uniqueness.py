"""p0_3c_per_portfolio_uniqueness

Revision ID: e7b2e4551df5
Revises: b3e04b7fe898
Create Date: 2026-10-04

Schema-only, additive-safe change for P0-3C (Ownership Enforcement).

P0-3A/B added nullable ownership columns but deliberately left three
uniqueness rules global, because widening them before ownership was
enforced would have let Postgres's NULL-is-distinct semantics admit
duplicates. P0-3C now scopes every read/write to the caller's portfolio, so
those rules must become per-portfolio -- otherwise two users could never
hold or watch the same (global) asset, or have the same notification
condition active at once:

  holdings       UNIQUE(asset_id)          -> UNIQUE(portfolio_config_id, asset_id)
  watchlist      UNIQUE(asset_id)          -> UNIQUE(portfolio_config_id, asset_id)
  notifications  UNIQUE(source_id) active  -> UNIQUE(portfolio_config_id, source_id) active

Each composite constraint is paired with a PARTIAL unique index over the
unowned (portfolio_config_id IS NULL) rows, restoring the original
guarantee for legacy rows that predate ownership.

Safe against existing production rows, with no data read or written: every
existing row is unowned and was already unique on the old key, so every new
constraint/index is satisfied by construction. No backfill, no data
migration. Also adds plain indexes on the ownership columns the scoped
queries now filter on.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7b2e4551df5'
down_revision: Union[str, None] = 'b3e04b7fe898'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # holdings
    op.create_index(
        'uq_holdings_asset_id_unowned', 'holdings', ['asset_id'], unique=True,
        postgresql_where=sa.text('portfolio_config_id IS NULL'),
    )
    op.drop_constraint('uq_holdings_asset_id', 'holdings', type_='unique')
    op.create_unique_constraint('uq_holdings_portfolio_asset', 'holdings', ['portfolio_config_id', 'asset_id'])

    # watchlist
    op.create_index(
        'uq_watchlist_asset_id_unowned', 'watchlist', ['asset_id'], unique=True,
        postgresql_where=sa.text('portfolio_config_id IS NULL'),
    )
    op.drop_constraint('uq_watchlist_asset_id', 'watchlist', type_='unique')
    op.create_unique_constraint('uq_watchlist_portfolio_asset', 'watchlist', ['portfolio_config_id', 'asset_id'])

    # notifications
    op.create_index(
        'uq_notifications_source_id_active_unowned', 'notifications', ['source_id'], unique=True,
        postgresql_where=sa.text('resolved_at IS NULL AND portfolio_config_id IS NULL'),
    )
    op.create_index(
        'uq_notifications_portfolio_source_id_active', 'notifications', ['portfolio_config_id', 'source_id'],
        unique=True, postgresql_where=sa.text('resolved_at IS NULL'),
    )
    op.drop_index(
        'uq_notifications_source_id_active', table_name='notifications',
        postgresql_where=sa.text('resolved_at IS NULL'),
    )

    # ownership-column lookup indexes
    op.create_index(op.f('ix_alert_rules_portfolio_config_id'), 'alert_rules', ['portfolio_config_id'], unique=False)
    op.create_index(op.f('ix_notifications_portfolio_config_id'), 'notifications', ['portfolio_config_id'], unique=False)
    op.create_index(op.f('ix_transactions_portfolio_config_id'), 'transactions', ['portfolio_config_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transactions_portfolio_config_id'), table_name='transactions')
    op.drop_index(op.f('ix_notifications_portfolio_config_id'), table_name='notifications')
    op.drop_index(op.f('ix_alert_rules_portfolio_config_id'), table_name='alert_rules')

    op.create_index(
        'uq_notifications_source_id_active', 'notifications', ['source_id'], unique=True,
        postgresql_where=sa.text('resolved_at IS NULL'),
    )
    op.drop_index(
        'uq_notifications_portfolio_source_id_active', table_name='notifications',
        postgresql_where=sa.text('resolved_at IS NULL'),
    )
    op.drop_index(
        'uq_notifications_source_id_active_unowned', table_name='notifications',
        postgresql_where=sa.text('resolved_at IS NULL AND portfolio_config_id IS NULL'),
    )

    op.drop_constraint('uq_watchlist_portfolio_asset', 'watchlist', type_='unique')
    op.create_unique_constraint('uq_watchlist_asset_id', 'watchlist', ['asset_id'])
    op.drop_index(
        'uq_watchlist_asset_id_unowned', table_name='watchlist',
        postgresql_where=sa.text('portfolio_config_id IS NULL'),
    )

    op.drop_constraint('uq_holdings_portfolio_asset', 'holdings', type_='unique')
    op.create_unique_constraint('uq_holdings_asset_id', 'holdings', ['asset_id'])
    op.drop_index(
        'uq_holdings_asset_id_unowned', table_name='holdings',
        postgresql_where=sa.text('portfolio_config_id IS NULL'),
    )
