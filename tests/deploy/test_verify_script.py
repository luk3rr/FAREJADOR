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

# The fake curl answers according to "<method> <url> <code> [<body>]" lines of a table file:
# it prints the status code when asked for it (-w) and the body otherwise.
CURL_STUB = """#!/usr/bin/env bash
method="GET"; url=""; want_code=0
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -w) want_code=1; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
echo "curl $method $url" >> "$STUB_DIR/curl.log"
line="$(grep -F "$method $url " "$STUB_DIR/table" | head -n 1)"
if [ "$want_code" = 1 ]; then
  code="$(printf '%s' "$line" | awk '{print $3}')"
  echo -n "${code:-000}"
else
  printf '%s' "$line" | cut -d' ' -f4-
fi
"""

SECRET = "whsec-SENTINELVALUE"

GOOD = {
    "GET https://luk3rr.com/": "200",
    "GET https://hooks.luk3rr.com/": "404",
    "GET https://hooks.luk3rr.com/healthz": "404",
    "GET https://hooks.luk3rr.com/docs": "404",
    "POST https://hooks.luk3rr.com/webhook": "403",
    "POST https://hooks.luk3rr.com/anything": "403",
    "GET https://farejador.luk3rr.com/api/status": (
        '200 {"status":"ok","trace_available":true,"retention_days":30,"reviews":3}'
    ),
    "GET https://farejador.luk3rr.com/api/reviews?limit=1": '200 {"items":[],"next_cursor":null}',
    "GET https://farejador.luk3rr.com/api/reviews/999999999": '404 {"error":"not_found"}',
    "POST https://farejador.luk3rr.com/api/reviews": "403",
    "DELETE https://farejador.luk3rr.com/api/reviews/1": "403",
    "POST https://farejador.luk3rr.com/webhook": "403",
    "GET https://farejador.luk3rr.com/webhook": "404",
    "GET https://farejador.luk3rr.com/healthz": "404",
    "GET https://farejador.luk3rr.com/docs": "404",
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


API = "https://farejador.luk3rr.com"


@pytest.mark.parametrize(
    ("request_line", "wrong", "needle"),
    [
        (f"GET {API}/api/status", "500", "GET /api/status answers"),
        (f"GET {API}/api/reviews?limit=1", "502", "GET /api/reviews answers"),
        (f"GET {API}/api/reviews/999999999", "200", "an unknown review is a 404"),
        (f"POST {API}/api/reviews", "200", "a write on the API is refused"),
        (f"DELETE {API}/api/reviews/1", "204", "a delete on the API is refused"),
        (f"POST {API}/webhook", "200", "the webhook path is not reachable on the API host"),
        (f"GET {API}/webhook", "405", "the webhook path is not readable on the API host"),
        (f"GET {API}/healthz", "200", "the health path is not public on the API host"),
        (f"GET {API}/docs", "200", "anything outside /api/ is blocked"),
    ],
)
def test_each_api_exposure_is_reported_as_a_failure(
    tmp_path: Path, request_line: str, wrong: str, needle: str
) -> None:
    body = GOOD[request_line].partition(" ")[2]  # only the status code is wrong, not the body
    result = _run(tmp_path, {**GOOD, request_line: f"{wrong} {body}".strip()}, "external")
    assert result.returncode == 1
    failing = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
    assert len(failing) == 1 and needle in failing[0], result.stdout


@pytest.mark.parametrize("code", ["403", "405"])
def test_a_write_refused_by_the_waf_or_by_the_api_both_count(tmp_path: Path, code: str) -> None:
    table = {**GOOD, f"POST {API}/api/reviews": code, f"DELETE {API}/api/reviews/1": code}
    assert _run(tmp_path, table, "external").returncode == 0


def test_an_api_whose_trace_is_unavailable_fails_even_with_a_200(tmp_path: Path) -> None:
    table = {**GOOD, f"GET {API}/api/status": '200 {"status":"ok","trace_available":false}'}
    result = _run(tmp_path, table, "external")
    assert result.returncode == 1
    assert "says the trace is available: the answer does not contain" in result.stdout


def test_a_reviews_answer_that_is_not_a_list_fails(tmp_path: Path) -> None:
    table = {**GOOD, f"GET {API}/api/reviews?limit=1": '200 {"error":"trace_unavailable"}'}
    result = _run(tmp_path, table, "external")
    assert result.returncode == 1 and "is a JSON list" in result.stdout


def test_the_api_checks_can_be_skipped_explicitly(tmp_path: Path) -> None:
    only_hooks = {k: v for k, v in GOOD.items() if "farejador.luk3rr.com" not in k}
    result = _run(tmp_path, only_hooks, "external", extra={"FAREJADOR_API_URL": "none"})
    assert result.returncode == 0, result.stdout
    assert "SKIP  API checks" in result.stdout


def test_an_unreachable_api_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    only_hooks = {k: v for k, v in GOOD.items() if "farejador.luk3rr.com" not in k}
    result = _run(tmp_path, only_hooks, "external")
    assert result.returncode == 1
    assert "GET /api/status answers: got HTTP 000" in result.stdout


def test_the_api_address_can_be_changed(tmp_path: Path) -> None:
    moved = {
        key.replace("farejador.luk3rr.com", "api.example.org"): value for key, value in GOOD.items()
    }
    result = _run(
        tmp_path, moved, "external", extra={"FAREJADOR_API_URL": "https://api.example.org"}
    )
    assert result.returncode == 0, result.stdout


def test_the_server_mode_also_checks_the_trace_file() -> None:
    text = SCRIPT.read_text()
    assert "exec farejador test -s /data/trace.db" in text
    assert "the trace database exists in the data volume" in text
