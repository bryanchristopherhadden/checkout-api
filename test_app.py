import logging
from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest
from fastapi.testclient import TestClient

import app as app_module
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
from commerce import CommerceService

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_commerce(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    service = CommerceService("sqlite+pysqlite:///:memory:")
    service.initialize_for_tests()
    monkeypatch.setattr(app_module, "commerce", service)
    yield
    service.engine.dispose()


def test_health_check_has_request_id_and_logs_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="checkout_api.request")
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 36
    assert any(
        record.request_id == request_id
        and record.method == "GET"
        and record.path == "/health"
        and record.status_code == 200
        and record.duration_ms >= 0
        for record in caplog.records
        if record.name == "checkout_api.request"
    )


def test_request_middleware_logs_error_responses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="checkout_api.request")
    response = client.get("/missing-route")

    assert response.status_code == 404
    request_id = response.headers["x-request-id"]
    assert any(
        record.request_id == request_id and record.status_code == 404
        for record in caplog.records
        if record.name == "checkout_api.request"
    )


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


def test_gift_card_is_created_applied_and_redeemed_at_checkout() -> None:
    gift_card_response = client.post(
        "/gift-cards", json={"balance_cents": 700}
    )
    assert gift_card_response.status_code == 201
    gift_card = gift_card_response.json()
    gift_card_id = gift_card["gift_card_id"]
    assert gift_card["balance_cents"] == 700
    assert gift_card["currency"] == "USD"

    assert client.get(f"/gift-cards/{gift_card_id}").json()["balance_cents"] == 700
    cart_id = client.post("/carts").json()["cart_id"]
    client.post(
        f"/carts/{cart_id}/items",
        json={"product_id": "coffee", "quantity": 2},
    )
    client.post(
        f"/carts/{cart_id}/discounts", json={"code": "SAVE10"}
    )
    applied = client.post(
        f"/carts/{cart_id}/gift-cards",
        json={"gift_card_id": gift_card_id},
    )
    assert applied.status_code == 200
    assert applied.json()["gift_card_applied_cents"] == 700
    assert applied.json()["amount_due_cents"] == 200

    order = client.post(f"/carts/{cart_id}/checkout")
    assert order.status_code == 200
    assert order.json()["total_cents"] == 900
    assert order.json()["gift_card_applied_cents"] == 700
    assert order.json()["amount_due_cents"] == 200
    assert client.get(f"/gift-cards/{gift_card_id}").json()["balance_cents"] == 0
    another_cart_id = client.post("/carts").json()["cart_id"]
    response = client.post(
        f"/carts/{another_cart_id}/gift-cards",
        json={"gift_card_id": gift_card_id},
    )
    assert response.status_code == 409


def test_gift_card_balance_caps_at_checkout_total_and_can_be_removed() -> None:
    gift_card = client.post(
        "/gift-cards", json={"balance_cents": 5000}
    ).json()
    cart_id = client.post("/carts").json()["cart_id"]
    client.post(
        f"/carts/{cart_id}/items",
        json={"product_id": "coffee", "quantity": 2},
    )
    client.post(
        f"/carts/{cart_id}/gift-cards",
        json={"gift_card_id": gift_card["gift_card_id"]},
    )

    removed = client.delete(f"/carts/{cart_id}/gift-card")
    assert removed.status_code == 200
    assert removed.json()["gift_card_id"] is None
    assert removed.json()["amount_due_cents"] == 1000
    assert client.get(
        f"/gift-cards/{gift_card['gift_card_id']}"
    ).json()["balance_cents"] == 5000

    client.post(
        f"/carts/{cart_id}/gift-cards",
        json={"gift_card_id": gift_card["gift_card_id"]},
    )
    order = client.post(f"/carts/{cart_id}/checkout")
    assert order.json()["gift_card_applied_cents"] == 1000
    assert order.json()["amount_due_cents"] == 0
    assert client.get(
        f"/gift-cards/{gift_card['gift_card_id']}"
    ).json()["balance_cents"] == 4000


def test_failed_checkout_does_not_redeem_gift_card() -> None:
    gift_card = client.post(
        "/gift-cards", json={"balance_cents": 1000}
    ).json()
    cart_id = client.post("/carts").json()["cart_id"]
    other_cart_id = client.post("/carts").json()["cart_id"]
    client.post(
        f"/carts/{cart_id}/items",
        json={"product_id": "coffee", "quantity": 2},
    )
    client.post(
        f"/carts/{cart_id}/gift-cards",
        json={"gift_card_id": gift_card["gift_card_id"]},
    )
    client.post(
        f"/carts/{other_cart_id}/items",
        json={"product_id": "coffee", "quantity": 9},
    )
    assert client.post(f"/carts/{other_cart_id}/checkout").status_code == 200

    assert client.post(f"/carts/{cart_id}/checkout").status_code == 409
    assert client.get(
        f"/gift-cards/{gift_card['gift_card_id']}"
    ).json()["balance_cents"] == 1000


def test_gift_card_endpoints_reject_invalid_values_and_unknown_cards() -> None:
    assert client.post("/gift-cards", json={"balance_cents": 0}).status_code == 422
    assert client.get(f"/gift-cards/{'0' * 36}").status_code == 404


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


def test_checkout_rolls_back_stock_and_keeps_cart_when_stock_changes() -> None:
    first_cart = client.post("/carts").json()["cart_id"]
    second_cart = client.post("/carts").json()["cart_id"]
    client.post(
        f"/carts/{first_cart}/items",
        json={"product_id": "coffee", "quantity": 2},
    )
    client.post(
        f"/carts/{second_cart}/items",
        json={"product_id": "coffee", "quantity": 9},
    )
    assert client.post(f"/carts/{second_cart}/checkout").status_code == 200

    failed_checkout = client.post(f"/carts/{first_cart}/checkout")
    assert failed_checkout.status_code == 409
    assert client.get("/products/coffee/stock").json()["available_quantity"] == 1
    assert len(client.get(f"/carts/{first_cart}").json()["items"]) == 1


def test_cart_data_persists_across_service_instances(tmp_path: Path) -> None:
    database_path = tmp_path / "persistent.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    first_service = CommerceService(database_url)
    first_service.initialize_for_tests()
    cart = first_service.create_cart()
    first_service.add_item(cart.cart_id, "coffee", 2)

    second_service = CommerceService(database_url)
    second_service.initialize_for_tests()
    persisted_cart = second_service.get_cart(cart.cart_id)

    assert persisted_cart.items[0].quantity == 2
    first_service.engine.dispose()
    second_service.engine.dispose()


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
            gift_card = http_client.post(
                "/gift-cards", json={"balance_cents": 400}
            ).json()
            applied_card = http_client.post(
                f"/carts/{cart_id}/gift-cards",
                json={"gift_card_id": gift_card["gift_card_id"]},
            )
            assert applied_card.json()["amount_due_cents"] == 500
            assert (
                stub.CheckStock(CheckStockRequest(product_id="coffee"), timeout=2)
                .available_quantity
                == 10
            )

            order = stub.CheckoutCart(CartRequest(cart_id=cart_id), timeout=2)
            assert order.total_cents == 900
            assert order.gift_card_applied_cents == 400
            assert order.amount_due_cents == 500
            assert (
                http_client.get(
                    f"/gift-cards/{gift_card['gift_card_id']}"
                ).json()["balance_cents"]
                == 0
            )
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
