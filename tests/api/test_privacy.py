# Filename: test_privacy.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A private repository never shows through the API, not even by name (FR-11, NFR-2, M-011)."""

import re
from pathlib import Path
from typing import Any

import pytest
from tests.api_env import PRIVATE_REPO, SECRET_CODE, api_client, make_run, seed

from farejador.trace import queries
from farejador.trace.store import TraceStore, open_readonly

ALL_FILTER_COMBINATIONS: list[dict[str, Any]] = [
    {},
    {"limit": 50},
    {"outcome": "complete"},
    {"outcome": "partial"},
    {"outcome": "failed"},
    {"pr": 5},
    {"pr": 6},
    {"since": "2000-01-01T00:00:00Z"},
    {"until": "2100-01-01T00:00:00Z"},
]


def _leaks(text: str) -> bool:
    return PRIVATE_REPO in text or SECRET_CODE in text or "x/unknown" in text


async def test_no_listing_ever_includes_a_private_or_unknown_run(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    forbidden = set(seeded.private_ids + seeded.unknown_ids)
    async with api_client(seeded.path) as client:
        for params in ALL_FILTER_COMBINATIONS:
            response = await client.get("/reviews", params=params)
            assert response.status_code == 200
            assert not forbidden & {item["id"] for item in response.json()["items"]}, params
            assert not _leaks(response.text), params


async def test_filtering_by_the_name_of_a_private_repository_finds_nothing(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        for repo in (PRIVATE_REPO, "x/unknown"):
            body = (await client.get("/reviews", params={"repo": repo})).json()
            assert body == {"items": [], "next_cursor": None}
        # a name that merely resembles a private one matches nothing either (exact comparison)
        body = (await client.get("/reviews", params={"repo": "acme/secret_project"})).json()
        assert body["items"] == []


async def test_every_private_id_answers_exactly_like_one_that_does_not_exist(
    tmp_path: Path,
) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        for run_id in range(1, 40):
            response = await client.get(f"/reviews/{run_id}")
            if run_id in seeded.public_ids:
                assert response.status_code == 200
                assert not _leaks(response.text)
            else:
                assert (response.status_code, response.text) == (404, '{"error":"not_found"}')


async def test_the_status_never_counts_or_names_private_runs(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        response = await client.get("/status")
    assert response.json()["reviews"] == len(seeded.public_ids)
    assert not _leaks(response.text)


async def test_a_repository_that_turns_private_disappears_after_its_next_review(
    tmp_path: Path,
) -> None:
    store = TraceStore(tmp_path / "trace.db").open()
    first = make_run(store, repo="o/r", public=True, key="a")
    async with api_client(tmp_path / "trace.db") as client:
        assert (await client.get(f"/reviews/{first}")).status_code == 200
        make_run(store, repo="o/r", public=False, key="b")  # the repository became private
        assert (await client.get(f"/reviews/{first}")).status_code == 404
        assert (await client.get("/reviews")).json()["items"] == []


async def test_a_run_whose_visibility_was_never_recorded_is_private(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.db").open()
    run_id = make_run(store, repo="o/r", public=None, key="a")
    async with api_client(tmp_path / "trace.db") as client:
        assert (await client.get(f"/reviews/{run_id}")).status_code == 404
        assert (await client.get("/reviews")).json()["items"] == []


def test_every_statement_that_reads_runs_carries_the_privacy_condition() -> None:
    """If someone adds a query on trace_run without the condition, this test fails (FN-10)."""
    source = Path(queries.__file__).read_text()
    statements = [m.start() for m in re.finditer(r"FROM trace_run", source)]
    assert len(statements) >= 3
    for start in statements:
        window = source[max(0, start - 900) : start + 250]
        assert "PUBLIC" in window or "{PUBLIC}" in window, source[start - 80 : start + 120]
    assert queries.PUBLIC == "r.repo_public = 1"


def test_the_privacy_condition_is_not_defined_anywhere_else() -> None:
    root = Path(queries.__file__).parent.parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        # store.py has it in the write-side downgrade rule (FN-11), which is not a read
        if "repo_public = 1" in path.read_text() and path.name not in ("queries.py", "store.py")
    ]
    assert offenders == []


@pytest.mark.parametrize("public", [None, False])
async def test_a_private_run_with_a_secret_looking_name_cannot_be_found_by_probing(
    tmp_path: Path, public: bool | None
) -> None:
    store = TraceStore(tmp_path / "trace.db").open()
    make_run(store, repo="corp/launch-codes", public=public, key="a")
    async with api_client(tmp_path / "trace.db") as client:
        for params in ({"repo": "corp/launch-codes"}, {"pr": 1}, {}):
            body = (await client.get("/reviews", params=params)).json()
            assert body["items"] == []
        assert "launch-codes" not in (await client.get("/reviews/1")).text


async def test_internal_error_texts_are_not_public_but_the_safe_ones_are(tmp_path: Path) -> None:
    from farejador.trace.store import RunOutcome

    store = TraceStore(tmp_path / "trace.db").open()
    texts = {
        "github_api": "GitHub API error 403: Resource not accessible by integration",
        "internal": "could not sign the GitHub App JWT; check the private key /run/secrets/x.pem",
        "model_api": "model API returned HTTP 429",
        "invalid_output": "the model did not call a tool to finish",
        "budget": "Revisão interrompida antes do fim: limite de passos atingido.",
    }
    ids = {
        category: make_run(
            store,
            repo="o/r",
            public=True,
            pr=number,
            key=category,
            outcome=RunOutcome.FAILED,
            error=(category, message),
        )
        for number, (category, message) in enumerate(texts.items(), start=1)
    }
    async with api_client(tmp_path / "trace.db") as client:
        shown = {c: (await client.get(f"/reviews/{i}")).json()["error"] for c, i in ids.items()}
    for category in ("model_api", "invalid_output", "budget"):
        assert shown[category] == {"category": category, "message": texts[category]}
    for category in ("github_api", "internal"):
        assert shown[category] == {"category": category, "message": "detalhes omitidos"}
    # the full text is still kept for the maintainer
    kept = (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT error_message FROM trace_run WHERE error_category = 'internal'")
        .fetchone()[0]
    )
    assert "check the private key" in kept
