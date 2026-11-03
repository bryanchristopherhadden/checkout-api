import grpc
import pytest
from fastapi.testclient import TestClient

from app import app
from checkout_pb2 import (
    AddToCartRequest,
    ApplyDiscountRequest,
    CartRequest,
    CheckStockRequest,
    CreateCartRequest,
    RemoveFromCartRequest,
)
from checkout_pb2_grpc import CheckoutCommandsStub
from commerce import commerce

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_commerce() -> None:
    commerce.reset()


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_products() -> None:
    response = client.get("/products")

    assert response.status_code == 200
    assert response.json()[0] == {
        "product_id": "coffee",
        "name": "Coffee",
        "unit_price_cents": 500,
    }


def test_checkout_calculates_total_in_cents() -> None:
    response = client.post(
        "/checkout",
        json={
            "items": [
                {"product_id": "coffee", "quantity": 2},
                {"product_id": "mug", "quantity": 1},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert body["total_cents"] == 2200
    assert len(body["order_id"]) == 36


def test_checkout_rejects_unknown_product() -> None:
    response = client.post(
        "/checkout",
        json={"items": [{"product_id": "unknown", "quantity": 1}]},
    )

    assert response.status_code == 404


def test_checkout_rejects_empty_cart() -> None:
    response = client.post("/checkout", json={"items": []})

    assert response.status_code == 422


def test_cart_lifecycle_applies_discount_and_updates_stock() -> None:
    created = client.post("/carts")
    assert created.status_code == 201
    cart_id = created.json()["cart_id"]

    added = client.post(
        f"/carts/{cart_id}/items",
        json={"product_id": "coffee", "quantity": 2},
    )
    assert added.status_code == 200
    assert added.json()["subtotal_cents"] == 1000

    discounted = client.post(
        f"/carts/{cart_id}/discounts", json={"code": "SAVE10"}
    )
    assert discounted.json()["discount_cents"] == 100
    assert discounted.json()["total_cents"] == 900

    order = client.post(f"/carts/{cart_id}/checkout")
    assert order.status_code == 200
    assert order.json()["total_cents"] == 900
    assert client.get("/products/coffee/stock").json()["available_quantity"] == 8
    assert client.get(f"/carts/{cart_id}").json()["items"] == []


def test_cart_rejects_unknown_discounts_and_insufficient_stock() -> None:
    cart_id = client.post("/carts").json()["cart_id"]

    invalid_discount = client.post(
        f"/carts/{cart_id}/discounts", json={"code": "NOTREAL"}
    )
    assert invalid_discount.status_code == 400

    too_many = client.post(
        f"/carts/{cart_id}/items",
        json={"product_id": "mug", "quantity": 6},
    )
    assert too_many.status_code == 409


def test_grpc_commands_use_the_same_cart_and_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHECKOUT_GRPC_PORT", "0")
    with TestClient(app) as http_client:
        with grpc.insecure_channel(
            f"127.0.0.1:{app.state.grpc_port}"
        ) as channel:
            stub = CheckoutCommandsStub(channel)
            cart_id = stub.CreateCart(CreateCartRequest(), timeout=2).cart_id
            added = stub.AddToCart(
                AddToCartRequest(
                    cart_id=cart_id, product_id="coffee", quantity=2
                ),
                timeout=2,
            )
            assert added.subtotal_cents == 1000

            discounted = stub.ApplyDiscount(
                ApplyDiscountRequest(cart_id=cart_id, code="SAVE10"), timeout=2
            )
            assert discounted.total_cents == 900
            assert (
                stub.CheckStock(CheckStockRequest(product_id="coffee"), timeout=2)
                .available_quantity
                == 10
            )

            order = stub.CheckoutCart(CartRequest(cart_id=cart_id), timeout=2)
            assert order.total_cents == 900
            assert (
                stub.CheckStock(CheckStockRequest(product_id="coffee"), timeout=2)
                .available_quantity
                == 8
            )

            removable_cart_id = stub.CreateCart(CreateCartRequest(), timeout=2).cart_id
            stub.AddToCart(
                AddToCartRequest(
                    cart_id=removable_cart_id, product_id="mug", quantity=1
                ),
                timeout=2,
            )
            removed = stub.RemoveFromCart(
                RemoveFromCartRequest(
                    cart_id=removable_cart_id, product_id="mug"
                ),
                timeout=2,
            )
            assert not removed.items
            cleared = stub.ClearCart(
                CartRequest(cart_id=removable_cart_id), timeout=2
            )
            assert not cleared.items

        assert http_client.get(f"/carts/{cart_id}").json()["items"] == []
