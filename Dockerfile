# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    NANOBOT_SKIP_WEBUI_BUILD=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TESTING_AGENT_NANOBOT_RUNTIME_ROOT=/data/runtime

RUN groupadd --system --gid 10001 worker \
    && useradd --system --uid 10001 --gid worker --home-dir /app worker \
    && mkdir -p /app/logs /data/runtime \
    && chown -R worker:worker /app /data/runtime

WORKDIR /app

COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --chown=worker:worker config ./config

USER 10001:10001

STOPSIGNAL SIGTERM

CMD ["testing-agent-ai-worker"]
