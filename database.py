import os

from sqlalchemy import (
    Column,
    CheckConstraint,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_DATABASE_URL = "postgresql+psycopg://checkout:checkout@localhost:5432/checkout"

metadata = MetaData()

products = Table(
    "products",
    metadata,
    Column("product_id", String(100), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("unit_price_cents", Integer, nullable=False),
    Column("available_quantity", Integer, nullable=False),
    CheckConstraint("unit_price_cents >= 0", name="ck_products_price_nonnegative"),
    CheckConstraint("available_quantity >= 0", name="ck_products_stock_nonnegative"),
)

carts = Table(
    "carts",
    metadata,
    Column("cart_id", String(36), primary_key=True),
    Column("discount_code", String(50)),
)

cart_items = Table(
    "cart_items",
    metadata,
    Column(
        "cart_id",
        String(36),
        ForeignKey("carts.cart_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "product_id",
        String(100),
        ForeignKey("products.product_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("quantity", Integer, nullable=False),
    CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
)

orders = Table(
    "orders",
    metadata,
    Column("order_id", String(36), primary_key=True),
    Column("cart_id", String(36), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("subtotal_cents", Integer, nullable=False),
    Column("discount_code", String(50)),
    Column("discount_cents", Integer, nullable=False),
    Column("total_cents", Integer, nullable=False),
)

order_items = Table(
    "order_items",
    metadata,
    Column(
        "order_id",
        String(36),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "product_id",
        String(100),
        ForeignKey("products.product_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("name", String(200), nullable=False),
    Column("unit_price_cents", Integer, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("line_total_cents", Integer, nullable=False),
)


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url == "sqlite+pysqlite:///:memory:":
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
