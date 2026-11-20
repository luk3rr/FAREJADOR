# Filename: test_size.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The dashboard stays small: 150 KB in total (NFR-1, NFR-1.1)."""

from pathlib import Path

WEB = Path(__file__).resolve().parent.parent.parent / "web"
KB = 1024
TOTAL_BUDGET = 150 * KB


def total_size() -> int:
    files = [
        *(WEB / "src").rglob("*.ts"),
        WEB / "static" / "index.html",
        WEB / "static" / "styles.css",
        WEB / "static" / "icon.png",
    ]
    return sum(path.stat().st_size for path in files)


def test_everything_the_page_loads_fits_in_150_kb() -> None:
    """TypeScript sources are a ceiling for the compiled JavaScript, so this is conservative."""
    assert total_size() <= TOTAL_BUDGET, f"{total_size() / KB:.1f} KB of {TOTAL_BUDGET / KB:.0f} KB"


def test_the_page_loads_no_file_from_outside_assets() -> None:
    index = (WEB / "static" / "index.html").read_text()
    for token in ("http://", "https://", "//cdn", "<style", "<script>", " onclick", " style="):
        assert token not in index, token
    assert index.count("<script") == 1 and 'type="module"' in index
    css = (WEB / "static" / "styles.css").read_text()
    assert "@import" not in css and "url(" not in css
