# Filename: test_forbidden_apis.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The dashboard code never has a way to turn text into markup or code (NFR-3, FR-21, R-2)."""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "web" / "src"

FORBIDDEN = {
    "innerHTML": r"\binnerHTML\b",
    "outerHTML": r"\bouterHTML\b",
    "insertAdjacentHTML": r"\binsertAdjacentHTML\b",
    "document.write": r"\bdocument\s*\.\s*write(ln)?\b",
    "eval": r"\beval\s*\(",
    "new Function": r"\bnew\s+Function\b|\bFunction\s*\(",
    "setTimeout with a string": r"\bset(Timeout|Interval)\s*\(\s*[\"'`]",
    "an on* handler assignment": r"\.\s*on[a-z]+\s*=[^=]",
    "an on* attribute": r"setAttribute\s*\(\s*[\"']on",
    "a style attribute": r"setAttribute\s*\(\s*[\"']style|\.style\.cssText|\.style\s*=[^=]",
    "javascript: URL": r"javascript\s*:",
    "srcdoc": r"\bsrcdoc\b",
    "createContextualFragment": r"\bcreateContextualFragment\b|\bDOMParser\b",
    "dynamic import": r"\bimport\s*\(",
    "document.cookie": r"\bdocument\s*\.\s*cookie\b",
    "an inline web worker or blob url": r"\bnew\s+Worker\b|\bURL\s*\.\s*createObjectURL\b",
}


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", source)


def violations(source: str) -> list[str]:
    code = strip_comments(source)
    return [name for name, pattern in FORBIDDEN.items() if re.search(pattern, code)]


def sources() -> list[Path]:
    return sorted(SRC.rglob("*.ts"))


def test_the_scanner_finds_each_forbidden_api() -> None:
    samples = {
        "innerHTML": "el.innerHTML = x;",
        "outerHTML": "el.outerHTML = x;",
        "insertAdjacentHTML": "el.insertAdjacentHTML('beforeend', x);",
        "document.write": "document.write(x);",
        "eval": "eval(x);",
        "new Function": "const f = new Function('return 1');",
        "setTimeout with a string": "setTimeout('alert(1)', 1);",
        "an on* handler assignment": "el.onclick = () => 1;",
        "an on* attribute": "el.setAttribute('onclick', 'x');",
        "a style attribute": "el.setAttribute('style', 'x');",
        "javascript: URL": "const u = 'javascript:alert(1)';",
        "srcdoc": "frame.srcdoc = x;",
        "createContextualFragment": "range.createContextualFragment(x);",
        "dynamic import": "await import('./x.js');",
        "document.cookie": "const c = document.cookie;",
        "an inline web worker or blob url": "new Worker(URL.createObjectURL(b));",
    }
    assert samples.keys() == FORBIDDEN.keys()
    for name, sample in samples.items():
        assert name in violations(sample), name


def test_the_scanner_ignores_comments_and_harmless_code() -> None:
    harmless = """
    // never use innerHTML here
    /* eval( is forbidden */
    const note = "ok"; // document.write is not used
    element.textContent = value;
    element.addEventListener("click", handler);
    const same = a == b;
    """
    assert violations(harmless) == []


@pytest.mark.parametrize("path", sources(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_source_file_uses_a_forbidden_api(path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8")) == []


def test_there_are_sources_to_scan() -> None:
    assert len(sources()) >= 8


def test_only_the_entry_point_touches_the_page() -> None:
    """`document` and `window` live in main.ts; the rest is pure or uses the renderer."""
    for path in sources():
        if path.name == "main.ts":
            continue
        code = strip_comments(path.read_text(encoding="utf-8"))
        assert not re.search(r"\b(document|window|localStorage|location)\b", code), path.name


def test_every_source_file_starts_with_the_standard_header() -> None:
    for path in sources():
        if path.name == "types.ts":  # generated
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == f"// Filename: {path.name}", path.name
        assert re.fullmatch(r"// Created on: [A-Z][a-z]+ \d{1,2}, \d{4}", lines[1]), path.name
        assert lines[2] == "// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>", path.name
