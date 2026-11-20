# Filename: test_log.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import io
import json
import logging

import pytest

from farejador.log import REDACTED, JsonFormatter, Redactor, configure_logging, log_run

SENTINEL = "sentinel-secret-value-123"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123\n-----END RSA PRIVATE KEY-----"


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def logger(stream: io.StringIO) -> logging.Logger:
    configure_logging("INFO", secrets=[SENTINEL], stream=stream)
    return logging.getLogger("farejador.test")


def _emit(stream: io.StringIO) -> dict[str, object]:
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 1
    parsed: dict[str, object] = json.loads(lines[0])
    return parsed


def test_log_run_emits_required_fields(logger: logging.Logger, stream: io.StringIO) -> None:
    log_run(
        logger,
        repo="o/r",
        pr=7,
        sha="abc1234",
        mode="polling",
        steps=3,
        tokens=1200,
        duration_s=1.23456,
        findings=2,
        outcome="done",
    )
    record = _emit(stream)
    assert record["message"] == "review_run"
    for field in ("pr", "sha", "mode", "steps", "tokens", "duration_s", "findings", "outcome"):
        assert field in record
    assert record["duration_s"] == 1.235


def test_known_secrets_are_redacted_in_message_and_extras(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("token is %s", SENTINEL, extra={"detail": f"x {SENTINEL} y", "n": 1})
    record = _emit(stream)
    assert SENTINEL not in json.dumps(record)
    assert REDACTED in str(record["message"])
    assert record["n"] == 1


def test_exception_text_is_redacted(logger: logging.Logger, stream: io.StringIO) -> None:
    try:
        raise RuntimeError(f"boom {SENTINEL}")
    except RuntimeError:
        logger.exception("failed")
    record = _emit(stream)
    assert SENTINEL not in json.dumps(record)
    assert "exc" in record


@pytest.mark.parametrize(
    "text",
    [
        PEM,
        "ghp_" + "a" * 36,
        "github_pat_" + "B" * 30,
        "sk-or-v1-" + "c" * 20,
        "Authorization: Bearer abcdefghijklmnop",
        "https://x-access-token:ghs_secretsecretsecret@github.com/o/r.git",
    ],
)
def test_credential_patterns_are_redacted(text: str) -> None:
    redacted = Redactor().redact(f"before {text} after")
    assert REDACTED in redacted
    assert "abcdefghijklmnop" not in redacted
    assert "MIIEabc123" not in redacted
    assert "secretsecret" not in redacted


def test_short_secrets_are_ignored_to_avoid_mangling_text() -> None:
    assert Redactor(["ab"]).redact("abab") == "abab"


def test_nested_values_are_redacted() -> None:
    value = Redactor([SENTINEL]).redact_value({"a": [SENTINEL, {"b": SENTINEL}], "c": 5})
    assert SENTINEL not in json.dumps(value)
    assert value["c"] == 5


def test_configure_logging_is_idempotent(stream: io.StringIO) -> None:
    configure_logging("INFO", stream=stream)
    configure_logging("INFO", stream=stream)
    logging.getLogger("farejador.test").info("once")
    assert len(stream.getvalue().strip().splitlines()) == 1


def test_configure_logging_defaults_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("farejador.test").info("to stdout")
    assert "to stdout" in capsys.readouterr().out


def test_formatter_handles_non_serialisable_extras() -> None:
    record = logging.LogRecord("n", logging.INFO, __file__, 1, "m", None, None)
    record.thing = object()
    assert "thing" in json.loads(JsonFormatter(Redactor()).format(record))


def test_log_calls_never_use_reserved_logrecord_names_in_extra() -> None:
    """``extra={"thread": ...}`` raises KeyError at runtime; catch such names statically."""
    import ast
    from pathlib import Path

    reserved = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
    offenders: list[str] = []
    for source in sorted(Path(__file__).resolve().parent.parent.joinpath("src").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and key.value in reserved:
                        offenders.append(f"{source.name}:{node.lineno} uses {key.value!r}")
    assert offenders == []
