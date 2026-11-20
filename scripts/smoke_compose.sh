#!/usr/bin/env bash
# Filename: smoke_compose.sh
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>
#
# Manual smoke test of the packaging. It builds the image once, validates both compose
# profiles and runs the CLI inside the container with throwaway settings. It never contacts
# GitHub or OpenRouter: the RSA key below is generated here and is not a real App key.
#
# Usage: scripts/smoke_compose.sh                    (Docker usable without a password prompt)
#        DOCKER="sudo docker" scripts/smoke_compose.sh

set -euo pipefail

DOCKER="${DOCKER:-docker}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/env" <<ENV
FAREJADOR_GITHUB_APP_ID=1
FAREJADOR_GITHUB_PRIVATE_KEY_PATH=/run/secrets/github_app.pem
FAREJADOR_WEBHOOK_SECRET=smoke-test-secret
FAREJADOR_OPENROUTER_API_KEY=sk-or-smoke-test-key
FAREJADOR_MODEL=test/model
ENV
openssl genrsa -out "$WORK/app.pem" 2048 2>/dev/null

export FAREJADOR_ENV_FILE="$WORK/env"
export FAREJADOR_PRIVATE_KEY_FILE="$WORK/app.pem"
export FAREJADOR_HOST_PORT=18080

cd "$ROOT"
compose() { $DOCKER compose -p farejador-smoke "$@"; }

echo "==> compose file is valid for both profiles"
compose --profile polling config --quiet
compose --profile webhook config --quiet

echo "==> building the image shared by both profiles"
compose --profile webhook build

echo "==> the CLI runs inside the container"
$DOCKER run --rm farejador:local version
$DOCKER run --rm --env-file "$WORK/env" -v "$WORK/app.pem:/run/secrets/github_app.pem:ro" \
    farejador:local check-config

echo "==> the container runs as a non-root user with a read-only root file system"
test "$($DOCKER run --rm --entrypoint id farejador:local -u)" != "0"
$DOCKER run --rm --read-only --tmpfs /tmp --entrypoint python farejador:local -c \
    "import tempfile; tempfile.mkdtemp(); print('temp dir OK')"

echo "==> healthcheck: fails with nothing listening, succeeds against a stub /healthz"
if $DOCKER run --rm -e FAREJADOR_MODE=webhook -e FAREJADOR_PORT=8099 farejador:local healthcheck; then
    echo "unexpected: healthcheck passed with no server" >&2
    exit 1
fi
$DOCKER run --rm -i -e FAREJADOR_MODE=webhook -e FAREJADOR_PORT=8099 --entrypoint python \
    farejador:local - <<'PY'
import http.server
import subprocess
import sys
import threading


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 8099), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
sys.exit(subprocess.call(["farejador", "healthcheck"]))
PY

echo "==> OK: the image builds, both compose profiles are valid and the container behaves"
