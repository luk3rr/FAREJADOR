#!/usr/bin/env bash
# Filename: verify_deploy.sh
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>
#
# Post-deploy checklist. Prints PASS / FAIL / SKIP per item and exits non-zero if anything fails.
# It never prints secrets and never needs one.
#
#   scripts/verify_deploy.sh external <server-ip>   from your own computer: proves what the world sees
#   scripts/verify_deploy.sh server                 on the server: proves the host state
#
# What this cannot prove from outside: that GitHub's own delivery reaches the app (the WAF only
# lets GitHub in). That one is the "ping" in the App's "Recent deliveries" page (see the runbook).

set -uo pipefail

HOOKS_URL="${FAREJADOR_HOOKS_URL:-https://hooks.luk3rr.com}"
API_URL="${FAREJADOR_API_URL:-https://farejador.luk3rr.com}"  # "none" skips the API checks
APEX_URL="${FAREJADOR_APEX_URL:-https://luk3rr.com}"
DASH_URL="${FAREJADOR_DASH_URL:-}"
CURL="${FAREJADOR_CURL:-curl}"
DOCKER="${FAREJADOR_DOCKER:-docker}"
CURL_TIMEOUT=10
PORT_TIMEOUT=3
PORTS_TO_SCAN="${FAREJADOR_PORTS:-21 22 23 25 80 443 3306 5432 8080 8443}"
HOME_DIR="${FAREJADOR_HOME:-/opt/farejador}"

failures=0

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
skip() { printf 'SKIP  %s\n' "$*"; }

http_code() {
    # $1 = method, $2 = url; prints the status code, or 000 when nothing answered.
    "$CURL" -s -o /dev/null -w '%{http_code}' --max-time "$CURL_TIMEOUT" -X "$1" "$2" 2>/dev/null || true
}

http_body() {
    # $1 = url; prints the body of a GET, or nothing when nothing answered.
    "$CURL" -s --max-time "$CURL_TIMEOUT" "$1" 2>/dev/null || true
}

expect_body() {
    # $1 = description, $2 = url, $3 = text the body must contain
    local body
    body="$(http_body "$2")"
    if [[ "$body" == *"$3"* ]]; then
        pass "$1"
    else
        fail "$1: the answer does not contain ${3}"
    fi
}

expect_code() {
    # $1 = description, $2 = method, $3 = url, remaining = accepted codes
    local description="$1" method="$2" url="$3"
    shift 3
    local code
    code="$(http_code "$method" "$url")"
    local accepted
    for accepted in "$@"; do
        if [ "$code" = "$accepted" ]; then
            pass "${description} (HTTP ${code})"
            return
        fi
    done
    fail "${description}: got HTTP ${code}, expected one of: $*"
}

port_is_closed() {
    # Closed or filtered: the connection must not succeed.
    ! timeout "$PORT_TIMEOUT" bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null
}

check_external() {
    local server_ip="${1:-}"
    echo "== What the internet sees (from this computer)"
    expect_code "apex page still answers" GET "${APEX_URL}/" 200
    expect_code "GET on the webhook host root is blocked" GET "${HOOKS_URL}/" 403 404
    expect_code "GET /healthz is not public" GET "${HOOKS_URL}/healthz" 403 404
    expect_code "other paths are blocked" GET "${HOOKS_URL}/docs" 403 404
    expect_code "POST /webhook from a non-GitHub address is blocked by the WAF" POST "${HOOKS_URL}/webhook" 403
    expect_code "POST on another path is blocked" POST "${HOOKS_URL}/anything" 403 404
    check_api
    if [ -n "$DASH_URL" ]; then
        expect_code "dashboard asks for login (Cloudflare Access)" GET "${DASH_URL}/" 302 401 403
    else
        skip "dashboard check (set FAREJADOR_DASH_URL when delivery 3 exists)"
    fi

    if [ -z "$server_ip" ]; then
        skip "port scan (pass the server IP as the second argument)"
        return
    fi
    echo "== Ports on the server address"
    local port
    for port in $PORTS_TO_SCAN; do
        if port_is_closed "$server_ip" "$port"; then
            pass "port ${port} is closed"
        else
            fail "port ${port} accepted a connection on ${server_ip}"
        fi
    done
    echo "Note: port 22 is expected to be closed unless you opened it for yourself on purpose."
}

check_api() {
    if [ "$API_URL" = "none" ]; then
        skip "API checks (FAREJADOR_API_URL=none)"
        return
    fi
    echo "== The public API (${API_URL})"
    expect_code "GET /api/status answers" GET "${API_URL}/api/status" 200
    expect_body "/api/status says the trace is available" "${API_URL}/api/status" '"trace_available":true'
    expect_code "GET /api/reviews answers" GET "${API_URL}/api/reviews?limit=1" 200
    expect_body "/api/reviews is a JSON list" "${API_URL}/api/reviews?limit=1" '"items"'
    expect_code "an unknown review is a 404" GET "${API_URL}/api/reviews/999999999" 404
    expect_code "a write on the API is refused" POST "${API_URL}/api/reviews" 403 405
    expect_code "a delete on the API is refused" DELETE "${API_URL}/api/reviews/1" 403 405
    expect_code "the webhook path is not reachable on the API host" POST "${API_URL}/webhook" 403 404
    expect_code "the webhook path is not readable on the API host" GET "${API_URL}/webhook" 403 404
    expect_code "the health path is not public on the API host" GET "${API_URL}/healthz" 403 404
    expect_code "anything outside /api/ is blocked" GET "${API_URL}/docs" 403 404
}

check_server() {
    echo "== Host state (on the server)"
    local status
    status="$("$DOCKER" inspect --format '{{.State.Health.Status}}' farejador 2>/dev/null || echo missing)"
    [ "$status" = "healthy" ] && pass "farejador container is healthy" || fail "farejador container is ${status}"
    status="$("$DOCKER" inspect --format '{{.State.Status}}' cloudflared 2>/dev/null || echo missing)"
    [ "$status" = "running" ] && pass "cloudflared container is running" || fail "cloudflared container is ${status}"

    local published
    published="$("$DOCKER" ps --format '{{.Ports}}' 2>/dev/null | grep -c '0.0.0.0\|:::' || true)"
    [ "$published" = "0" ] && pass "no container publishes a port" || fail "${published} container(s) publish a port"

    if command -v ss >/dev/null 2>&1; then
        local listening
        listening="$(ss -Hltn 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|\[?::1\]?)' | grep -vE ':(22|53)$' || true)"
        [ -z "$listening" ] && pass "nothing listens on the network besides SSH and the local resolver" || fail "listening sockets: $(printf '%s' "$listening" | tr '\n' ' ')"
    else
        skip "listening sockets (ss not installed)"
    fi

    if systemctl is-active --quiet farejador-update.timer 2>/dev/null; then
        pass "updater timer is active"
    else
        fail "updater timer is not active"
    fi

    local file mode owner
    for file in farejador.env cloudflared.env; do
        mode="$(stat -c '%a' "${HOME_DIR}/secrets/${file}" 2>/dev/null || echo missing)"
        owner="$(stat -c '%U' "${HOME_DIR}/secrets/${file}" 2>/dev/null || echo missing)"
        [ "$mode" = "600" ] && [ "$owner" = "root" ] && pass "${file} is root:600" || fail "${file} has mode ${mode}, owner ${owner}"
    done
    mode="$(stat -c '%a %u' "${HOME_DIR}/secrets/github_app.pem" 2>/dev/null || echo missing)"
    [ "$mode" = "400 10001" ] && pass "github_app.pem is 400 and owned by uid 10001" || fail "github_app.pem has mode/owner ${mode}"

    if "$DOCKER" exec farejador test -s /data/trace.db 2>/dev/null; then
        pass "the trace database exists in the data volume"
    else
        fail "the trace database /data/trace.db is missing or empty"
    fi

    swapon --show=NAME --noheadings 2>/dev/null | grep -q . && pass "swap is active" || fail "swap is not active"
}

case "${1:-}" in
    external) check_external "${2:-}" ;;
    server) check_server ;;
    *)
        echo "usage: $0 external [server-ip] | server" >&2
        exit 2
        ;;
esac

echo
if [ "$failures" -eq 0 ]; then
    echo "All checks passed."
    exit 0
fi
echo "${failures} check(s) failed."
exit 1
