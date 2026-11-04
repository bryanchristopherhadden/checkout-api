# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so code changes don't invalidate the pip layer.
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

# Application code and migrations (see .dockerignore for exclusions).
COPY . .

# Run as an unprivileged user.
RUN useradd --uid 10001 --home-dir /app checkout \
    && chown -R checkout:checkout /app
USER 10001

ENV CHECKOUT_GRPC_PORT=50051
EXPOSE 8000 50051

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
