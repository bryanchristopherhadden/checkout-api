import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import NoReturn

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from commerce import (
    Cart,
    Checkout,
    CommerceError,
    EmptyCartError,
    InvalidDiscountError,
    NotFoundError,
    OutOfStockError,
    commerce,
)
from grpc_service import start_grpc_server


class CartItemRequest(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, le=100)


class CartItemResponse(BaseModel):
    product_id: str
    name: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int


class ProductResponse(BaseModel):
    product_id: str
    name: str
    unit_price_cents: int


class DiscountRequest(BaseModel):
    code: str = Field(min_length=1)


class CartResponse(BaseModel):
    cart_id: str
    items: list[CartItemResponse]
    discount_code: str | None
    subtotal_cents: int
    discount_cents: int
    total_cents: int


class CheckoutResponse(BaseModel):
    order_id: str
    cart_id: str
    currency: str
    items: list[CartItemResponse]
    subtotal_cents: int
    discount_code: str | None = None
    discount_cents: int = 0
    total_cents: int


class StockResponse(BaseModel):
    product_id: str
    available_quantity: int


class LegacyCheckoutModel(BaseModel):
    items: list[CartItemRequest] = Field(min_length=1)


def _to_cart_response(cart: Cart) -> CartResponse:
    return CartResponse(**asdict(cart))


def _to_checkout_response(order: Checkout) -> CheckoutResponse:
    return CheckoutResponse(**asdict(order))


def _raise_http_error(error: CommerceError) -> NoReturn:
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, InvalidDiscountError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, EmptyCartError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, OutOfStockError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    server, port = start_grpc_server(
        commerce, int(os.environ.get("CHECKOUT_GRPC_PORT", "50051"))
    )
    app.state.grpc_server = server
    app.state.grpc_port = port
    try:
        yield
    finally:
        server.stop(grace=1).wait()


app = FastAPI(title="Checkout API", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products", response_model=list[ProductResponse])
def list_products() -> list[ProductResponse]:
    return [ProductResponse(**asdict(product)) for product in commerce.list_products()]


@app.get("/products/{product_id}/stock", response_model=StockResponse)
def check_stock(product_id: str) -> StockResponse:
    try:
        return StockResponse(
            product_id=product_id,
            available_quantity=commerce.check_stock(product_id),
        )
    except CommerceError as error:
        _raise_http_error(error)


@app.post("/carts", response_model=CartResponse, status_code=201)
def create_cart() -> CartResponse:
    return _to_cart_response(commerce.create_cart())


@app.get("/carts/{cart_id}", response_model=CartResponse)
def get_cart(cart_id: str) -> CartResponse:
    try:
        return _to_cart_response(commerce.get_cart(cart_id))
    except CommerceError as error:
        _raise_http_error(error)


@app.post("/carts/{cart_id}/items", response_model=CartResponse)
def add_item(cart_id: str, request: CartItemRequest) -> CartResponse:
    try:
        return _to_cart_response(
            commerce.add_item(cart_id, request.product_id, request.quantity)
        )
    except CommerceError as error:
        _raise_http_error(error)


@app.delete("/carts/{cart_id}/items/{product_id}", response_model=CartResponse)
def remove_item(cart_id: str, product_id: str) -> CartResponse:
    try:
        return _to_cart_response(commerce.remove_item(cart_id, product_id))
    except CommerceError as error:
        _raise_http_error(error)


@app.delete("/carts/{cart_id}", response_model=CartResponse)
def clear_cart(cart_id: str) -> CartResponse:
    try:
        return _to_cart_response(commerce.clear_cart(cart_id))
    except CommerceError as error:
        _raise_http_error(error)


@app.post("/carts/{cart_id}/discounts", response_model=CartResponse)
def apply_discount(cart_id: str, request: DiscountRequest) -> CartResponse:
    try:
        return _to_cart_response(commerce.apply_discount(cart_id, request.code))
    except CommerceError as error:
        _raise_http_error(error)


@app.post("/carts/{cart_id}/checkout", response_model=CheckoutResponse)
def checkout_cart(cart_id: str) -> CheckoutResponse:
    try:
        return _to_checkout_response(commerce.checkout_cart(cart_id))
    except CommerceError as error:
        _raise_http_error(error)


@app.post("/checkout", response_model=CheckoutResponse)
def checkout(request: LegacyCheckoutModel) -> CheckoutResponse:
    try:
        return _to_checkout_response(
            commerce.checkout_items(
                [(item.product_id, item.quantity) for item in request.items]
            )
        )
    except CommerceError as error:
        _raise_http_error(error)
