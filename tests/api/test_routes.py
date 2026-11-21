# Filename: test_routes.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The read-only API: lists, detail, errors, headers (FR-9 to FR-12, FR-15, NFR-7, NFR-8)."""

import json
from pathlib import Path
from typing import Any

import pytest
from tests.api_env import api_client, make_run, seed
from tests.trace.helpers import Clock

from farejador.trace.store import RunOutcome, TraceStore

SUMMARY_KEYS = {
    "id",
    "repo",
    "pr_number",
    "head_sha",
    "kind",
    "model",
    "prompt_version",
    "app_version",
    "outcome",
    "step_count",
    "tokens",
    "duration_s",
    "findings_inline",
    "findings_summary",
    "findings_dropped",
    "error_category",
    "started_at",
}


async def test_the_list_has_only_public_runs_newest_first_with_the_contract_fields(
    tmp_path: Path,
) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.get("/reviews")
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == sorted(seeded.public_ids, reverse=True)
    assert body["next_cursor"] is None
    assert set(body["items"][0]) == SUMMARY_KEYS
    assert "repo_public" not in response.text and "trigger_key" not in response.text


async def test_the_summary_counts_the_destination_of_each_finding(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        item = (await client.get("/reviews", params={"pr": 1, "repo": "o/r"})).json()["items"][0]
    assert (item["findings_inline"], item["findings_summary"], item["findings_dropped"]) == (
        1,
        1,
        1,
    )
    assert item["step_count"] == 2 and item["outcome"] == "complete"


async def test_pagination_walks_every_run_once(tmp_path: Path) -> None:
    clock = Clock()
    store = TraceStore(tmp_path / "trace.db", clock=clock).open()
    ids = [make_run(store, repo="o/r", public=True, pr=n + 1, key=f"k{n}") for n in range(25)]
    async with api_client(tmp_path / "trace.db") as client:
        seen: list[int] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"limit": 10}
            if cursor:
                params["cursor"] = cursor
            body = (await client.get("/reviews", params=params)).json()
            seen += [item["id"] for item in body["items"]]
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
    assert pages == 3
    assert seen == sorted(ids, reverse=True)


async def test_the_filters_narrow_the_list(tmp_path: Path) -> None:
    clock = Clock()
    seeded = seed(tmp_path, clock)
    async with api_client(seeded.path) as client:

        async def ids(**params: Any) -> list[int]:
            return [i["id"] for i in (await client.get("/reviews", params=params)).json()["items"]]

        assert len(await ids(repo="o/r")) == 2
        assert len(await ids(repo="o/other")) == 1
        assert len(await ids(repo="o/r", pr=2)) == 1
        assert len(await ids(outcome="failed")) == 1
        assert len(await ids(outcome="complete")) == 1
        assert len(await ids(outcome="partial")) == 1
        assert await ids(repo="nobody/nothing") == []
        everything = (await client.get("/reviews")).json()["items"]
        newest = max(item["started_at"] for item in everything)
        oldest = min(item["started_at"] for item in everything)
        assert len(await ids(since=newest)) == 1
        assert len(await ids(until=oldest)) == 1
        assert len(await ids(since=oldest, until=newest)) == 3
        assert await ids(since="2099-01-01T00:00:00Z") == []


async def test_runs_still_running_or_left_incomplete_are_listed_as_partial(
    tmp_path: Path,
) -> None:
    store = TraceStore(tmp_path / "trace.db").open()
    running = store.begin_run(
        trigger_key="r",
        kind="review",
        repo="o/r",
        pr_number=1,
        head_sha=None,
        repo_public=True,
        model="m",
        prompt_version="p",
        app_version="v",
        budgets={},
    )
    incomplete = make_run(
        store, repo="o/r", public=True, pr=2, key="i", outcome=RunOutcome.INCOMPLETE
    )
    async with api_client(tmp_path / "trace.db") as client:
        items = (await client.get("/reviews", params={"outcome": "partial"})).json()["items"]
    assert sorted(i["id"] for i in items) == sorted([running, incomplete])
    assert {i["outcome"] for i in items} == {"partial"}


async def test_the_detail_has_steps_tools_findings_budgets_and_the_error(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    ok, failed, partial = seeded.public_ids
    async with api_client(seeded.path) as client:
        detail = (await client.get(f"/reviews/{ok}")).json()
        broken = (await client.get(f"/reviews/{failed}")).json()
        budget = (await client.get(f"/reviews/{partial}")).json()

    assert detail["budgets"]["max_steps"] == 15 and detail["error"] is None
    assert detail["truncated"] is False
    first, second = detail["steps"]
    assert (first["index"], second["index"]) == (0, 1)
    assert first["input_messages"] == [
        {"role": "user", "content": "conteúdo 0", "tool_call_id": None}
    ]
    assert first["response"] == {
        "content": "vou ler",
        "reasoning": "pensando no diff",
        "tool_calls": [{"id": "c0", "name": "read_file", "arguments": '{"path": "a.py"}'}],
    }
    assert second["input_messages"] == [] and second["response"]["reasoning"] is None
    assert first["tool_results"][0] == {
        "call_id": "c0",
        "name": "read_file",
        "duration_s": 0.01,
        "content": "corpo conteúdo",
        "truncated": False,
        "original_chars": len("corpo conteúdo"),
    }
    assert [(f["disposition"], f["reason"]) for f in detail["findings"]] == [
        ("inline", None),
        ("summary", "line_not_added"),
        ("dropped", "duplicate"),
    ]
    assert broken["error"] == {"category": "model_api", "message": "model API returned HTTP 429"}
    assert broken["steps"] == [] and broken["outcome"] == "failed"
    assert budget["error"]["category"] == "budget" and budget["outcome"] == "partial"


async def test_the_status_counts_only_public_runs(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path, retention_days=45) as client:
        body = (await client.get("/status")).json()
    assert body["status"] == "ok" and body["trace_available"] is True
    assert (body["retention_days"], body["reviews"]) == (45, 3)


@pytest.mark.parametrize("path", ["/reviews", "/reviews/1", "/status"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def test_only_reads_are_allowed_and_nothing_changes(
    tmp_path: Path, path: str, method: str
) -> None:
    seeded = seed(tmp_path)
    before = seeded.store.count_runs()
    async with api_client(seeded.path) as client:
        response = await client.request(method, path)
    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed"}
    assert response.headers["allow"] == "GET, HEAD"
    assert seeded.store.count_runs() == before


async def test_head_is_supported_and_has_no_body(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.head("/reviews")
    assert response.status_code == 200 and response.content == b""


async def test_nonexistent_private_and_unknown_runs_are_indistinguishable(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        responses = [
            await client.get(f"/reviews/{run_id}")
            for run_id in (9999, seeded.private_ids[0], seeded.unknown_ids[0])
        ]
    assert {r.status_code for r in responses} == {404}
    assert {r.text for r in responses} == {'{"error":"not_found"}'}

    def stable(response: Any) -> dict[str, str]:
        return {k: v for k, v in response.headers.items() if k not in ("content-length", "date")}

    assert all(stable(r) == stable(responses[0]) for r in responses)


async def test_every_response_has_json_security_headers_and_no_cors(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        ok = await client.get("/reviews")
        missing = await client.get("/reviews/9999")
        bad = await client.get("/reviews", params={"limit": 0})
        unknown_path = await client.get("/nothing-here")
        wrong_method = await client.post("/reviews")
    for response in (ok, missing, bad, unknown_path, wrong_method):
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "access-control-allow-origin" not in response.headers
    assert ok.headers["cache-control"] == "public, max-age=30"
    for response in (missing, bad, unknown_path, wrong_method):
        assert response.headers["cache-control"] == "no-store"
    assert unknown_path.status_code == 404 and unknown_path.json() == {"error": "not_found"}


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/reviews", {"limit": 0}, "limit"),
        ("/reviews", {"limit": 51}, "limit"),
        ("/reviews", {"limit": -3}, "limit"),
        ("/reviews", {"limit": "many"}, "limit"),
        ("/reviews", {"pr": 0}, "pr"),
        ("/reviews", {"pr": "x"}, "pr"),
        ("/reviews", {"pr": 2**40}, "pr"),
        ("/reviews", {"repo": "no-slash"}, "repo"),
        ("/reviews", {"repo": "../../etc/passwd"}, "repo"),
        ("/reviews", {"repo": "o/r' OR '1'='1"}, "repo"),
        ("/reviews", {"repo": "o/r; DROP TABLE trace_run"}, "repo"),
        ("/reviews", {"outcome": "bogus"}, "outcome"),
        ("/reviews", {"since": "yesterday"}, "since"),
        ("/reviews", {"until": "2026-13-45"}, "until"),
        ("/reviews", {"cursor": "!!!"}, "cursor"),
        ("/reviews", {"cursor": "Zm9v"}, "cursor"),  # base64 of "foo"
        ("/reviews", {"cursor": "MA"}, "cursor"),  # "0"
        ("/reviews", {"cursor": "x" * 100}, "cursor"),
        ("/reviews/abc", {}, "review_id"),
        ("/reviews/0", {}, "review_id"),
        ("/reviews/-1", {}, "review_id"),
        ("/reviews/99999999999999999999999", {}, "review_id"),
    ],
)
async def test_invalid_parameters_get_a_422_that_names_the_field_and_never_echoes_it(
    tmp_path: Path, path: str, params: dict[str, Any], field: str
) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.get(path, params=params)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_parameter"
    assert field in [item["field"] for item in body["detail"]]
    for value in params.values():
        assert str(value) not in response.text or len(str(value)) < 3


async def test_since_after_until_is_rejected(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.get(
            "/reviews", params={"since": "2026-12-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"}
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["field"] == "since"


async def test_a_date_without_a_zone_is_read_as_utc(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        naive = await client.get("/reviews", params={"since": "2020-01-01T00:00:00"})
        zoned = await client.get("/reviews", params={"since": "2020-01-01T00:00:00Z"})
    assert naive.json() == zoned.json()


async def test_a_missing_trace_file_is_a_503_not_a_crash(tmp_path: Path) -> None:
    async with api_client(tmp_path / "absent.db") as client:
        for path in ("/reviews", "/reviews/1", "/status"):
            response = await client.get(path)
            assert response.status_code == 503
            assert response.json() == {"error": "trace_unavailable"}
            assert response.headers["cache-control"] == "no-store"


async def test_a_corrupted_trace_file_is_a_503(tmp_path: Path) -> None:
    broken = tmp_path / "trace.db"
    broken.write_bytes(b"this is not a sqlite database" * 50)
    async with api_client(broken) as client:
        assert (await client.get("/reviews")).status_code == 503


async def test_a_query_that_runs_too_long_is_interrupted_with_a_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = seed(tmp_path)

    def interrupt_at_once(conn: Any, seconds: float = 0) -> None:
        conn.set_progress_handler(lambda: 1, 1)

    monkeypatch.setattr("farejador.api.routes.queries.with_deadline", interrupt_at_once)
    async with api_client(seeded.path) as client:
        response = await client.get("/reviews")
    assert response.status_code == 503 and response.json() == {"error": "trace_unavailable"}


async def test_the_openapi_schema_describes_exactly_the_four_routes(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.get("/openapi.json")
    schema = response.json()
    assert set(schema["paths"]) == {"/reviews", "/reviews/{review_id}", "/stats", "/status"}
    assert {m for p in schema["paths"].values() for m in p} == {"get"}  # HEAD is implied
    assert json.dumps(schema)  # serializable


async def test_the_status_tells_which_release_is_running_and_since_when(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    started = datetime(2026, 11, 21, 0, 45, 12, tzinfo=UTC)
    async with api_client(
        seed(tmp_path).path, app_version="0.3.1", clock=lambda: started
    ) as client:
        first = (await client.get("/status")).json()
        second = (await client.get("/status")).json()
    assert first["app_version"] == "0.3.1"
    assert first["started_at"] == "2026-11-21T00:45:12Z"
    assert second["started_at"] == first["started_at"], "fixed when the service starts"
