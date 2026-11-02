#!/usr/bin/env python3
"""Smoke test a built JAR binary (or the source tree).

The script only exercises commands that work without a GUI, network access or
write access to the user's real configuration.

    python scripts/smoke_test.py dist/jar
    python scripts/smoke_test.py --source
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jar.version import APP_NAME, __version__  # noqa: E402


def run(command: list[str], env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    source = "--source" in args
    if source:
        args.remove("--source")
    if not source and not args:
        raise SystemExit("usage: smoke_test.py <path-to-jar> [--source]")

    if source:
        command = [sys.executable, "-m", "jar"]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
    else:
        binary = Path(args[0]).expanduser().resolve()
        if not binary.exists():
            raise SystemExit(f"binary not found: {binary}")
        command = [str(binary)]
        env = dict(os.environ)

    with tempfile.TemporaryDirectory(prefix="jar-smoke-") as temporary:
        sandbox = Path(temporary)
        env["JAR_CONFIG_DIR"] = str(sandbox / "config")
        env["JAR_DATA_DIR"] = str(sandbox / "data")
        env["NO_COLOR"] = "1"

        version = run(command + ["version"], env)
        assert APP_NAME in version and __version__ in version, version
        print(f"ok   version -> {version.strip()}")

        payload = json.loads(run(command + ["--json", "version"], env))
        assert payload["name"] == APP_NAME and payload["version"] == __version__
        print("ok   version --json")

        help_text = run(command + ["--help"], env)
        assert "organize" in help_text and "duplicates" in help_text
        print("ok   --help")

        doctor = json.loads(run(command + ["doctor", "--json"], env))
        assert doctor["ok"], doctor
        print("ok   doctor")

        inbox = sandbox / "inbox"
        inbox.mkdir()
        (inbox / "smoke.txt").write_text("smoke", encoding="utf-8")
        (inbox / "smoke.jpg").write_text("image", encoding="utf-8")
        run(command + ["organize", str(inbox), "--dest", str(sandbox / "sorted")], env)
        assert (sandbox / "sorted" / "Documents" / "smoke.txt").exists()
        assert (sandbox / "sorted" / "Pictures" / "smoke.jpg").exists()
        print("ok   organize")

        undo = json.loads(run(command + ["undo", "--yes", "--json"], env))
        assert undo["restored"] == 2, undo
        assert (inbox / "smoke.txt").exists()
        print("ok   undo")

    print(f"\n{APP_NAME} {__version__} smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
