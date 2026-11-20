# Filename: conftest.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import pytest
from tests.gitrepo import make_repo

from farejador.tools import RepoTools


@pytest.fixture
def repo_tools(tmp_path: Path) -> RepoTools:
    root = tmp_path / "repo"
    make_repo(
        root,
        {
            "a.py": "def normalize(user):\n    return user.strip()\n",
            "b.py": "from a import normalize\nprint(normalize(' x '))\n",
        },
    )
    (tmp_path / "outside.txt").write_text("outside secret")
    return RepoTools(root)
