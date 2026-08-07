"""skor bilesenleri, kirilim teyidi, sonuc takibi ve fiyat alarmlari

Revision ID: 8f3c21ad55e1
Revises: 4cb6b68fc115
Create Date: 2026-08-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8f3c21ad55e1"
down_revision = "4cb6b68fc115"
branch_labels = None
depends_on = None

_SIGNAL_COLUMNS = (
    ("interval", sa.String(length=8)),
    ("indicator_score", sa.Float()),
    ("sentiment", sa.Float()),
    ("mtf_score", sa.Float()),
    ("breakout_level", sa.Float()),
    ("confirmed_at", sa.DateTime(timezone=True)),
    ("confirmed_price", sa.Float()),
    ("confirm_volume_ratio", sa.Float()),
)


def upgrade() -> None:
    with op.batch_alter_table("signals", schema=None) as batch_op:
        for name, type_ in _SIGNAL_COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=True))

    op.create_table(
        "signal_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=False),
        sa.Column("is_hit", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_outcome_signal"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_price", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.create_index("ix_alerts_active", ["is_active", "ticker"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index("ix_alerts_active")
    op.drop_table("alerts")
    op.drop_table("signal_outcomes")

    with op.batch_alter_table("signals", schema=None) as batch_op:
        for name, _ in reversed(_SIGNAL_COLUMNS):
            batch_op.drop_column(name)
