# syntax=docker/dockerfile:1

# ---- build stage: resolve and install the locked dependencies, then the package ----
FROM python:3.13-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime stage: Python, git and the virtual environment only ----
FROM python:3.13-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /nonexistent --no-create-home farejador \
    && mkdir /data \
    && chown farejador /data
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FAREJADOR_STATE_PATH=/data/farejador.db \
    FAREJADOR_HOST=0.0.0.0
LABEL org.opencontainers.image.source="https://github.com/luk3rr/FAREJADOR" \
      org.opencontainers.image.description="Farejador: agentic first-pass code reviewer for GitHub pull requests"
USER farejador
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["farejador", "healthcheck"]
ENTRYPOINT ["farejador"]
CMD ["run"]
