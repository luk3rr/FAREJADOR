# Filename: test_config.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import pytest

from farejador.config import ConfigError, Mode, Settings

SECRET_KEY = "sk-or-v1-supersecretvalue1234567890"
WEBHOOK_SECRET = "whsec-topsecret-value"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    key_file = tmp_path / "app.pem"
    key_file.write_text("dummy")
    for name in list(__import__("os").environ):
        if name.startswith("FAREJADOR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("FAREJADOR_GITHUB_APP_ID", "12345")
    monkeypatch.setenv("FAREJADOR_GITHUB_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setenv("FAREJADOR_OPENROUTER_API_KEY", SECRET_KEY)
    monkeypatch.setenv("FAREJADOR_MODEL", "some/model")
    return monkeypatch


def test_defaults_match_contract(env: pytest.MonkeyPatch) -> None:
    settings = Settings.load()
    assert settings.mode is Mode.POLLING
    assert settings.trigger_text is None  # derived from the App's name at startup
    assert settings.poll_interval_s == 60
    assert settings.workers == 2
    assert (settings.max_steps, settings.max_tokens) == (15, 200_000)
    assert (settings.max_seconds, settings.max_files) == (300, 40)
    assert settings.state_path == Path("/data/farejador.db")
    assert (settings.host, settings.port) == ("127.0.0.1", 8080)
    assert settings.ignore_globs == []
    assert settings.reasoning_effort is None


def test_missing_required_variable_names_it_only(env: pytest.MonkeyPatch) -> None:
    env.delenv("FAREJADOR_OPENROUTER_API_KEY")
    with pytest.raises(ConfigError) as info:
        Settings.load()
    assert "FAREJADOR_OPENROUTER_API_KEY is required" in str(info.value)


def test_invalid_value_error_does_not_echo_value(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_PORT", "not-a-number-" + SECRET_KEY)
    with pytest.raises(ConfigError) as info:
        Settings.load()
    assert "FAREJADOR_PORT" in str(info.value)
    assert SECRET_KEY not in str(info.value)


@pytest.mark.parametrize("mode", ["webhook", "both"])
def test_webhook_modes_require_secret(env: pytest.MonkeyPatch, mode: str) -> None:
    env.setenv("FAREJADOR_MODE", mode)
    with pytest.raises(ConfigError) as info:
        Settings.load()
    assert "FAREJADOR_WEBHOOK_SECRET is required" in str(info.value)

    env.setenv("FAREJADOR_WEBHOOK_SECRET", WEBHOOK_SECRET)
    assert Settings.load().mode == Mode(mode)


def test_polling_does_not_require_webhook_secret(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_MODE", "polling")
    assert Settings.load().webhook_secret is None


def test_unknown_mode_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_MODE", "carrier-pigeon")
    with pytest.raises(ConfigError, match="FAREJADOR_MODE"):
        Settings.load()


def test_private_key_must_be_a_file(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env.setenv("FAREJADOR_GITHUB_PRIVATE_KEY_PATH", str(tmp_path / "missing.pem"))
    with pytest.raises(ConfigError, match="FAREJADOR_GITHUB_PRIVATE_KEY_PATH"):
        Settings.load()


def test_ignore_globs_are_split_and_trimmed(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_IGNORE_GLOBS", " *.snap, docs/** ,, vendor/** ")
    assert Settings.load().ignore_globs == ["*.snap", "docs/**", "vendor/**"]


def test_log_level_is_normalised_and_validated(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_LOG_LEVEL", "debug")
    assert Settings.load().log_level == "DEBUG"
    env.setenv("FAREJADOR_LOG_LEVEL", "loud")
    with pytest.raises(ConfigError, match="FAREJADOR_LOG_LEVEL"):
        Settings.load()


def test_secrets_are_hidden_in_repr_and_listed_for_redaction(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_MODE", "both")
    env.setenv("FAREJADOR_WEBHOOK_SECRET", WEBHOOK_SECRET)
    settings = Settings.load()
    assert SECRET_KEY not in repr(settings)
    assert WEBHOOK_SECRET not in repr(settings)
    assert set(settings.secret_values()) == {SECRET_KEY, WEBHOOK_SECRET}


def test_trace_settings_have_safe_defaults(env: pytest.MonkeyPatch) -> None:
    settings = Settings.load()
    assert settings.trace_enabled is True
    assert settings.trace_path == Path("/data/trace.db")
    assert settings.trace_retention_days == 30
    assert settings.trace_max_item_chars == 20_000
    assert settings.trace_max_run_bytes == 2 * 1024 * 1024


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRACE_RETENTION_DAYS", "0"),
        ("TRACE_RETENTION_DAYS", "366"),
        ("TRACE_RETENTION_DAYS", "abc"),
        ("TRACE_MAX_ITEM_CHARS", "10"),
        ("TRACE_MAX_RUN_BYTES", "100"),
        ("TRACE_ENABLED", "maybe"),
    ],
)
def test_invalid_trace_settings_are_rejected_naming_the_variable(
    env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    env.setenv(f"FAREJADOR_{name}", value)
    with pytest.raises(ConfigError) as error:
        Settings.load()
    assert f"FAREJADOR_{name}" in str(error.value)


def test_trace_settings_can_be_changed(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_TRACE_ENABLED", "false")
    env.setenv("FAREJADOR_TRACE_RETENTION_DAYS", "90")
    env.setenv("FAREJADOR_TRACE_PATH", "/tmp/x.db")
    settings = Settings.load()
    assert (settings.trace_enabled, settings.trace_retention_days) == (False, 90)
    assert settings.trace_path == Path("/tmp/x.db")


def test_reasoning_effort_accepts_the_known_levels_only(env: pytest.MonkeyPatch) -> None:
    env.setenv("FAREJADOR_REASONING_EFFORT", "xhigh")
    assert Settings.load().reasoning_effort == "xhigh"
    env.setenv("FAREJADOR_REASONING_EFFORT", "max")
    with pytest.raises(Exception):  # noqa: B017  (the loader wraps validation errors)
        Settings.load()


@pytest.mark.parametrize(
    ("configured", "bot_login", "expected"),
    [
        (None, "farejadorr[bot]", "@farejadorr"),
        (None, "farejadorr", "@farejadorr"),
        (None, "  Meu-App[bot] ", "@Meu-App"),
        ("@ajuda", "farejadorr[bot]", "@ajuda"),
        (None, None, "@farejador"),
        (None, "", "@farejador"),
        (None, "[bot]", "@farejador"),
    ],
)
def test_the_trigger_is_the_apps_own_mention_unless_configured(
    configured: str | None, bot_login: str | None, expected: str
) -> None:
    from farejador.config import effective_trigger_text

    assert effective_trigger_text(configured, bot_login) == expected
