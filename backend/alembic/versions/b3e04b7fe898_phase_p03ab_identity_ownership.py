"""phase_p03ab_identity_ownership

Revision ID: b3e04b7fe898
Revises: e7b9c2a1d430
Create Date: 2026-09-20 17:15:16.579418

Additive-only, production-safe schema change for P0-3A (Identity/Ownership).

Adds a local `users` table keyed 1:1 by the Supabase Auth `auth.users.id`
UUID (see app/models/user.py), and a nullable `portfolio_config_id` (or,
for portfolio_configs itself, `user_id`) ownership column on every
existing user-owned table identified so far: portfolio_configs, holdings,
transactions, watchlist, alert_rules, notifications.

Every new column is NULLABLE and no existing row is modified: this
migration performs no backfill and no production data writes. See
DECISIONS.md, "P0-3A/B — Identity, Ownership, JWT Verification" for the
full rationale, including why holdings.uq_holdings_asset_id and
watchlist.uq_watchlist_asset_id are deliberately left unwidened here, and
what a later, verified-backfill phase must do before any of these
columns can become NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e04b7fe898'
down_revision: Union[str, None] = 'e7b9c2a1d430'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('portfolio_configs', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_portfolio_configs_user_id_users',
        'portfolio_configs', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('holdings', sa.Column('portfolio_config_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_holdings_portfolio_config_id_portfolio_configs',
        'holdings', 'portfolio_configs',
        ['portfolio_config_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('transactions', sa.Column('portfolio_config_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_transactions_portfolio_config_id_portfolio_configs',
        'transactions', 'portfolio_configs',
        ['portfolio_config_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('watchlist', sa.Column('portfolio_config_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_watchlist_portfolio_config_id_portfolio_configs',
        'watchlist', 'portfolio_configs',
        ['portfolio_config_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('alert_rules', sa.Column('portfolio_config_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_alert_rules_portfolio_config_id_portfolio_configs',
        'alert_rules', 'portfolio_configs',
        ['portfolio_config_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('notifications', sa.Column('portfolio_config_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_notifications_portfolio_config_id_portfolio_configs',
        'notifications', 'portfolio_configs',
        ['portfolio_config_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_notifications_portfolio_config_id_portfolio_configs', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'portfolio_config_id')

    op.drop_constraint('fk_alert_rules_portfolio_config_id_portfolio_configs', 'alert_rules', type_='foreignkey')
    op.drop_column('alert_rules', 'portfolio_config_id')

    op.drop_constraint('fk_watchlist_portfolio_config_id_portfolio_configs', 'watchlist', type_='foreignkey')
    op.drop_column('watchlist', 'portfolio_config_id')

    op.drop_constraint('fk_transactions_portfolio_config_id_portfolio_configs', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'portfolio_config_id')

    op.drop_constraint('fk_holdings_portfolio_config_id_portfolio_configs', 'holdings', type_='foreignkey')
    op.drop_column('holdings', 'portfolio_config_id')

    op.drop_constraint('fk_portfolio_configs_user_id_users', 'portfolio_configs', type_='foreignkey')
    op.drop_column('portfolio_configs', 'user_id')

    op.drop_table('users')
