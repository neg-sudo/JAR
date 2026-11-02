"""User-defined shell hooks with JAR_* environment variables.

Hooks are disabled by default.  Each hook is a shell command configured under
``hooks`` in the config.  Commands receive:

``JAR_EVENT``, ``JAR_SOURCE``, ``JAR_DEST``, ``JAR_CATEGORY``, ``JAR_SIZE``,
``JAR_BATCH``, ``JAR_PROFILE``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .config import Config

log = logging.getLogger("jar.hooks")


class HookRunner:
    def __init__(self, config: Config):
        self.config = config

    def enabled(self, name: str) -> bool:
        return bool((self.config.data.get("hooks") or {}).get(name))

    def run(self, name: str, values: dict[str, object]) -> bool:
        hooks = self.config.data.get("hooks") or {}
        command = str(hooks.get(name) or "").strip()
        if not command:
            return True
        env = dict(os.environ)
        for key, value in values.items():
            env[f"JAR_{str(key).upper()}"] = "" if value is None else str(value)
        env["JAR_EVENT"] = name
        env["JAR_PROFILE"] = self.config.profile
        try:
            timeout = float(hooks.get("timeout") or 10)
        except (TypeError, ValueError):
            timeout = 10.0
        try:
            completed = subprocess.run(
                command,
                shell=True,
                env=env,
                cwd=str(Path.home()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                check=False,
            )
            if completed.stdout.strip():
                log.info("hook %s output: %s", name, completed.stdout.strip()[:2000])
            if completed.returncode != 0:
                log.warning("hook %s exited with %s", name, completed.returncode)
                return False
            return True
        except subprocess.TimeoutExpired:
            log.warning("hook %s timed out after %ss", name, timeout)
            return False
        except OSError as exc:
            log.warning("hook %s failed: %s", name, exc)
            return False
