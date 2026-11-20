# Filename: test_headers.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHON_FILES = sorted(p for folder in ("src", "tests") for p in (ROOT / folder).rglob("*.py"))
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"({MONTHS}) \d{{1,2}}, \d{{4}}"
AUTHOR = "# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>"


def test_python_files_were_found() -> None:
    assert PYTHON_FILES


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_file_starts_with_standard_header(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"# Filename: {path.name}"
    assert re.fullmatch(rf"# Created on: {DATE}", lines[1])
    assert lines[2] == AUTHOR
