"""Create product, cart, and order tables.

Revision ID: 0001_checkout_tables
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_checkout_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "unit_price_cents >= 0", name="ck_products_price_nonnegative"
        ),
        sa.CheckConstraint(
            "available_quantity >= 0", name="ck_products_stock_nonnegative"
        ),
    )
    op.create_table(
        "carts",
        sa.Column("cart_id", sa.String(length=36), primary_key=True),
        sa.Column("discount_code", sa.String(length=50)),
    )
    op.create_table(
        "cart_items",
        sa.Column(
            "cart_id",
            sa.String(length=36),
            sa.ForeignKey("carts.cart_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            sa.String(length=100),
            sa.ForeignKey("products.product_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
    )
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=36), primary_key=True),
        sa.Column("cart_id", sa.String(length=36), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column("discount_code", sa.String(length=50)),
        sa.Column("discount_cents", sa.Integer(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
    )
    op.create_table(
        "order_items",
        sa.Column(
            "order_id",
            sa.String(length=36),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            sa.String(length=100),
            sa.ForeignKey("products.product_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
    )
    products = sa.table(
        "products",
        sa.column("product_id", sa.String),
        sa.column("name", sa.String),
        sa.column("unit_price_cents", sa.Integer),
        sa.column("available_quantity", sa.Integer),
    )
    op.bulk_insert(
        products,
        [
            {
                "product_id": "coffee",
                "name": "Coffee",
                "unit_price_cents": 500,
                "available_quantity": 10,
            },
            {
                "product_id": "mug",
                "name": "Mug",
                "unit_price_cents": 1200,
                "available_quantity": 5,
            },
            {
                "product_id": "beans",
                "name": "Coffee beans",
                "unit_price_cents": 1800,
                "available_quantity": 8,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("products")
