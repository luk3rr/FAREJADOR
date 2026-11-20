# Filename: test_cli.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import urllib.error
from pathlib import Path
from typing import Any

import pytest

from farejador import __version__
from farejador.cli import EXIT_CONFIG, EXIT_ERROR, EXIT_OK, main
from farejador.config import Settings
from farejador.github.errors import AuthError, GitHubApiError


class FakeRuntime:
    def __init__(self) -> None:
        self.ran = False

    async def run(self, stop: Any) -> None:
        self.ran = True


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == __version__


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2


def test_unknown_modes_are_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit) as info:
        main(["run", "--mode", "carrier-pigeon"])
    assert info.value.code == 2


def test_check_config_accepts_a_valid_setup_without_printing_secrets(
    farejador_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check-config"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Configuration OK (mode=polling, model=test/model)" in out
    assert "sk-or" not in out
    assert "whsec" not in out


def test_check_config_reports_the_missing_variable_by_name_only(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("FAREJADOR_MODEL")
    assert main(["check-config"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "FAREJADOR_MODEL is required" in err
    assert "sk-or" not in err


def test_the_mode_flag_overrides_the_environment_and_is_validated(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("FAREJADOR_WEBHOOK_SECRET")
    runtime = FakeRuntime()

    async def builder(settings: Settings) -> FakeRuntime:
        assert settings.mode.value == "polling"
        return runtime

    assert main(["run", "--mode", "polling"], builder=builder) == EXIT_OK  # type: ignore[arg-type]
    assert runtime.ran is True

    assert main(["run", "--mode", "webhook"], builder=builder) == EXIT_CONFIG  # type: ignore[arg-type]
    assert "FAREJADOR_WEBHOOK_SECRET is required" in capsys.readouterr().err


def test_run_builds_the_runtime_and_runs_it(farejador_env: Path) -> None:
    runtime = FakeRuntime()
    seen: list[Settings] = []

    async def builder(settings: Settings) -> FakeRuntime:
        seen.append(settings)
        return runtime

    assert main(["run"], builder=builder) == EXIT_OK  # type: ignore[arg-type]
    assert runtime.ran is True
    assert seen[0].model == "test/model"


@pytest.mark.parametrize(
    "error",
    [GitHubApiError(401, "bad credentials"), AuthError("could not sign the JWT"), OSError("x")],
)
def test_startup_failures_exit_with_a_short_message(
    farejador_env: Path, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    async def builder(_settings: Settings) -> FakeRuntime:
        raise error

    assert main(["run"], builder=builder) == EXIT_ERROR  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert err.startswith("Could not start:")
    assert "Traceback" not in err


# -- healthcheck -----------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def test_the_healthcheck_of_the_polling_mode_has_nothing_to_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAREJADOR_MODE", "polling")
    assert main(["healthcheck"]) == EXIT_OK


def test_the_healthcheck_defaults_to_polling_when_the_mode_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAREJADOR_MODE", raising=False)
    assert main(["healthcheck"]) == EXIT_OK


@pytest.mark.parametrize(("status", "code"), [(200, EXIT_OK), (503, EXIT_ERROR)])
def test_the_webhook_healthcheck_probes_healthz_on_the_configured_port(
    monkeypatch: pytest.MonkeyPatch, status: int, code: int
) -> None:
    monkeypatch.setenv("FAREJADOR_MODE", "webhook")
    monkeypatch.setenv("FAREJADOR_PORT", "9123")
    urls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        urls.append(url)
        return _Response(status)

    monkeypatch.setattr("farejador.cli.urllib.request.urlopen", fake_urlopen)
    assert main(["healthcheck"]) == code
    assert urls == ["http://127.0.0.1:9123/healthz"]


@pytest.mark.parametrize("error", [urllib.error.URLError("refused"), TimeoutError(), ValueError()])
def test_the_webhook_healthcheck_fails_when_the_server_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setenv("FAREJADOR_MODE", "both")

    def fake_urlopen(url: str, timeout: float) -> _Response:
        raise error

    monkeypatch.setattr("farejador.cli.urllib.request.urlopen", fake_urlopen)
    assert main(["healthcheck"]) == EXIT_ERROR
