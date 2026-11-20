# Filename: test_bootstrap_script.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Static checks of the host bootstrap (FR-10, NFR-2.5, NFR-2.6). It is never executed here."""

import re
import subprocess

from tests.workflows import ROOT

SCRIPT = ROOT / "deploy" / "bootstrap.sh"
TEXT = SCRIPT.read_text()


def test_the_script_is_valid_bash_and_starts_with_the_file_header() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    lines = TEXT.splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "# Filename: bootstrap.sh"
    assert "set -euo pipefail" in TEXT


def test_it_refuses_to_run_without_root() -> None:
    assert 'id -u)" -ne 0' in TEXT


def test_the_cosign_version_and_checksums_are_pinned_and_verified_before_installing() -> None:
    assert re.search(r'^COSIGN_VERSION="v\d+\.\d+\.\d+"$', TEXT, re.M)
    checksums = re.findall(r'^COSIGN_SHA256_\w+="([0-9a-f]{64})"$', TEXT, re.M)
    assert len(checksums) == 2
    assert "sha256sum -c" in TEXT
    assert TEXT.index("sha256sum -c") < TEXT.index('install -m 0755 "$tmp" /usr/local/bin/cosign')


def test_the_cosign_version_matches_the_release_workflow() -> None:
    version = re.search(r'^COSIGN_VERSION="(v[\d.]+)"$', TEXT, re.M)
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert version is not None
    assert workflow.count(f"cosign-release: {version.group(1)}") == 2


def test_the_docker_signing_key_fingerprint_is_checked() -> None:
    assert re.search(r'^DOCKER_GPG_FINGERPRINT="[0-9A-F]{40}"$', TEXT, re.M)
    assert "does not match the expected fingerprint" in TEXT


def test_nothing_is_piped_from_the_network_into_a_shell() -> None:
    assert not re.search(r"curl[^\n]*\|\s*(sudo\s+)?(ba)?sh", TEXT)
    assert not re.search(r"wget[^\n]*\|\s*(sudo\s+)?(ba)?sh", TEXT)


def test_every_step_is_safe_to_repeat() -> None:
    for guard in (
        "already installed",
        "swap already active",
        'grep -q "^${SWAP_FILE} " /etc/fstab',
        "install -d",
        "ln -sfn",
    ):
        assert guard in TEXT, guard


def test_secret_files_get_the_permissions_of_the_design() -> None:
    assert 'install -d -m 700 "$SECRETS_DIR"' in TEXT
    assert 'chown "${APP_UID}:${APP_UID}" "${SECRETS_DIR}/github_app.pem"' in TEXT
    assert 'chmod 400 "${SECRETS_DIR}/github_app.pem"' in TEXT
    assert 'chmod 600 "${SECRETS_DIR}/${file}"' in TEXT
    assert "APP_UID=10001" in TEXT


def test_it_never_reads_or_prints_secret_values() -> None:
    for forbidden in ("TUNNEL_TOKEN", "OPENROUTER", "WEBHOOK_SECRET", 'cat "${SECRETS_DIR}'):
        assert forbidden not in TEXT, forbidden


def test_it_sets_up_swap_updates_time_sync_and_the_timer() -> None:
    for expected in (
        "SWAP_SIZE_MB=1024",
        "unattended-upgrades",
        "timedatectl set-ntp true",
        "systemctl enable --now farejador-update.timer",
        "max-size",
    ):
        assert expected in TEXT, expected


def test_flock_comes_from_util_linux_because_it_is_not_an_apt_package() -> None:
    install_line = next(line for line in TEXT.splitlines() if "apt-get install -y -qq ca-" in line)
    assert "util-linux" in install_line
    assert " flock " not in install_line


def test_the_updater_unit_can_run_a_script_reached_through_a_symlink_into_home() -> None:
    """ProtectHome=true hid the linked repo and made systemd fail with 203/EXEC."""
    unit = (ROOT / "deploy" / "farejador-update.service").read_text()
    assert "ProtectHome=read-only" in unit
    assert "ProtectHome=true" not in unit
    assert "ExecStart=/opt/farejador/repo/deploy/update.sh" in unit
