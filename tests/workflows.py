# Filename: workflows.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Helpers to read the GitHub workflows as data (static checks, no network)."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return loaded


def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """The ``on`` block; YAML 1.1 parses the bare key ``on`` as the boolean True."""
    value: dict[str, Any] = workflow.get("on", workflow.get(True))
    return value


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = job["steps"]
    return result


def run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in steps(job))


def all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))
