# Filename: stubs.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A fake ``docker`` and ``cosign`` on the PATH, controlled by files, to run ``update.sh`` offline.

Nothing here talks to a registry or to Docker (M-003). Every call is appended to ``calls.log``.
"""

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
UPDATE_SH = ROOT / "deploy" / "update.sh"

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64

DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_DIR/calls.log"
case "$1" in
  buildx)
    if [ -f "$STUB_DIR/registry_down" ]; then exit 1; fi
    cat "$STUB_DIR/stable_digest"
    ;;
  compose)
    for arg in "$@"; do
      if [ "$arg" = "pull" ] && [ -f "$STUB_DIR/pull_fails" ]; then exit 1; fi
      if [ "$arg" = "up" ]; then
        if [ -f "$STUB_DIR/up_fails_once" ]; then rm "$STUB_DIR/up_fails_once"; exit 1; fi
        echo "up with $(cat "$FAREJADOR_IMAGE_ENV")" >> "$STUB_DIR/calls.log"
      fi
    done
    ;;
  inspect)
    if [ -s "$STUB_DIR/health_sequence" ]; then
      head -n 1 "$STUB_DIR/health_sequence"
      tail -n +2 "$STUB_DIR/health_sequence" > "$STUB_DIR/health_sequence.next"
      mv "$STUB_DIR/health_sequence.next" "$STUB_DIR/health_sequence"
    else
      cat "$STUB_DIR/health_default"
    fi
    ;;
  image) ;;
esac
exit 0
"""

COSIGN_STUB = """#!/usr/bin/env bash
echo "cosign $*" >> "$STUB_DIR/calls.log"
if [ -f "$STUB_DIR/cosign_fails" ]; then
  echo "no matching signatures" >&2
  exit 1
fi
echo '[{"critical":{}}]'
exit 0
"""

SLEEP_STUB = "#!/usr/bin/env bash\nexit 0\n"


@dataclass
class Sandbox:
    root: Path
    stub_dir: Path
    home: Path
    state: Path

    @property
    def calls(self) -> list[str]:
        log = self.stub_dir / "calls.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    @property
    def image_env(self) -> Path:
        return self.home / "image.env"

    def set_stable(self, digest: str) -> None:
        (self.stub_dir / "stable_digest").write_text(digest + "\n")

    def flag(self, name: str) -> None:
        (self.stub_dir / name).write_text("")

    def health(self, *statuses: str, default: str = "healthy") -> None:
        (self.stub_dir / "health_sequence").write_text(
            "\n".join(statuses) + ("\n" if statuses else "")
        )
        (self.stub_dir / "health_default").write_text(default + "\n")

    def write_current(self, digest: str, last_good: str | None = None) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        self.image_env.write_text(f"FAREJADOR_IMAGE=ghcr.io/luk3rr/farejador@{digest}\n")
        if last_good:
            (self.state / "last_good").write_text(last_good + "\n")

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None, path: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": path if path is not None else f"{self.stub_dir}:{os.environ['PATH']}",
            "FAREJADOR_HOME": str(self.home),
            "FAREJADOR_UPDATE_STATE_DIR": str(self.state),
            "FAREJADOR_COMPOSE_FILE": str(self.home / "docker-compose.server.yml"),
            "FAREJADOR_IMAGE_ENV": str(self.image_env),
            "FAREJADOR_HEALTH_TIMEOUT": "20",
            "FAREJADOR_HEALTH_INTERVAL": "5",
            "STUB_DIR": str(self.stub_dir),
            "HOME": str(self.root),
        }
        env.update(extra_env or {})
        return subprocess.run(
            ["/usr/bin/env", "bash", str(UPDATE_SH), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


def make_sandbox(tmp_path: Path) -> Sandbox:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("cosign", COSIGN_STUB), ("sleep", SLEEP_STUB)):
        script = stub_dir / name
        script.write_text(body)
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    home = tmp_path / "opt"
    home.mkdir()
    state = tmp_path / "state"
    sandbox = Sandbox(tmp_path, stub_dir, home, state)
    sandbox.set_stable(DIGEST_A)
    sandbox.health(default="healthy")
    return sandbox
