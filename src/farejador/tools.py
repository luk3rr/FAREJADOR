# Filename: tools.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Read-only repository tools confined to a checkout (FR-9, NFR-2, ADR-4).

The agent can read, search and list files; it cannot write, execute or reach the network.
Every error is returned as text the model can read, never raised through the agent loop.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from farejador.review.filters import is_secret_path, mask

MAX_READ_LINES = 400
MAX_READ_CHARS = 30_000
MAX_FILE_BYTES = 2_000_000
MAX_GREP_RESULTS = 100
MAX_GREP_LINE = 300
MAX_PATTERN = 200
MAX_DIR_ENTRIES = 200
GREP_TIMEOUT_S = 10
_BINARY_SAMPLE = 8192


def error_json(message: str) -> str:
    """An error as JSON text for the model, keeping accents readable (not ``\\u00e3``)."""
    return json.dumps({"error": message}, ensure_ascii=False)


class ToolError(Exception):
    """A tool call that cannot be served; the message is shown to the model."""


class RepoTools:
    """The three read-only tools, bound to one repository checkout."""

    def __init__(self, root: Path, *, git: str = "git") -> None:
        self._root = root.resolve()
        self._git = shutil.which(git) or git

    # -- confinement -----------------------------------------------------------------------

    def resolve(self, path: str | None) -> Path:
        """Resolve a model-supplied path inside the checkout or raise ``ToolError``."""
        raw = (path or ".").replace("\\", "/")
        if "\x00" in raw:
            raise ToolError("caminho inválido")
        raw = raw.lstrip("/") or "."
        candidate = (self._root / raw).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ToolError("o caminho está fora do repositório")
        relative = candidate.relative_to(self._root)
        if ".git" in relative.parts or is_secret_path(relative.as_posix()):
            raise ToolError("caminho indisponível")
        return candidate

    def _relative(self, path: Path) -> str:
        relative = path.relative_to(self._root).as_posix()
        return relative if relative != "." else ""

    # -- tools -----------------------------------------------------------------------------

    def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"arquivo não encontrado: {path}")
        if not target.is_file():
            raise ToolError(f"não é um arquivo: {path}")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(f"arquivo grande demais para ler ({target.stat().st_size} bytes)")
        data = target.read_bytes()
        if b"\x00" in data[:_BINARY_SAMPLE]:
            raise ToolError("arquivo binário")

        start = 1 if start_line is None else start_line
        if start < 1:
            raise ToolError("start_line deve ser pelo menos 1")
        if end_line is not None and end_line < start:
            raise ToolError("end_line não pode ser menor que start_line")

        lines = data.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        if total and start > total:
            raise ToolError(f"start_line {start} está além do fim do arquivo ({total} linhas)")
        last = total if end_line is None else min(end_line, total)

        shown: list[str] = []
        used = 0
        stopped_at = last
        for number in range(start, min(last, start + MAX_READ_LINES - 1) + 1):
            rendered = f"{number}: {lines[number - 1]}"
            if used + len(rendered) + 1 > MAX_READ_CHARS and shown:
                stopped_at = number - 1
                break
            shown.append(rendered)
            used += len(rendered) + 1
            stopped_at = number
        header = (
            f"{self._relative(target)} (linhas {start}-{max(stopped_at, start - 1)} de {total})"
        )
        if stopped_at < last:
            header += f"\n[truncado: chame de novo com start_line={stopped_at + 1} para continuar]"
        return "\n".join([header, *shown])

    def grep(self, pattern: str, path: str | None = None, max_results: int | None = None) -> str:
        if not pattern:
            raise ToolError("o padrão não pode ser vazio")
        if len(pattern) > MAX_PATTERN:
            raise ToolError(f"o padrão tem mais de {MAX_PATTERN} caracteres")
        limit = MAX_GREP_RESULTS if max_results is None else max(1, min(max_results, 100))
        scope = self._relative(self.resolve(path))

        command = [self._git, "grep", "-n", "-I", "-E", "--no-color", "-e", pattern, "--"]
        command.append(scope or ".")
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell; scope checked by resolve()
                command,
                cwd=self._root,
                capture_output=True,
                timeout=GREP_TIMEOUT_S,
                check=False,
                env=git_env(),
            )
        except subprocess.TimeoutExpired:
            raise ToolError(
                "a busca excedeu o tempo; use um padrão mais simples ou um caminho mais restrito"
            ) from None
        if result.returncode == 1:
            return "nenhuma ocorrência"
        if result.returncode != 0:
            raise ToolError("padrão de busca inválido")

        found = result.stdout.decode("utf-8", errors="replace").splitlines()
        lines = [_clip(line, MAX_GREP_LINE) for line in found[:limit]]
        if len(found) > limit:
            lines.append(f"[{len(found) - limit} resultados a mais omitidos; restrinja a busca]")
        return "\n".join(lines)

    def list_dir(self, path: str | None = None) -> str:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"diretório não encontrado: {path or '.'}")
        if not target.is_dir():
            raise ToolError(f"não é um diretório: {path}")
        entries = sorted(
            (entry for entry in target.iterdir() if entry.name != ".git"),
            key=lambda entry: (not entry.is_dir(), entry.name.lower()),
        )
        lines: list[str] = []
        for entry in entries[:MAX_DIR_ENTRIES]:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                lines.append(f"{entry.name} ({entry.stat().st_size} bytes)")
        if len(entries) > MAX_DIR_ENTRIES:
            lines.append(f"[{len(entries) - MAX_DIR_ENTRIES} entradas a mais omitidas]")
        return "\n".join(lines) if lines else "(diretório vazio)"

    # -- dispatch for the agent loop -------------------------------------------------------

    def execute(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Run a tool by name; failures come back as ``{"error": "..."}`` text."""
        handlers: dict[str, Callable[[Mapping[str, Any]], str]] = {
            "read_file": lambda a: self.read_file(
                _text(a, "path", required=True),
                _number(a, "start_line"),
                _number(a, "end_line"),
            ),
            "grep": lambda a: self.grep(
                _text(a, "pattern", required=True), _text(a, "path"), _number(a, "max_results")
            ),
            "list_dir": lambda a: self.list_dir(_text(a, "path")),
        }
        handler = handlers.get(name)
        if handler is None:
            return error_json(f"ferramenta desconhecida: {name}")
        try:
            # Everything the model reads is masked first (FR-19), keeping line numbers intact.
            return mask(handler(arguments))
        except ToolError as exc:
            return error_json(str(exc))
        except OSError:
            return error_json("não foi possível ler o arquivo")


def _text(arguments: Mapping[str, Any], key: str, *, required: bool = False) -> Any:
    value = arguments.get(key)
    if value is None:
        if required:
            raise ToolError(f"argumento ausente: {key}")
        return None
    if not isinstance(value, str):
        raise ToolError(f"o argumento {key} deve ser texto")
    return value


def _number(arguments: Mapping[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"o argumento {key} deve ser um inteiro")
    return value


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def git_env() -> dict[str, str]:
    """A clean environment so user and system git configuration never apply."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C.UTF-8",
    }
