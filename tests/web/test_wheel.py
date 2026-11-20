# Filename: test_wheel.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The compiled dashboard travels inside the wheel even though git ignores it (FR-25)."""

import zipfile
from pathlib import Path

import pytest
from tests.workflows import ROOT

STATIC = ROOT / "src" / "farejador" / "web" / "static"


def test_the_build_output_is_declared_as_a_wheel_artifact() -> None:
    text = (ROOT / "pyproject.toml").read_text()
    assert 'artifacts = ["src/farejador/web/static/**"]' in text


@pytest.mark.skipif(not (STATIC / "index.html").is_file(), reason="the dashboard is not built")
def test_a_real_wheel_contains_the_page_and_every_compiled_module(tmp_path: Path) -> None:
    import subprocess

    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )
    wheel = next(out.glob("*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    built = {
        f"farejador/web/static/{path.relative_to(STATIC).as_posix()}"
        for path in STATIC.rglob("*")
        if path.is_file()
    }
    assert "farejador/web/static/index.html" in built
    assert built <= names, sorted(built - names)
