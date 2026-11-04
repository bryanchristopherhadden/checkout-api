from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.engine import Engine, Row
from sqlalchemy.orm import Session

from database import (
    cart_items,
    carts,
    create_database_engine,
    create_session_factory,
    gift_cards,
    metadata,
    order_items,
    orders,
    products,
)


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    unit_price_cents: int


@dataclass(frozen=True)
class CartLine:
    product_id: str
    name: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int


@dataclass(frozen=True)
class Cart:
    cart_id: str
    items: list[CartLine]
    discount_code: str | None
    gift_card_id: str | None
    gift_card_balance_cents: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    gift_card_applied_cents: int
    amount_due_cents: int


@dataclass(frozen=True)
class GiftCard:
    gift_card_id: str
    balance_cents: int
    currency: str


@dataclass(frozen=True)
class Checkout:
    order_id: str
    cart_id: str
    currency: str
    items: list[CartLine]
    subtotal_cents: int
    discount_code: str | None
    discount_cents: int
    total_cents: int
    gift_card_id: str | None
    gift_card_applied_cents: int
    amount_due_cents: int


class CommerceError(Exception):
    pass


class NotFoundError(CommerceError):
    pass


class InvalidDiscountError(CommerceError):
    pass


class InvalidGiftCardError(CommerceError):
    pass


class GiftCardBalanceError(CommerceError):
    pass


class EmptyCartError(CommerceError):
    pass


class OutOfStockError(CommerceError):
    pass


class CommerceService:
    _catalog = (
        Product("coffee", "Coffee", 500),
        Product("mug", "Mug", 1200),
        Product("beans", "Coffee beans", 1800),
    )
    _initial_stock = {"coffee": 10, "mug": 5, "beans": 8}
    _discounts = {"SAVE10": 10, "SAVE20": 20}

    def __init__(
        self, database_url: str | None = None, engine: Engine | None = None
    ) -> None:
        self.engine = (
            engine if engine is not None else create_database_engine(database_url)
        )
        self._sessions = create_session_factory(self.engine)

    def initialize_for_tests(self) -> None:
        metadata.create_all(self.engine)
        with self._sessions.begin() as session:
            for product in self._catalog:
                exists = session.scalar(
                    select(products.c.product_id).where(
                        products.c.product_id == product.product_id
                    )
                )
                if exists is None:
                    session.execute(
                        insert(products).values(
                            product_id=product.product_id,
                            name=product.name,
                            unit_price_cents=product.unit_price_cents,
                            available_quantity=self._initial_stock[product.product_id],
                        )
                    )

    def verify_database(self) -> None:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

    def list_products(self) -> list[Product]:
        catalog_order = {
            product.product_id: index for index, product in enumerate(self._catalog)
        }
        with self._sessions() as session:
            rows = session.execute(
                select(products).order_by(
                    case(catalog_order, value=products.c.product_id)
                )
            )
            return [
                Product(
                    product_id=row.product_id,
                    name=row.name,
                    unit_price_cents=row.unit_price_cents,
                )
                for row in rows
            ]

    def create_cart(self) -> Cart:
        cart_id = str(uuid4())
        with self._sessions.begin() as session:
            session.execute(insert(carts).values(cart_id=cart_id))
        return self.get_cart(cart_id)

    def create_gift_card(self, balance_cents: int) -> GiftCard:
        gift_card_id = str(uuid4())
        with self._sessions.begin() as session:
            session.execute(
                insert(gift_cards).values(
                    gift_card_id=gift_card_id,
                    balance_cents=balance_cents,
                    currency="USD",
                )
            )
        return GiftCard(gift_card_id, balance_cents, "USD")

    def get_gift_card(self, gift_card_id: str) -> GiftCard:
        with self._sessions() as session:
            row = self._get_gift_card(session, gift_card_id)
            return GiftCard(row.gift_card_id, row.balance_cents, row.currency)

    def apply_gift_card(self, cart_id: str, gift_card_id: str) -> Cart:
        with self._sessions.begin() as session:
            self._get_cart(session, cart_id, lock=True)
            gift_card = self._get_gift_card(session, gift_card_id, lock=True)
            if gift_card.currency != "USD":
                raise InvalidGiftCardError("Gift card currency must be USD")
            if gift_card.balance_cents <= 0:
                raise GiftCardBalanceError("Gift card has no remaining balance")
            session.execute(
                update(carts)
                .where(carts.c.cart_id == cart_id)
                .values(gift_card_id=gift_card_id)
            )
        return self.get_cart(cart_id)

    def remove_gift_card(self, cart_id: str) -> Cart:
        with self._sessions.begin() as session:
            self._get_cart(session, cart_id, lock=True)
            session.execute(
                update(carts)
                .where(carts.c.cart_id == cart_id)
                .values(gift_card_id=None)
            )
        return self.get_cart(cart_id)

    def get_cart(self, cart_id: str) -> Cart:
        with self._sessions() as session:
            row = session.execute(
                select(carts).where(carts.c.cart_id == cart_id)
            ).first()
            if row is None:
                raise NotFoundError(f"Unknown cart: {cart_id}")
            return self._cart_view(session, row)

    def add_item(self, cart_id: str, product_id: str, quantity: int) -> Cart:
        with self._sessions.begin() as session:
            cart = self._get_cart(session, cart_id, lock=True)
            product = self._get_product(session, product_id, lock=True)
            item = session.execute(
                select(cart_items).where(
                    cart_items.c.cart_id == cart_id,
                    cart_items.c.product_id == product_id,
                )
            ).first()
            new_quantity = (item.quantity if item is not None else 0) + quantity
            if new_quantity > product.available_quantity:
                raise OutOfStockError(f"Insufficient stock for {product_id}")
            if item is None:
                session.execute(
                    insert(cart_items).values(
                        cart_id=cart_id,
                        product_id=product_id,
                        quantity=quantity,
                    )
                )
            else:
                session.execute(
                    update(cart_items)
                    .where(
                        cart_items.c.cart_id == cart_id,
                        cart_items.c.product_id == product_id,
                    )
                    .values(quantity=new_quantity)
                )
        return self.get_cart(cart.cart_id)

    def remove_item(self, cart_id: str, product_id: str) -> Cart:
        with self._sessions.begin() as session:
            self._get_cart(session, cart_id, lock=True)
            result = session.execute(
                delete(cart_items).where(
                    cart_items.c.cart_id == cart_id,
                    cart_items.c.product_id == product_id,
                )
            )
            if result.rowcount == 0:
                self._get_product(session, product_id)
                raise NotFoundError(f"Product {product_id} is not in this cart")
        return self.get_cart(cart_id)

    def clear_cart(self, cart_id: str) -> Cart:
        with self._sessions.begin() as session:
            self._get_cart(session, cart_id, lock=True)
            session.execute(delete(cart_items).where(cart_items.c.cart_id == cart_id))
            session.execute(
                update(carts)
                .where(carts.c.cart_id == cart_id)
                .values(discount_code=None, gift_card_id=None)
            )
        return self.get_cart(cart_id)

    def apply_discount(self, cart_id: str, code: str) -> Cart:
        normalized_code = code.strip().upper()
        if normalized_code not in self._discounts:
            raise InvalidDiscountError(f"Invalid discount code: {code}")
        with self._sessions.begin() as session:
            self._get_cart(session, cart_id, lock=True)
            session.execute(
                update(carts)
                .where(carts.c.cart_id == cart_id)
                .values(discount_code=normalized_code)
            )
        return self.get_cart(cart_id)

    def check_stock(self, product_id: str) -> int:
        with self._sessions() as session:
            product = self._get_product(session, product_id)
            return product.available_quantity

    def checkout_cart(self, cart_id: str) -> Checkout:
        order_id = str(uuid4())
        with self._sessions.begin() as session:
            cart = self._get_cart(session, cart_id, lock=True)
            lines = self._cart_lines(session, cart_id, lock=True)
            if not lines:
                raise EmptyCartError("Cannot checkout an empty cart")

            for line in lines:
                result = session.execute(
                    update(products)
                    .where(
                        products.c.product_id == line.product_id,
                        products.c.available_quantity >= line.quantity,
                    )
                    .values(
                        available_quantity=products.c.available_quantity
                        - line.quantity
                    )
                )
                if result.rowcount != 1:
                    raise OutOfStockError(
                        f"Insufficient stock for {line.product_id}"
                    )

            subtotal = sum(line.line_total_cents for line in lines)
            discount_code = cart.discount_code
            discount = (
                subtotal * self._discounts[discount_code] // 100
                if discount_code is not None
                else 0
            )
            total = subtotal - discount
            gift_card_id = cart.gift_card_id
            gift_card_applied = 0
            if gift_card_id is not None:
                gift_card = self._get_gift_card(session, gift_card_id, lock=True)
                gift_card_applied = min(gift_card.balance_cents, total)
                if gift_card_applied:
                    result = session.execute(
                        update(gift_cards)
                        .where(
                            gift_cards.c.gift_card_id == gift_card_id,
                            gift_cards.c.balance_cents >= gift_card_applied,
                            gift_cards.c.currency == "USD",
                        )
                        .values(
                            balance_cents=gift_cards.c.balance_cents
                            - gift_card_applied
                        )
                    )
                    if result.rowcount != 1:
                        raise GiftCardBalanceError(
                            "Gift card balance changed; retry checkout"
                        )
            amount_due = total - gift_card_applied
            session.execute(
                insert(orders).values(
                    order_id=order_id,
                    cart_id=cart_id,
                    currency="USD",
                    subtotal_cents=subtotal,
                    discount_code=discount_code,
                    discount_cents=discount,
                    total_cents=total,
                    gift_card_id=gift_card_id,
                    gift_card_applied_cents=gift_card_applied,
                    amount_due_cents=amount_due,
                )
            )
            session.execute(
                insert(order_items),
                [
                    {
                        "order_id": order_id,
                        "product_id": line.product_id,
                        "name": line.name,
                        "unit_price_cents": line.unit_price_cents,
                        "quantity": line.quantity,
                        "line_total_cents": line.line_total_cents,
                    }
                    for line in lines
                ],
            )
            session.execute(delete(cart_items).where(cart_items.c.cart_id == cart_id))
            session.execute(
                update(carts)
                .where(carts.c.cart_id == cart_id)
                .values(discount_code=None, gift_card_id=None)
            )

        return Checkout(
            order_id=order_id,
            cart_id=cart_id,
            currency="USD",
            items=lines,
            subtotal_cents=subtotal,
            discount_code=discount_code,
            discount_cents=discount,
            total_cents=total,
            gift_card_id=gift_card_id,
            gift_card_applied_cents=gift_card_applied,
            amount_due_cents=amount_due,
        )

    def checkout_items(self, items: list[tuple[str, int]]) -> Checkout:
        cart = self.create_cart()
        try:
            for product_id, quantity in items:
                self.add_item(cart.cart_id, product_id, quantity)
            return self.checkout_cart(cart.cart_id)
        finally:
            with self._sessions.begin() as session:
                session.execute(
                    delete(carts).where(carts.c.cart_id == cart.cart_id)
                )

    def reset(self) -> None:
        with self._sessions.begin() as session:
            session.execute(delete(orders))
            session.execute(delete(carts))
            session.execute(delete(gift_cards))
            for product_id, quantity in self._initial_stock.items():
                session.execute(
                    update(products)
                    .where(products.c.product_id == product_id)
                    .values(available_quantity=quantity)
                )

    def _cart_view(self, session: Session, cart: Row[Any]) -> Cart:
        lines = self._cart_lines(session, cart.cart_id)
        subtotal = sum(line.line_total_cents for line in lines)
        discount = (
            subtotal * self._discounts[cart.discount_code] // 100
            if cart.discount_code
            else 0
        )
        gift_card_balance = self._gift_card_balance(session, cart.gift_card_id)
        total = subtotal - discount
        gift_card_applied = min(gift_card_balance, total)
        return Cart(
            cart_id=cart.cart_id,
            items=lines,
            discount_code=cart.discount_code,
            gift_card_id=cart.gift_card_id,
            gift_card_balance_cents=gift_card_balance,
            subtotal_cents=subtotal,
            discount_cents=discount,
            total_cents=total,
            gift_card_applied_cents=gift_card_applied,
            amount_due_cents=total - gift_card_applied,
        )

    @staticmethod
    def _cart_lines(
        session: Session, cart_id: str, lock: bool = False
    ) -> list[CartLine]:
        query = (
            select(
                products.c.product_id,
                products.c.name,
                products.c.unit_price_cents,
                cart_items.c.quantity,
            )
            .join(cart_items, cart_items.c.product_id == products.c.product_id)
            .where(cart_items.c.cart_id == cart_id)
            .order_by(products.c.product_id)
        )
        if lock:
            query = query.with_for_update()
        return [
            CartLine(
                product_id=row.product_id,
                name=row.name,
                unit_price_cents=row.unit_price_cents,
                quantity=row.quantity,
                line_total_cents=row.unit_price_cents * row.quantity,
            )
            for row in session.execute(query)
        ]

    @staticmethod
    def _get_cart(
        session: Session, cart_id: str, lock: bool = False
    ) -> Row[Any]:
        query = select(carts).where(carts.c.cart_id == cart_id)
        if lock:
            query = query.with_for_update()
        cart = session.execute(query).first()
        if cart is None:
            raise NotFoundError(f"Unknown cart: {cart_id}")
        return cart

    @staticmethod
    def _get_product(
        session: Session, product_id: str, lock: bool = False
    ) -> Row[Any]:
        query = select(products).where(products.c.product_id == product_id)
        if lock:
            query = query.with_for_update()
        product = session.execute(query).first()
        if product is None:
            raise NotFoundError(f"Unknown product: {product_id}")
        return product

    @staticmethod
    def _get_gift_card(
        session: Session, gift_card_id: str, lock: bool = False
    ) -> Row[Any]:
        query = select(gift_cards).where(gift_cards.c.gift_card_id == gift_card_id)
        if lock:
            query = query.with_for_update()
        gift_card = session.execute(query).first()
        if gift_card is None:
            raise NotFoundError(f"Unknown gift card: {gift_card_id}")
        return gift_card

    @staticmethod
    def _gift_card_balance(session: Session, gift_card_id: str | None) -> int:
        if gift_card_id is None:
            return 0
        balance = session.scalar(
            select(gift_cards.c.balance_cents).where(
                gift_cards.c.gift_card_id == gift_card_id
            )
        )
        return balance if balance is not None else 0


commerce = CommerceService()
