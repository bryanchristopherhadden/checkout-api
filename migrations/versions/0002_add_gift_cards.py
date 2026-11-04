"""Add gift card balances and cart checkout redemption.

Revision ID: 0002_gift_cards
Revises: 0001_checkout_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_gift_cards"
down_revision = "0001_checkout_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gift_cards",
        sa.Column("gift_card_id", sa.String(length=36), primary_key=True),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.CheckConstraint(
            "balance_cents >= 0", name="ck_gift_cards_balance_nonnegative"
        ),
    )
    op.add_column(
        "carts",
        sa.Column(
            "gift_card_id",
            sa.String(length=36),
            sa.ForeignKey("gift_cards.gift_card_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "gift_card_id",
            sa.String(length=36),
            sa.ForeignKey("gift_cards.gift_card_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "gift_card_applied_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "amount_due_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "amount_due_cents")
    op.drop_column("orders", "gift_card_applied_cents")
    op.drop_column("orders", "gift_card_id")
    op.drop_column("carts", "gift_card_id")
    op.drop_table("gift_cards")
