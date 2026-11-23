# Filename: test_docs.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The dashboard guide only cites paths and commands that exist (NFR-8)."""

import json
import re

from tests.workflows import ROOT

GUIDE = ROOT / "docs" / "painel.md"


def test_the_guide_exists_and_the_readme_links_to_it() -> None:
    assert GUIDE.is_file()
    assert "docs/painel.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_npm_script_the_guide_names_exists() -> None:
    scripts = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["scripts"]
    named = set(re.findall(r"npm --prefix web (?:run )?(\w+)", GUIDE.read_text(encoding="utf-8")))
    assert {"check", "test", "build"} <= named
    for name in named - {"ci"}:
        assert name in scripts, name


def test_every_file_the_guide_cites_exists() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for path in re.findall(r"`((?:web|scripts|docs)/[\w./-]+)`", text):
        assert (ROOT / path).exists(), path
    assert (ROOT / "scripts" / "gen_api_types.py").is_file()
    assert (ROOT / "web" / ".nvmrc").is_file()
