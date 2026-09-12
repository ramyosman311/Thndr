"""phase_20_telegram_delivery

Revision ID: e7b9c2a1d430
Revises: c49911658945
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b9c2a1d430"
down_revision: Union[str, None] = "c49911658945"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("telegram_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "telegram_sent_at")
