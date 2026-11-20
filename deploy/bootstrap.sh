#!/usr/bin/env bash
# Filename: bootstrap.sh
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>
#
# One-time (and safe to repeat) preparation of a fresh Ubuntu LTS server for Farejador:
# Docker from Docker's own repository, a pinned cosign, 1 GB of swap, automatic security updates,
# the folders for secrets and state, and the systemd timer of the updater.
#
# Run as root from the cloned repository:   sudo bash deploy/bootstrap.sh
# It never asks for, reads or prints any secret: the secret files are created empty-handed
# (folders and permissions only) and filled in by the person following the runbook.

set -euo pipefail

# Keep COSIGN_VERSION equal to the cosign-release in .github/workflows/release.yml.
COSIGN_VERSION="v3.1.4"
COSIGN_SHA256_AMD64="424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa"
COSIGN_SHA256_ARM64="ade83b7aac62e131cacfe96d958948b2150cc9efec46a570a2649b8e27dedad2"
# Fingerprint of Docker's package signing key (https://download.docker.com/linux/ubuntu/gpg).
DOCKER_GPG_FINGERPRINT="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
SWAP_FILE="/swapfile"
SWAP_SIZE_MB=1024
APP_UID=10001

HOME_DIR="/opt/farejador"
REPO_DIR="${HOME_DIR}/repo"
SECRETS_DIR="${HOME_DIR}/secrets"
STATE_DIR="/var/lib/farejador-update"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="$(dirname "$SCRIPT_DIR")"

log() { printf '[bootstrap] %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo bash deploy/bootstrap.sh" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

install_packages() {
    log "installing base packages"
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg util-linux jq unattended-upgrades >/dev/null
}

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        log "docker and compose plugin already installed"
        return
    fi
    log "installing docker from the official repository"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /tmp/docker.gpg
    fingerprint="$(gpg --show-keys --with-colons /tmp/docker.gpg | awk -F: '/^fpr/ {print $10}')"
    if ! printf '%s\n' "$fingerprint" | grep -qx "$DOCKER_GPG_FINGERPRINT"; then
        echo "the Docker signing key does not match the expected fingerprint; stopping" >&2
        rm -f /tmp/docker.gpg
        exit 1
    fi
    gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg /tmp/docker.gpg
    rm -f /tmp/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$(dpkg --print-architecture)" "$VERSION_CODENAME" >/etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
    systemctl enable --now docker
}

install_cosign() {
    if command -v cosign >/dev/null 2>&1 && cosign version 2>/dev/null | grep -q "${COSIGN_VERSION#v}"; then
        log "cosign ${COSIGN_VERSION} already installed"
        return
    fi
    log "installing cosign ${COSIGN_VERSION}"
    local arch expected tmp
    case "$(dpkg --print-architecture)" in
        amd64) arch="amd64"; expected="$COSIGN_SHA256_AMD64" ;;
        arm64) arch="arm64"; expected="$COSIGN_SHA256_ARM64" ;;
        *) echo "unsupported architecture" >&2; exit 1 ;;
    esac
    tmp="$(mktemp)"
    curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-${arch}" -o "$tmp"
    if ! printf '%s  %s\n' "$expected" "$tmp" | sha256sum -c - >/dev/null 2>&1; then
        echo "the cosign download does not match the expected SHA-256; stopping" >&2
        rm -f "$tmp"
        exit 1
    fi
    install -m 0755 "$tmp" /usr/local/bin/cosign
    rm -f "$tmp"
}

configure_swap() {
    if swapon --show=NAME --noheadings | grep -qx "$SWAP_FILE"; then
        log "swap already active"
        return
    fi
    log "creating ${SWAP_SIZE_MB} MB of swap"
    if [ ! -f "$SWAP_FILE" ]; then
        dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$SWAP_SIZE_MB" status=none
        chmod 600 "$SWAP_FILE"
        mkswap "$SWAP_FILE" >/dev/null
    fi
    swapon "$SWAP_FILE"
    grep -q "^${SWAP_FILE} " /etc/fstab || printf '%s none swap sw 0 0\n' "$SWAP_FILE" >>/etc/fstab
}

configure_security() {
    log "enabling automatic security updates and time sync"
    printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
        >/etc/apt/apt.conf.d/20auto-upgrades
    systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
    timedatectl set-ntp true || true
    # Docker's own log rotation default for any container started without compose settings.
    mkdir -p /etc/docker
    if [ ! -f /etc/docker/daemon.json ]; then
        printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "10m", "max-file": "5"}\n}\n' >/etc/docker/daemon.json
        systemctl restart docker
    fi
}

prepare_folders() {
    log "preparing folders and permissions"
    install -d -m 755 "$HOME_DIR"
    install -d -m 700 "$SECRETS_DIR"
    install -d -m 700 "$STATE_DIR"
    if [ "$SOURCE_REPO" != "$REPO_DIR" ]; then
        if [ -d "$REPO_DIR" ] && [ ! -L "$REPO_DIR" ]; then
            log "${REPO_DIR} already exists; leaving it as it is"
        else
            ln -sfn "$SOURCE_REPO" "$REPO_DIR"
        fi
    fi
    # The container user (uid ${APP_UID}) must be able to read the GitHub App key, nobody else.
    if [ -f "${SECRETS_DIR}/github_app.pem" ]; then
        chown "${APP_UID}:${APP_UID}" "${SECRETS_DIR}/github_app.pem"
        chmod 400 "${SECRETS_DIR}/github_app.pem"
    fi
    for file in farejador.env cloudflared.env; do
        if [ -f "${SECRETS_DIR}/${file}" ]; then
            chown root:root "${SECRETS_DIR}/${file}"
            chmod 600 "${SECRETS_DIR}/${file}"
        fi
    done
}

install_timer() {
    log "installing the updater timer"
    install -m 644 "${REPO_DIR}/deploy/farejador-update.service" /etc/systemd/system/farejador-update.service
    install -m 644 "${REPO_DIR}/deploy/farejador-update.timer" /etc/systemd/system/farejador-update.timer
    chmod 755 "${REPO_DIR}/deploy/update.sh"
    systemctl daemon-reload
    systemctl enable --now farejador-update.timer
}

install_packages
install_docker
install_cosign
configure_swap
configure_security
prepare_folders
install_timer
log "done. Next: put the three secret files in ${SECRETS_DIR} (see the runbook), then run ${REPO_DIR}/deploy/update.sh"
