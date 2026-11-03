# Checkout API

A compact checkout microservice demonstrating a Python service with a
FastAPI/HTTP interface and a protobuf/gRPC command interface. It supports
product listings and stock checks, cart creation and updates, discount
application, and checkout.

This repository is also used as a code-review exercise for an AI reviewer.
It gives reviewers, recruiters, and hiring engineers a concrete example to
explore, run, and assess—including its API design, shared service layer,
validation, tests, and generated gRPC bindings.

The implementation is intentionally small and in-memory: it is a
demonstration project, not a production-ready commerce system. Cart and stock
state reset when the service restarts; it does not persist orders or process
payments.

## Start the API

Run these commands from the project directory. The virtual environment keeps
Python packages separate from macOS's system-managed Python:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

If you already created `.venv`, skip the `venv` creation command and activate
it with `source .venv/bin/activate`. Activate it again whenever you open a new
terminal before running the API.

The API is available at `http://127.0.0.1:8000`; open
`http://127.0.0.1:8000/docs` for interactive API documentation. The FastAPI
process also starts the gRPC service on port `50051`. Set `CHECKOUT_GRPC_PORT`
to choose another port (or `0` to let the OS choose one).

## Postman

Import [`postman/Checkout API.postman_collection.json`](./postman/Checkout%20API.postman_collection.json)
in Postman using **Import → File**. With the API running, send requests in
order from **Create cart** through **Checkout cart**. The create request saves
the new cart ID to the collection variable automatically. The collection's
`baseUrl` variable defaults to `http://127.0.0.1:8000`.

Generate the Python gRPC bindings after changing `checkout.proto`:

```sh
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. checkout.proto
```

## HTTP API

- `GET /health` checks that the service is running.
- `GET /products` lists the demo catalog. Prices are integer cents.
- `GET /products/{product_id}/stock` checks available inventory.
- `POST /carts` creates an empty cart.
- `GET /carts/{cart_id}` reads a cart and its totals.
- `POST /carts/{cart_id}/items` adds `{"product_id":"coffee","quantity":2}`.
- `DELETE /carts/{cart_id}/items/{product_id}` removes a product.
- `DELETE /carts/{cart_id}` clears the cart.
- `POST /carts/{cart_id}/discounts` accepts `{"code":"SAVE10"}` or
  `{"code":"SAVE20"}`.
- `POST /carts/{cart_id}/checkout` checks out the cart, applies its discount,
  and decrements inventory.
- `POST /checkout` retains the original stateless checkout request format.

## gRPC commands

The `CheckoutCommands` service in [`checkout.proto`](./checkout.proto) supports
`CreateCart`, `AddToCart`, `RemoveFromCart`, `ClearCart`, `ApplyDiscount`,
`CheckoutCart`, and `CheckStock`. Both transports use the same in-process cart
and inventory state.

Run the tests with `pytest`.
