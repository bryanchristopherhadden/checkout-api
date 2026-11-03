from dataclasses import dataclass
from threading import RLock
from uuid import uuid4


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
    subtotal_cents: int
    discount_cents: int
    total_cents: int


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


@dataclass
class _CartState:
    items: dict[str, int]
    discount_code: str | None = None


class CommerceError(Exception):
    pass


class NotFoundError(CommerceError):
    pass


class InvalidDiscountError(CommerceError):
    pass


class EmptyCartError(CommerceError):
    pass


class OutOfStockError(CommerceError):
    pass


class CommerceService:
    def __init__(self) -> None:
        self.products = {
            "coffee": Product("coffee", "Coffee", 500),
            "mug": Product("mug", "Mug", 1200),
            "beans": Product("beans", "Coffee beans", 1800),
        }
        self._stock = {"coffee": 10, "mug": 5, "beans": 8}
        self._discounts = {"SAVE10": 10, "SAVE20": 20}
        self._carts: dict[str, _CartState] = {}
        self._lock = RLock()

    def list_products(self) -> list[Product]:
        return list(self.products.values())

    def create_cart(self) -> Cart:
        with self._lock:
            cart_id = str(uuid4())
            self._carts[cart_id] = _CartState(items={})
            return self._cart_view(cart_id)

    def get_cart(self, cart_id: str) -> Cart:
        with self._lock:
            self._get_cart_state(cart_id)
            return self._cart_view(cart_id)

    def add_item(self, cart_id: str, product_id: str, quantity: int) -> Cart:
        with self._lock:
            cart = self._get_cart_state(cart_id)
            self._get_product(product_id)
            new_quantity = cart.items.get(product_id, 0) + quantity
            if new_quantity > self._stock[product_id]:
                raise OutOfStockError(f"Insufficient stock for {product_id}")
            cart.items[product_id] = new_quantity
            return self._cart_view(cart_id)

    def remove_item(self, cart_id: str, product_id: str) -> Cart:
        with self._lock:
            cart = self._get_cart_state(cart_id)
            if product_id not in cart.items:
                raise NotFoundError(f"Product {product_id} is not in this cart")
            del cart.items[product_id]
            return self._cart_view(cart_id)

    def clear_cart(self, cart_id: str) -> Cart:
        with self._lock:
            cart = self._get_cart_state(cart_id)
            cart.items.clear()
            cart.discount_code = None
            return self._cart_view(cart_id)

    def apply_discount(self, cart_id: str, code: str) -> Cart:
        with self._lock:
            cart = self._get_cart_state(cart_id)
            normalized_code = code.strip().upper()
            if normalized_code not in self._discounts:
                raise InvalidDiscountError(f"Invalid discount code: {code}")
            cart.discount_code = normalized_code
            return self._cart_view(cart_id)

    def check_stock(self, product_id: str) -> int:
        with self._lock:
            self._get_product(product_id)
            return self._stock[product_id]

    def checkout_cart(self, cart_id: str) -> Checkout:
        with self._lock:
            cart = self._get_cart_state(cart_id)
            if not cart.items:
                raise EmptyCartError("Cannot checkout an empty cart")

            for product_id, quantity in cart.items.items():
                if quantity > self._stock[product_id]:
                    raise OutOfStockError(f"Insufficient stock for {product_id}")

            view = self._cart_view(cart_id)
            order = Checkout(
                order_id=str(uuid4()),
                cart_id=cart_id,
                currency="USD",
                items=view.items,
                subtotal_cents=view.subtotal_cents,
                discount_code=view.discount_code,
                discount_cents=view.discount_cents,
                total_cents=view.total_cents,
            )
            for product_id, quantity in cart.items.items():
                self._stock[product_id] -= quantity
            cart.items.clear()
            cart.discount_code = None
            return order

    def checkout_items(self, items: list[tuple[str, int]]) -> Checkout:
        cart = self.create_cart()
        try:
            for product_id, quantity in items:
                self.add_item(cart.cart_id, product_id, quantity)
            return self.checkout_cart(cart.cart_id)
        except CommerceError:
            with self._lock:
                self._carts.pop(cart.cart_id, None)
            raise

    def reset(self) -> None:
        with self._lock:
            self._stock = {"coffee": 10, "mug": 5, "beans": 8}
            self._carts.clear()

    def _cart_view(self, cart_id: str) -> Cart:
        cart = self._carts[cart_id]
        lines = [
            CartLine(
                product_id=product.product_id,
                name=product.name,
                unit_price_cents=product.unit_price_cents,
                quantity=quantity,
                line_total_cents=product.unit_price_cents * quantity,
            )
            for product_id, quantity in cart.items.items()
            for product in [self.products[product_id]]
        ]
        subtotal = sum(line.line_total_cents for line in lines)
        discount = (
            subtotal * self._discounts[cart.discount_code] // 100
            if cart.discount_code
            else 0
        )
        return Cart(
            cart_id=cart_id,
            items=lines,
            discount_code=cart.discount_code,
            subtotal_cents=subtotal,
            discount_cents=discount,
            total_cents=subtotal - discount,
        )

    def _get_cart_state(self, cart_id: str) -> _CartState:
        cart = self._carts.get(cart_id)
        if cart is None:
            raise NotFoundError(f"Unknown cart: {cart_id}")
        return cart

    def _get_product(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise NotFoundError(f"Unknown product: {product_id}")
        return product


commerce = CommerceService()
