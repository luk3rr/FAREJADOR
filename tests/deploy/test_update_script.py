# Filename: test_update_script.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The updater, run against a fake docker and cosign (FR-3, FR-4, NFR-2, NFR-2.1 to NFR-2.3)."""

import fcntl
import os
from pathlib import Path

from tests.deploy.stubs import (
    DIGEST_A,
    DIGEST_B,
    DIGEST_C,
    UPDATE_SH,
    Sandbox,
    make_sandbox,
)

IMAGE = "ghcr.io/luk3rr/farejador"


def _cosign_calls(box: Sandbox) -> list[str]:
    return [call for call in box.calls if call.startswith("cosign ")]


def _compose_up_images(box: Sandbox) -> list[str]:
    return [call for call in box.calls if call.startswith("up with")]


def _bad(box: Sandbox) -> list[str]:
    path = box.state / "bad"
    return path.read_text().splitlines() if path.exists() else []


def test_a_new_signed_digest_is_installed_after_the_signature_is_verified(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)

    result = box.run()

    assert result.returncode == 0, result.stdout + result.stderr
    (verify,) = _cosign_calls(box)
    assert verify.startswith(f"cosign verify {IMAGE}@{DIGEST_B} ")
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in verify
    assert (
        "--certificate-identity-regexp "
        "^https://github.com/luk3rr/FAREJADOR/.github/workflows/release.yml"
        "@refs/tags/v[0-9]+\\.[0-9]+\\.[0-9]+$"
    ) in verify
    assert box.image_env.read_text() == f"FAREJADOR_IMAGE={IMAGE}@{DIGEST_B}\n"
    assert (box.state / "last_good").read_text().strip() == DIGEST_B
    assert _compose_up_images(box) == [f"up with FAREJADOR_IMAGE={IMAGE}@{DIGEST_B}"]
    # the signature is checked before anything is pulled or restarted
    verify_index = next(i for i, c in enumerate(box.calls) if c.startswith("cosign verify"))
    pull_index = next(i for i, c in enumerate(box.calls) if c.endswith(" pull"))
    assert verify_index < pull_index
    assert f"docker image rm {IMAGE}@{DIGEST_A}" in box.calls  # the old image is removed


def test_the_first_installation_works_without_a_current_version(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    result = box.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.image_env.read_text() == f"FAREJADOR_IMAGE={IMAGE}@{DIGEST_A}\n"
    assert (box.state / "last_good").read_text().strip() == DIGEST_A
    assert "now running" in result.stdout


def test_the_same_digest_does_nothing(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    result = box.run()
    assert result.returncode == 0
    assert "already running" in result.stdout
    assert _cosign_calls(box) == []
    assert not any("compose" in call for call in box.calls)


def test_an_image_without_a_valid_signature_is_refused_and_never_run(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.flag("cosign_fails")

    result = box.run()

    assert result.returncode == 1
    assert "signature verification failed" in result.stdout
    assert box.image_env.read_text() == f"FAREJADOR_IMAGE={IMAGE}@{DIGEST_A}\n"
    assert not any("compose" in call for call in box.calls)
    (entry,) = _bad(box)
    assert entry.startswith(f"{DIGEST_B} ") and entry.endswith(" invalid-signature")


def test_a_refused_digest_is_not_tried_again_until_a_new_one_appears(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.flag("cosign_fails")
    assert box.run().returncode == 1
    cosign_before = len(_cosign_calls(box))

    again = box.run()
    assert again.returncode == 0
    assert "skipping" in again.stdout
    assert len(_cosign_calls(box)) == cosign_before  # no second verification

    box.set_stable(DIGEST_C)
    (box.stub_dir / "cosign_fails").unlink()
    fresh = box.run()
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    assert box.image_env.read_text().strip().endswith(DIGEST_C)


def test_an_unhealthy_update_is_rolled_back_to_the_last_healthy_digest(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.health("starting", "unhealthy", "healthy")  # the new one fails, the old one is healthy

    result = box.run()

    assert result.returncode == 1
    assert "rolling back" in result.stdout
    assert box.image_env.read_text() == f"FAREJADOR_IMAGE={IMAGE}@{DIGEST_A}\n"
    assert _compose_up_images(box) == [
        f"up with FAREJADOR_IMAGE={IMAGE}@{DIGEST_B}",
        f"up with FAREJADOR_IMAGE={IMAGE}@{DIGEST_A}",
    ]
    assert (box.state / "last_good").read_text().strip() == DIGEST_A
    (entry,) = _bad(box)
    assert entry.startswith(f"{DIGEST_B} ") and entry.endswith(" unhealthy")


def test_a_version_that_never_becomes_healthy_times_out_and_is_rolled_back(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.health(*(["starting"] * 4), default="healthy")  # 20 s / 5 s = 4 attempts, all "starting"

    result = box.run()

    assert result.returncode == 1
    assert "did not become healthy within 20s" in result.stdout
    assert box.image_env.read_text().strip().endswith(DIGEST_A)


def test_the_rollback_does_not_loop_on_the_same_bad_digest(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.health("unhealthy", "healthy")
    assert box.run().returncode == 1
    ups = len(_compose_up_images(box))

    box.health(default="healthy")
    second = box.run()
    assert second.returncode == 0
    assert len(_compose_up_images(box)) == ups
    assert box.image_env.read_text().strip().endswith(DIGEST_A)


def test_a_failed_first_installation_stops_the_service_and_leaves_no_image(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.health("unhealthy")
    result = box.run()
    assert result.returncode == 1
    assert any(call.endswith(" stop") for call in box.calls)
    assert "stopping the service" in result.stdout
    assert [e.split()[0] for e in _bad(box)] == [DIGEST_A]


def test_a_failing_compose_up_is_also_rolled_back(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.flag("up_fails_once")
    result = box.run()
    assert result.returncode == 1
    assert "docker compose up failed" in result.stdout
    assert box.image_env.read_text().strip().endswith(DIGEST_A)
    assert _bad(box)[0].endswith(" compose-failed")


def test_a_failed_pull_restores_the_previous_version_and_refuses_the_digest(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.flag("pull_fails")
    result = box.run()
    assert result.returncode == 1
    assert box.image_env.read_text().strip().endswith(DIGEST_A)
    assert not _compose_up_images(box)
    assert _bad(box)[0].endswith(" pull-failed")


def test_garbage_from_the_registry_is_never_used(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    for garbage in (
        "not-a-digest",
        "sha256:short",
        "sha256:" + "g" * 64,
        "sha256:" + "a" * 64 + "; rm -rf /",
    ):
        (box.stub_dir / "stable_digest").write_text(garbage + "\n")
        result = box.run()
        assert result.returncode == 1, garbage
        assert "not a digest" in result.stdout
    assert _cosign_calls(box) == []
    assert box.image_env.read_text().strip().endswith(DIGEST_A)


def test_an_unreachable_registry_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.flag("registry_down")
    result = box.run()
    assert result.returncode == 0
    assert "could not read the digest" in result.stdout
    assert box.image_env.read_text().strip().endswith(DIGEST_A)


def test_check_mode_reports_without_changing_anything(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    result = box.run("--check")
    assert result.returncode == 0
    assert f"update available: {DIGEST_B} (running: {DIGEST_A})" in result.stdout
    assert _cosign_calls(box) == []
    assert box.image_env.read_text().strip().endswith(DIGEST_A)


def test_only_one_update_runs_at_a_time(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    box.state.mkdir(parents=True, exist_ok=True)
    with (box.state / "lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = box.run()
    assert result.returncode == 0
    assert "another update is already running" in result.stdout
    assert box.calls == []


def test_missing_tools_exit_with_code_2(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    result = box.run(
        path=f"{empty}:/usr/bin:/bin", extra_env={"FAREJADOR_COSIGN": "cosign-not-installed"}
    )
    assert result.returncode == 2
    assert "required tool not found: cosign-not-installed" in result.stdout


def test_secrets_never_appear_in_the_output_and_the_state_is_private(tmp_path: Path) -> None:
    box = make_sandbox(tmp_path)
    box.write_current(DIGEST_A, last_good=DIGEST_A)
    box.set_stable(DIGEST_B)
    secrets_dir = box.home / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "farejador.env").write_text("FAREJADOR_OPENROUTER_API_KEY=sk-or-SENTINELVALUE\n")
    sentinel_env = {
        "TUNNEL_TOKEN": "tunnel-SENTINELVALUE",
        "FAREJADOR_WEBHOOK_SECRET": "whsec-SENTINELVALUE",
    }

    result = box.run(extra_env=sentinel_env)

    assert result.returncode == 0
    combined = result.stdout + result.stderr + "\n".join(box.calls)
    assert "SENTINELVALUE" not in combined
    assert oct(box.state.stat().st_mode & 0o777) == "0o700"
    for name in ("last_good", "lock"):
        assert (box.state / name).stat().st_mode & 0o077 == 0, name


def test_the_script_has_the_safety_properties_required_by_the_design() -> None:
    text = UPDATE_SH.read_text()
    assert "set -euo pipefail" in text
    assert "flock -n 9" in text
    for setting in (
        "NET_TIMEOUT:-30",
        "VERIFY_TIMEOUT:-60",
        "PULL_TIMEOUT:-300",
        "HEALTH_TIMEOUT:-120",
    ):
        assert setting in text
    assert text.count("timeout ") >= 3
    assert "eval " not in text
    assert "curl" not in text
    assert os.access(UPDATE_SH, os.X_OK)
    lines = text.splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "# Filename: update.sh"
    assert lines[3] == "# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>"
