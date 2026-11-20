# Filename: test_ignore.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest

from farejador.review.diff import DiffFile, FileStatus
from farejador.review.filters import check_ignored


def _file(path: str, **kwargs: object) -> DiffFile:
    return DiffFile(path=path, old_path=path, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("package-lock.json", "lockfile"),
        ("frontend/yarn.lock", "lockfile"),
        ("uv.lock", "lockfile"),
        ("go.sum", "lockfile"),
        (".env", "secret-bearing"),
        ("config/.env.production", "secret-bearing"),
        ("certs/server.pem", "secret-bearing"),
        ("keys/id_rsa", "secret-bearing"),
        ("static/app.min.js", "generated"),
        ("dist/bundle.js", "generated"),
        ("web/build/out.js", "generated"),
        ("proto/api_pb2.py", "generated"),
        ("node_modules/pkg/index.js", "vendored"),
        ("third_party/vendor/lib.go", "vendored"),
        ("assets/logo.PNG", "binary"),
        ("docs/manual.pdf", "binary"),
    ],
)
def test_default_ignore_reasons(path: str, reason: str) -> None:
    decision = check_ignored(_file(path))
    assert decision.ignored is True
    assert decision.reason == reason


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "README.md", ".env.example", "docs/environment.md", "lock.py", "distance.py"],
)
def test_regular_files_are_reviewed(path: str) -> None:
    assert check_ignored(_file(path)).ignored is False


def test_binary_flag_wins_even_with_a_text_extension() -> None:
    assert check_ignored(_file("data.txt", is_binary=True)).reason == "binary"


def test_deleted_files_are_ignored() -> None:
    assert check_ignored(_file("gone.py", status=FileStatus.DELETED)).reason == "deleted"


def test_custom_globs_apply_to_path_and_name() -> None:
    assert check_ignored(_file("src/a.snap"), ["*.snap"]).reason == "custom"
    assert check_ignored(_file("docs/api/x.md"), ["docs/**"]).reason == "custom"
    assert check_ignored(_file("src/a.py"), ["*.snap", "docs/**"]).ignored is False
