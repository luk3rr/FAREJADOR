# syntax=docker/dockerfile:1

# ---- web stage: compile the dashboard. Node lives only here, never in the final image ----
FROM node:22.22.1-slim@sha256:4f77a690f2f8946ab16fe1e791a3ac0667ae1c3575c3e4d0d4589e9ed5bfaf3d AS web
WORKDIR /web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run check && WEB_OUT=/out npm run build

# ---- build stage: resolve and install the locked dependencies, then the package ----
FROM python:3.13-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY --from=web /out ./src/farejador/web/static
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
# The release passes its tag here so the trace can tell versions apart; a local build says "dev".
ARG APP_VERSION=dev
ENV FAREJADOR_APP_VERSION=${APP_VERSION}
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
