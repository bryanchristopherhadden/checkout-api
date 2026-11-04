# Checkout API

A compact checkout microservice demonstrating a Python service with a
FastAPI/HTTP interface and a protobuf/gRPC command interface. It supports
product listings and stock checks, cart creation and updates, discount
application, and checkout.

This repository is also used as a code-review exercise for an AI reviewer.
It gives reviewers, recruiters, and hiring engineers a concrete example to
explore, run, and assess—including its API design, shared service layer,
validation, tests, and generated gRPC bindings.

The service stores carts, orders, and inventory in PostgreSQL. It is still a
small demonstration project, not a complete production commerce system; it
does not process payments or provide user authentication.

## Start PostgreSQL and the API

Start a local PostgreSQL database with Docker Compose:

```sh
docker compose up -d postgres
```

On macOS without Docker, PostgreSQL can instead be installed and started with
Homebrew:

```sh
brew install postgresql@17
brew services start postgresql@17
psql -d postgres -c "CREATE ROLE checkout LOGIN PASSWORD 'checkout'"
psql -d postgres -c "CREATE DATABASE checkout OWNER checkout"
```

Set up the Python environment and configure the database connection:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
set -a
source .env
set +a
alembic upgrade head
uvicorn app:app --reload
```

If you already created `.venv`, skip the `venv` creation command and activate
it with `source .venv/bin/activate`. Activate it again whenever you open a new
terminal before running the API.

After the one-time setup above, start the API from the project directory with
this single command (it activates the virtual environment, loads `.env` if
present, applies pending migrations, and starts the server):

```sh
source .venv/bin/activate && if [ -f .env ]; then set -a && source .env && set +a; fi && alembic upgrade head && uvicorn app:app --reload
```

The app defaults to the local development database URL in
`.env.example`, so `.env` is optional for the default local setup. Copy
`.env.example` to `.env` if you want to configure the database URL or gRPC
port.

The Compose setup uses a local development database (`checkout` / `checkout`);
do not use these credentials outside local development. `.env.example` contains
fake local-development credentials; copy it to `.env` and adjust the URL if
needed. If PostgreSQL is installed another way, start it with your platform's
service manager and set `DATABASE_URL` in `.env` to the database URL. The
database migration command creates the schema and demo products. Inventory is
decremented at checkout; adding an item to a cart does not reserve stock.

The API is available at `http://127.0.0.1:8000`; open
`http://127.0.0.1:8000/docs` for interactive API documentation. The API also
starts gRPC on port `50051`. Set `CHECKOUT_GRPC_PORT` to choose another port.

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

- HTTP responses include an `X-Request-ID` header. Request logs include that
  ID, method, path, status, and request duration; use the ID to correlate a
  client response with server logs.
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
`CheckoutCart`, and `CheckStock`. Both transports use the same PostgreSQL-backed
cart and inventory state.

## Continuous integration

GitHub Actions runs on pushes to `main` and on pull requests targeting `main`.
The workflow tests Python 3.12, 3.13, and 3.14, starts PostgreSQL 17, applies
database migrations, and runs the test suite. Results appear in each pull
request's **Checks** tab and as a status check on the commit.

Automatic deployment (CD) is not configured; it requires selecting a hosting
provider and adding its deployment settings and secrets.

Run the tests with `pytest`. Tests use isolated SQLite databases; the
application itself defaults to PostgreSQL using `DATABASE_URL`.
