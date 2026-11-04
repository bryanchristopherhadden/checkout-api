# Runbook: run and test the Checkout API locally

Step-by-step commands for running the API three ways and testing it:

1. **Docker Compose**: PostgreSQL in Docker, API on your Mac (fastest for development).
2. **Docker image**: the API packaged as a container image.
3. **Kubernetes (minikube + Helm)**: the API and PostgreSQL deployed to a local cluster.

Run every command from the repository root (`checkout-api/`) unless a step says
otherwise. Commands were verified on macOS (Apple Silicon) with Colima.

---

## 0. One-time setup

Install the tools (Homebrew):

```sh
brew install colima docker docker-compose kubernetes-cli helm minikube
```

Tell Docker where the Compose plugin is. Add this key to `~/.docker/config.json`
(keep the existing keys):

```json
"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
```

Check it:

```sh
docker compose version
```

Start the Docker runtime (Colima). Run this after every reboot:

```sh
colima start --cpu 2 --memory 4 --disk 20
docker version --format 'server={{.Server.Version}}'
```

Python tools for running the tests (only needed once):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

---

## 1. Docker Compose (PostgreSQL in Docker, API on your Mac)

```sh
docker compose up -d postgres
docker compose ps                     # wait for "(healthy)"

cp -n .env.example .env               # local dev credentials; optional
source .venv/bin/activate
set -a; source .env; set +a
alembic upgrade head                  # creates tables and seeds demo products
uvicorn app:app --reload
```

The API is now at <http://127.0.0.1:8000>, interactive docs at
<http://127.0.0.1:8000/docs>, and gRPC on port `50051`.

Stop it:

```sh
docker compose down                   # keeps data
docker compose down -v                # deletes the database volume too
```

---

## 2. Build the Docker image

```sh
docker build -t checkout-api:dev .
```

Run the image against the Compose database. Migrations are not run
automatically inside the container, so run them first:

```sh
docker run --rm \
  -e DATABASE_URL=postgresql+psycopg://checkout:checkout@host.docker.internal:5432/checkout \
  checkout-api:dev alembic upgrade head

docker run -d --name checkout-api \
  -e DATABASE_URL=postgresql+psycopg://checkout:checkout@host.docker.internal:5432/checkout \
  -p 8000:8000 checkout-api:dev

curl http://127.0.0.1:8000/health      # {"status":"ok"}
docker logs checkout-api               # request logs
docker rm -f checkout-api              # stop and remove
```

`host.docker.internal` is how a container reaches Postgres published on your Mac.
Port 8000 must be free (stop `uvicorn` first).

---

## 3. Kubernetes with minikube and Helm

### 3a. Start the cluster (once per boot)

```sh
colima start --cpu 2 --memory 4 --disk 20        # skip if already running
minikube start --driver=docker --cpus=2 --memory=3072 --profile=checkout
kubectl config use-context checkout
kubectl get nodes                                 # STATUS should be Ready
```

If the node says `NotReady` right after start, wait 30 seconds and check again.

### 3b. Build the image and load it into the cluster

minikube runs its own container runtime, so it needs the image copied in. Use a
new tag for every build (see Troubleshooting):

```sh
TAG=$(date +%Y%m%d%H%M%S)
docker build -t checkout-api:$TAG .
minikube -p checkout image load checkout-api:$TAG
minikube -p checkout image ls | grep checkout-api
```

### 3c. Install the Helm release

The chart creates the API Deployment and Service, a PostgreSQL Deployment and
Service, a database Secret, and a migration Job. The Job runs after install and
waits for the database to accept connections.

```sh
helm lint charts/checkout-api -f values/minikube.yaml
helm install checkout charts/checkout-api -f values/minikube.yaml \
  --set image.tag=$TAG --wait --timeout 5m
```

`--wait` returns when the pods are ready. Expect `STATUS: deployed`.

Check the pods:

```sh
kubectl get pods
kubectl get svc
kubectl get endpoints checkout-checkout-api   # should list the API pod IP
```

The API pod may restart once or twice on first install. It starts before the
migration Job has created the tables, then recovers. This is expected for now.

### 3d. Test the API

Open a port-forward in its own terminal (it stays running until you press Ctrl+C):

```sh
kubectl port-forward svc/checkout-checkout-api 18000:8000
```

In another terminal:

```sh
curl http://127.0.0.1:18000/health                  # {"status":"ok"}
curl http://127.0.0.1:18000/products                # 3 seeded products
curl -X POST http://127.0.0.1:18000/carts           # 201 with a new cart_id
```

Then try a full checkout. Replace `CART_ID` with the `cart_id` from the last command:

```sh
curl -X POST http://127.0.0.1:18000/carts/CART_ID/items \
  -H 'content-type: application/json' -d '{"product_id":"coffee","quantity":2}'
curl -X POST http://127.0.0.1:18000/carts/CART_ID/discounts \
  -H 'content-type: application/json' -d '{"code":"SAVE10"}'
curl -X POST http://127.0.0.1:18000/carts/CART_ID/checkout
```

For Postman, import `postman/Checkout API.postman_collection.json` and set the
`baseUrl` variable to `http://127.0.0.1:18000`.

gRPC listens on port `50051` inside the cluster. To reach it from your Mac:

```sh
kubectl port-forward svc/checkout-checkout-api 15051:50051
```

Then point a gRPC client at `127.0.0.1:15051`.

### 3e. Inspect logs and state

```sh
kubectl logs deploy/checkout-checkout-api --tail=50
kubectl describe pod -l app.kubernetes.io/component=api
kubectl get events --sort-by=.lastTimestamp | tail -20
helm status checkout
helm history checkout
```

### 3f. Deploy a change

Change the code, then build a new tag and upgrade:

```sh
TAG=$(date +%Y%m%d%H%M%S)
docker build -t checkout-api:$TAG .
minikube -p checkout image load checkout-api:$TAG
helm upgrade checkout charts/checkout-api -f values/minikube.yaml \
  --set image.tag=$TAG --wait --timeout 5m
```

The upgrade also runs the migration Job again.

### 3g. Stop and clean up

```sh
helm uninstall checkout                  # removes the app and database (emptyDir data is lost)
minikube -p checkout stop                # keeps the cluster
minikube -p checkout delete              # deletes the cluster
colima stop                              # stops the Docker runtime
```

---

## 4. Run the test suite

The tests need PostgreSQL. Start the Compose database first (section 1), then:

```sh
source .venv/bin/activate
DATABASE_URL=postgresql+psycopg://checkout:checkout@localhost:5432/checkout \
  CHECKOUT_GRPC_PORT=0 python -m pytest -q
```

Last verified result: `15 passed`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker: unknown command: docker compose` | Compose plugin path not configured | Add `cliPluginsExtraDirs` to `~/.docker/config.json` (step 0) |
| `Cannot connect to the Docker daemon` | Colima is stopped | `colima start` |
| `minikube` fails or hangs | Colima or Docker not running, or too little memory | `colima status`; restart Colima with more memory |
| Node stays `NotReady` | Still starting | Wait 30 s, then `kubectl describe node checkout` |
| Port already in use (8000, 5432, 18000) | Another container or process holds it | `docker ps`; `lsof -i :8000`; stop it |
| Pod `CrashLoopBackOff` | App cannot connect to the database, or the migration failed | `kubectl logs deploy/checkout-checkout-api`, `kubectl logs job/<name>` |
| Code change not visible in the cluster | Same image tag was reused and minikube kept the old image | Use a new `TAG` each build (step 3b) |
| `port-forward` says `does not have a named port 'http'` | Service selector matched the Postgres pod (fixed in the chart; reinstall to pick up the fix) | `helm uninstall checkout`, then reinstall |
| `Error: UPGRADE FAILED` | A Deployment selector changed, which Kubernetes does not allow | `helm uninstall checkout`, then reinstall |
| Tests fail with connection refused | Compose Postgres not running | `docker compose up -d postgres` |
| `alembic` errors about the database | Migrations not applied | `alembic upgrade head` (or let the Helm migration Job run) |

Useful checks when something is wrong:

```sh
colima status
minikube -p checkout status
kubectl get pods -A
kubectl describe pod <pod-name>
kubectl logs <pod-name> --previous     # logs from the last crashed container
```
