#!/usr/bin/env bash
# Filename: update.sh
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>
#
# Farejador image updater (runs on the server, every 5 minutes, from a systemd timer).
#
# It follows the image tag "stable", which only moves after a person approves a release in the
# GitHub Environment "production". For a new digest it:
#   1. verifies the signature (cosign, identity of this repository's release workflow);
#   2. switches the container to that exact digest and waits for the health check;
#   3. rolls back to the last healthy digest, and refuses the bad digest, if it does not get healthy.
# The server never accepts a connection from GitHub: this script only makes outbound requests.
#
# Usage: update.sh            apply an update if there is a new, correctly signed digest
#        update.sh --check    only report what it would do
#
# Exit codes: 0 nothing to do or updated; 1 an update was refused or rolled back; 2 missing tool.

set -euo pipefail

IMAGE_REPO="${FAREJADOR_IMAGE_REPO:-ghcr.io/luk3rr/farejador}"
STABLE_TAG="${FAREJADOR_STABLE_TAG:-stable}"
HOME_DIR="${FAREJADOR_HOME:-/opt/farejador}"
STATE_DIR="${FAREJADOR_UPDATE_STATE_DIR:-/var/lib/farejador-update}"
COMPOSE_FILE="${FAREJADOR_COMPOSE_FILE:-${HOME_DIR}/repo/docker-compose.server.yml}"
IMAGE_ENV="${FAREJADOR_IMAGE_ENV:-${HOME_DIR}/image.env}"
CONTAINER="${FAREJADOR_CONTAINER:-farejador}"
SIGNER_IDENTITY_REGEX="${FAREJADOR_SIGNER_IDENTITY_REGEX:-^https://github.com/luk3rr/FAREJADOR/.github/workflows/release.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+\$}"
OIDC_ISSUER="${FAREJADOR_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

NET_TIMEOUT="${FAREJADOR_NET_TIMEOUT:-30}"
VERIFY_TIMEOUT="${FAREJADOR_VERIFY_TIMEOUT:-60}"
PULL_TIMEOUT="${FAREJADOR_PULL_TIMEOUT:-300}"
HEALTH_TIMEOUT="${FAREJADOR_HEALTH_TIMEOUT:-120}"
HEALTH_INTERVAL="${FAREJADOR_HEALTH_INTERVAL:-5}"

DOCKER="${FAREJADOR_DOCKER:-docker}"
COSIGN="${FAREJADOR_COSIGN:-cosign}"

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=1
fi

log() {
    # $1 = level, remaining = message. Never print secrets: this script does not read any.
    local level="$1"
    shift
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$*"
}

for tool in "$DOCKER" "$COSIGN" timeout flock; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        log ERROR "required tool not found: $tool"
        exit 2
    fi
done

umask 077
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# Only one update at a time (a slow pull must not overlap the next timer run).
exec 9>"${STATE_DIR}/lock"
if ! flock -n 9; then
    log INFO "another update is already running; nothing to do"
    exit 0
fi

valid_digest() {
    [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]]
}

read_state() {
    # Prints the content of a state file, or nothing if it does not exist.
    local file="${STATE_DIR}/$1"
    if [ -f "$file" ]; then
        tr -d '[:space:]' <"$file"
    fi
}

current_digest() {
    if [ -f "$IMAGE_ENV" ]; then
        sed -n 's/^FAREJADOR_IMAGE=.*@\(sha256:[0-9a-f]\{64\}\)$/\1/p' "$IMAGE_ENV" | head -n 1
    fi
}

is_refused() {
    [ -f "${STATE_DIR}/bad" ] && grep -q "^$1 " "${STATE_DIR}/bad"
}

refuse() {
    printf '%s %s %s\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" >>"${STATE_DIR}/bad"
    chmod 600 "${STATE_DIR}/bad"
}

write_image_env() {
    local tmp="${IMAGE_ENV}.tmp"
    printf 'FAREJADOR_IMAGE=%s@%s\n' "$IMAGE_REPO" "$1" >"$tmp"
    chmod 644 "$tmp"
    mv "$tmp" "$IMAGE_ENV"
}

compose() {
    "$DOCKER" compose --env-file "$IMAGE_ENV" -f "$COMPOSE_FILE" "$@"
}

verify_signature() {
    timeout "$VERIFY_TIMEOUT" "$COSIGN" verify "${IMAGE_REPO}@$1" \
        --certificate-identity-regexp "$SIGNER_IDENTITY_REGEX" \
        --certificate-oidc-issuer "$OIDC_ISSUER" >/dev/null
}

wait_healthy() {
    local attempts=$((HEALTH_TIMEOUT / HEALTH_INTERVAL))
    local status
    local i
    for ((i = 0; i < attempts; i++)); do
        status="$("$DOCKER" inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
        case "$status" in
            healthy) return 0 ;;
            unhealthy) return 1 ;;
        esac
        sleep "$HEALTH_INTERVAL"
    done
    return 1
}

roll_back() {
    # $1 = refused digest, $2 = reason, $3 = last healthy digest (may be empty)
    local bad="$1" reason="$2" good="$3"
    refuse "$bad" "$reason"
    if [ -n "$good" ]; then
        log WARN "rolling back to the last healthy digest ${good}"
        write_image_env "$good"
        compose up -d >/dev/null 2>&1 || log ERROR "docker compose up failed during the rollback"
        if wait_healthy; then
            log INFO "rollback finished; ${bad} is refused until a new digest appears"
        else
            log ERROR "the previous version is not healthy either; manual action needed"
        fi
    else
        log ERROR "no healthy version to go back to; stopping the service"
        compose stop >/dev/null 2>&1 || true
    fi
}

new="$(timeout "$NET_TIMEOUT" "$DOCKER" buildx imagetools inspect "${IMAGE_REPO}:${STABLE_TAG}" --format '{{.Manifest.Digest}}' 2>/dev/null | tr -d '[:space:]' || true)"
if [ -z "$new" ]; then
    log WARN "could not read the digest of ${IMAGE_REPO}:${STABLE_TAG}; will try again later"
    exit 0
fi
if ! valid_digest "$new"; then
    log ERROR "the registry answered something that is not a digest; refusing to continue"
    exit 1
fi

cur="$(current_digest)"
if [ "$new" = "$cur" ]; then
    log INFO "already running ${new}"
    exit 0
fi
if is_refused "$new"; then
    log INFO "skipping ${new}: it was refused before and no new digest has appeared"
    exit 0
fi
if [ "$CHECK_ONLY" = 1 ]; then
    log INFO "update available: ${new} (running: ${cur:-none})"
    exit 0
fi

log INFO "new digest ${new} (running: ${cur:-none}); verifying the signature"
if ! verify_signature "$new"; then
    refuse "$new" "invalid-signature"
    log ERROR "signature verification failed for ${new}; refusing it"
    exit 1
fi
log INFO "signature is valid"

last_good="$(read_state last_good)"
if [ -z "$last_good" ] && [ -n "$cur" ]; then
    last_good="$cur"
fi

write_image_env "$new"
if ! timeout "$PULL_TIMEOUT" "$DOCKER" compose --env-file "$IMAGE_ENV" -f "$COMPOSE_FILE" pull >/dev/null 2>&1; then
    log ERROR "could not pull ${new}"
    if [ -n "$last_good" ]; then
        write_image_env "$last_good"
    else
        rm -f "$IMAGE_ENV"
    fi
    refuse "$new" "pull-failed"
    exit 1
fi

if ! compose up -d >/dev/null 2>&1; then
    log ERROR "docker compose up failed for ${new}"
    roll_back "$new" "compose-failed" "$last_good"
    exit 1
fi
if wait_healthy; then
    printf '%s\n' "$new" >"${STATE_DIR}/last_good"
    chmod 600 "${STATE_DIR}/last_good"
    log INFO "now running ${new}"
    if [ -n "$last_good" ] && [ "$last_good" != "$new" ]; then
        "$DOCKER" image rm "${IMAGE_REPO}@${last_good}" >/dev/null 2>&1 || true
    fi
    exit 0
fi

log ERROR "${new} did not become healthy within ${HEALTH_TIMEOUT}s"
roll_back "$new" "unhealthy" "$last_good"
exit 1
