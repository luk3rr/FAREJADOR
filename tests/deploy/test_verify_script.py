# Filename: test_verify_script.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The post-deploy checklist, run against a fake curl and local sockets (FR-14, NFR-3.2)."""

import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest
from tests.workflows import ROOT

SCRIPT = ROOT / "scripts" / "verify_deploy.sh"

# The fake curl answers according to "<method> <url>" lines of a table file.
CURL_STUB = """#!/usr/bin/env bash
method=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
echo "curl $method $url" >> "$STUB_DIR/curl.log"
code="$(grep -F "$method $url " "$STUB_DIR/table" | head -n 1 | awk '{print $3}')"
echo -n "${code:-000}"
"""

SECRET = "whsec-SENTINELVALUE"

GOOD = {
    "GET https://luk3rr.com/": "200",
    "GET https://hooks.luk3rr.com/": "404",
    "GET https://hooks.luk3rr.com/healthz": "404",
    "GET https://hooks.luk3rr.com/docs": "404",
    "POST https://hooks.luk3rr.com/webhook": "403",
    "POST https://hooks.luk3rr.com/anything": "403",
}


def _run(
    tmp_path: Path, table: dict[str, str], *args: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    curl = stubs / "curl"
    curl.write_text(CURL_STUB)
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    (stubs / "table").write_text("".join(f"{key} {code}\n" for key, code in table.items()))
    env = {
        "PATH": os.environ["PATH"],
        "STUB_DIR": str(stubs),
        "FAREJADOR_CURL": str(curl),
        "TUNNEL_TOKEN": "tunnel-SENTINELVALUE",
        "FAREJADOR_WEBHOOK_SECRET": SECRET,
        **(extra or {}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_a_correct_setup_passes_every_external_check(tmp_path: Path) -> None:
    result = _run(tmp_path, GOOD, "external", extra={"FAREJADOR_PORTS": "1"})
    assert result.returncode == 0, result.stdout
    assert "FAIL" not in result.stdout
    assert (
        "PASS  POST /webhook from a non-GitHub address is blocked by the WAF (HTTP 403)"
        in result.stdout
    )
    assert "SKIP  dashboard check" in result.stdout
    assert "SKIP  port scan" in result.stdout
    assert "All checks passed." in result.stdout


@pytest.mark.parametrize(
    ("request_line", "wrong_code", "needle"),
    [
        ("POST https://hooks.luk3rr.com/webhook", "200", "POST /webhook from a non-GitHub"),
        ("GET https://hooks.luk3rr.com/healthz", "200", "GET /healthz is not public"),
        ("GET https://hooks.luk3rr.com/docs", "200", "other paths are blocked"),
        ("GET https://luk3rr.com/", "500", "apex page still answers"),
        ("GET https://hooks.luk3rr.com/", "200", "root is blocked"),
    ],
)
def test_each_exposure_or_breakage_is_reported_as_a_failure(
    tmp_path: Path, request_line: str, wrong_code: str, needle: str
) -> None:
    table = {**GOOD, request_line: wrong_code}
    result = _run(tmp_path, table, "external")
    assert result.returncode == 1
    failing = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
    assert len(failing) == 1 and needle in failing[0]
    assert f"got HTTP {wrong_code}" in failing[0]


def test_an_unreachable_host_counts_as_a_failure_not_a_pass(tmp_path: Path) -> None:
    result = _run(tmp_path, {}, "external")
    assert result.returncode == 1
    assert "apex page still answers: got HTTP 000" in result.stdout


def test_the_dashboard_must_ask_for_login_when_configured(tmp_path: Path) -> None:
    table = {**GOOD, "GET https://farejador.luk3rr.com/": "200"}
    result = _run(
        tmp_path, table, "external", extra={"FAREJADOR_DASH_URL": "https://farejador.luk3rr.com"}
    )
    assert result.returncode == 1
    assert "dashboard asks for login" in result.stdout
    table["GET https://farejador.luk3rr.com/"] = "302"
    assert (
        _run(
            tmp_path,
            table,
            "external",
            extra={"FAREJADOR_DASH_URL": "https://farejador.luk3rr.com"},
        ).returncode
        == 0
    )


def test_an_open_port_on_the_server_is_a_failure_and_a_closed_one_passes(tmp_path: Path) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    open_port = listener.getsockname()[1]
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        result = _run(
            tmp_path,
            GOOD,
            "external",
            "127.0.0.1",
            extra={"FAREJADOR_PORTS": f"{closed_port} {open_port}"},
        )
    finally:
        listener.close()
    assert result.returncode == 1
    assert f"PASS  port {closed_port} is closed" in result.stdout
    assert f"FAIL  port {open_port} accepted a connection on 127.0.0.1" in result.stdout


def test_no_secret_is_ever_printed(tmp_path: Path) -> None:
    result = _run(tmp_path, GOOD, "external", extra={"FAREJADOR_PORTS": "1"})
    assert "SENTINELVALUE" not in result.stdout + result.stderr


def test_every_request_has_a_timeout_and_the_script_needs_no_secret() -> None:
    text = SCRIPT.read_text()
    assert "--max-time" in text
    assert "CURL_TIMEOUT=10" in text
    assert "SECRET" not in text and "TOKEN" not in text


def test_usage_error_exits_with_code_2(tmp_path: Path) -> None:
    result = _run(tmp_path, GOOD)
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_the_script_is_valid_bash_with_the_file_header() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    lines = SCRIPT.read_text().splitlines()
    assert lines[:2] == ["#!/usr/bin/env bash", "# Filename: verify_deploy.sh"]
    assert os.access(SCRIPT, os.X_OK)
