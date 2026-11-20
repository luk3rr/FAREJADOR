# Filename: test_release_workflow.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Static checks of the release workflow (FR-1, FR-2, FR-15, NFR-1.1 to NFR-1.3)."""

import re
from typing import Any

import pytest
from tests.workflows import WORKFLOWS, load, run_text, steps, triggers

RELEASE = load("release.yml")
JOBS: dict[str, Any] = RELEASE["jobs"]


def _uses(job: dict[str, Any]) -> str:
    return " ".join(step.get("uses", "") for step in steps(job))


def test_it_runs_only_for_version_tags() -> None:
    on = triggers(RELEASE)
    assert on == {"push": {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}}
    assert "branches" not in on["push"]
    assert "pull_request" not in on


def test_there_is_no_permission_by_default_and_every_job_declares_its_own() -> None:
    assert RELEASE["permissions"] == {}
    for name, job in JOBS.items():
        assert isinstance(job.get("permissions"), dict), name
        assert job["permissions"].get("contents") == "read", name


def test_the_signing_permission_exists_only_in_the_sign_job() -> None:
    with_id_token = [name for name, job in JOBS.items() if "id-token" in job["permissions"]]
    assert with_id_token == ["sign"]
    assert JOBS["sign"]["permissions"]["id-token"] == "write"


def test_package_write_is_limited_to_the_jobs_that_publish_sign_or_promote() -> None:
    writers = {name for name, job in JOBS.items() if job["permissions"].get("packages") == "write"}
    assert writers == {"publish", "sign", "promote"}
    assert "packages" not in JOBS["verify"]["permissions"]


def test_the_jobs_run_in_a_fixed_order() -> None:
    assert "needs" not in JOBS["verify"]
    assert JOBS["publish"]["needs"] == "verify"
    assert JOBS["sign"]["needs"] == "publish"
    assert set(JOBS["promote"]["needs"]) == {"publish", "sign"}


def test_verify_runs_the_quality_gates_and_requires_the_tag_to_be_on_main() -> None:
    commands = run_text(JOBS["verify"])
    for expected in (
        "ruff check",
        "ruff format --check",
        "mypy src",
        "pytest",
        "--cov-fail-under=80",
    ):
        assert expected in commands
    assert "git merge-base --is-ancestor" in commands
    assert "origin/main" in commands
    checkout = steps(JOBS["verify"])[0]
    assert checkout["with"]["fetch-depth"] == 0


def test_publish_pushes_the_version_and_commit_tags_with_oci_labels() -> None:
    build = next(s for s in steps(JOBS["publish"]) if s.get("id") == "build")
    assert build["with"]["push"] is True
    tags = build["with"]["tags"]
    assert "${{ env.IMAGE }}:${{ steps.version.outputs.number }}" in tags
    assert "${{ env.IMAGE }}:sha-${{ steps.version.outputs.short }}" in tags
    assert ":stable" not in tags
    labels = build["with"]["labels"]
    for label in ("image.source", "image.revision", "image.version"):
        assert label in labels
    assert JOBS["publish"]["outputs"]["digest"] == "${{ steps.build.outputs.digest }}"
    assert RELEASE["env"]["IMAGE"] == "ghcr.io/luk3rr/farejador"


def test_the_image_is_signed_by_digest_and_never_by_a_movable_tag() -> None:
    sign = next(s for s in steps(JOBS["sign"]) if "cosign sign" in s.get("run", ""))
    assert 'cosign sign --yes "${IMAGE}@${DIGEST}"' in sign["run"]
    assert sign["env"]["DIGEST"] == "${{ needs.publish.outputs.digest }}"
    assert ":stable" not in sign["run"]


def test_only_the_promote_job_touches_the_stable_tag_and_it_needs_approval() -> None:
    for name, job in JOBS.items():
        mentions_stable = ":stable" in run_text(job) or "stable" in str(job.get("with", ""))
        assert mentions_stable is (name == "promote"), name
    assert JOBS["promote"]["environment"] == "production"
    for name in ("verify", "publish", "sign"):
        assert "environment" not in JOBS[name]


def test_promote_verifies_the_signature_before_moving_stable() -> None:
    steps_list = steps(JOBS["promote"])
    verify_index = next(i for i, s in enumerate(steps_list) if "cosign verify" in s.get("run", ""))
    move_index = next(
        i for i, s in enumerate(steps_list) if "imagetools create" in s.get("run", "")
    )
    assert verify_index < move_index
    verify = steps_list[verify_index]["run"]
    assert "--certificate-identity-regexp" in verify
    assert "release.yml@refs/tags/v" in verify
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in verify
    move = steps_list[move_index]
    assert (
        'docker buildx imagetools create --prefer-index=false --tag "${IMAGE}:stable" '
        '"${IMAGE}@${DIGEST}"'
    ) in move["run"]


def test_stable_must_keep_the_signed_digest_and_the_job_checks_it() -> None:
    """A re-wrapped manifest has a new digest that nobody signed (found in the first deploy)."""
    run = next(s for s in steps(JOBS["promote"]) if "imagetools create" in s.get("run", ""))["run"]
    assert "--prefer-index=false" in run
    assert "imagetools inspect" in run
    assert '= "${DIGEST}"' in run


def test_the_identity_regex_matches_the_certificate_of_a_real_release() -> None:
    verify = next(s for s in steps(JOBS["promote"]) if "cosign verify" in s.get("run", ""))["run"]
    pattern = re.search(r'--certificate-identity-regexp "([^"]+)"', verify)
    assert pattern is not None
    regex = pattern.group(1).replace("${REPOSITORY}", "luk3rr/FAREJADOR")
    good = "https://github.com/luk3rr/FAREJADOR/.github/workflows/release.yml@refs/tags/v1.2.3"
    assert re.fullmatch(regex, good)
    for bad in (
        "https://github.com/luk3rr/FAREJADOR/.github/workflows/ci.yml@refs/tags/v1.2.3",
        "https://github.com/evil/FAREJADOR/.github/workflows/release.yml@refs/tags/v1.2.3",
        "https://github.com/luk3rr/FAREJADOR/.github/workflows/release.yml@refs/heads/main",
        "https://github.com/luk3rr/FAREJADOR/.github/workflows/release.yml@refs/tags/v1.2.3-evil",
    ):
        assert not re.fullmatch(regex, bad), bad


def test_the_only_secret_used_is_the_automatic_github_token() -> None:
    text = (WORKFLOWS / "release.yml").read_text()
    assert set(re.findall(r"secrets\.([A-Za-z0-9_]+)", text)) == {"GITHUB_TOKEN"}


@pytest.mark.parametrize("job_name", ["verify", "publish", "sign", "promote"])
def test_run_scripts_never_interpolate_workflow_expressions(job_name: str) -> None:
    """Untrusted values must reach scripts through ``env``, never by ``${{ }}`` in ``run``."""
    for step in steps(JOBS[job_name]):
        assert "${{" not in step.get("run", ""), step.get("name", step.get("run"))


def test_actions_used_by_each_job_are_the_expected_ones() -> None:
    assert "docker/build-push-action" in _uses(JOBS["publish"])
    assert "sigstore/cosign-installer" in _uses(JOBS["sign"])
    assert "sigstore/cosign-installer" in _uses(JOBS["promote"])


def test_the_image_is_built_with_the_release_version_so_traces_can_tell_releases_apart() -> None:
    build = next(s for s in steps(JOBS["publish"]) if s.get("id") == "build")
    assert "APP_VERSION=${{ steps.version.outputs.number }}" in build["with"]["build-args"]
