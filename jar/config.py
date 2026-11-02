"""Configuration loading, validation, profiles and app paths."""

from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .categories import CATEGORY_EXTENSIONS, DEFAULT_CATEGORY_DESTINATIONS
from .errors import ConfigError
from .utils import (
    atomic_write_json,
    deep_get,
    deep_merge,
    deep_set,
    deep_unset,
    expand_path,
)

CONFIG_VERSION = 2
CONFLICT_STRATEGIES = [
    "rename",
    "skip",
    "overwrite",
    "trash",
    "dedupe",
    "keep_newest",
    "keep_oldest",
]
MODES = ["global", "local"]
DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
    ".cache/",
    ".DS_Store",
    "desktop.ini",
    "Thumbs.db",
    "$RECYCLE.BIN/",
    "*.crdownload",
    "*.part",
    "*.partial",
    "*.download",
    "*.tmp",
    "*.temp",
    "*.swp",
    "*.swo",
    "~$*",
    ".~lock.*",
    "*.jar-journal",
]


def default_config() -> dict[str, Any]:
    """Return a fresh copy of the built-in configuration."""
    return {
        "version": CONFIG_VERSION,
        "profile": "default",
        "profiles": {},
        "mode": "global",
        "dest_root": "",
        "watch_dirs": [],
        "recursive": False,
        "follow_symlinks": False,
        "conflict": "rename",
        "dry_run": False,
        "use_trash": False,
        "quarantine_dir": "",
        "notifications": True,
        "notify_on_summary": True,
        "cleanup_empty_dirs": False,
        "sanitize_names": False,
        "normalize_names": False,
        "lowercase_names": False,
        "max_filename_length": 200,
        "date_subfolders": False,
        "destination_template": "{category}",
        "category_destinations": copy.deepcopy(DEFAULT_CATEGORY_DESTINATIONS),
        "categories": copy.deepcopy(CATEGORY_EXTENSIONS),
        "rules": [],
        "ignore_hidden": True,
        "ignore_patterns": list(DEFAULT_IGNORE_PATTERNS),
        "ignore_files": [".jarignore"],
        "min_age_seconds": 0,
        "max_age_seconds": 0,
        "min_size": 0,
        "max_size": 0,
        "include_categories": [],
        "exclude_categories": [],
        "watch_interval": 2.0,
        "watch_stability": 2.0,
        "watch_existing": False,
        "hooks": {
            "before_move": "",
            "after_move": "",
            "on_error": "",
            "timeout": 10,
            "fail_closed": False,
        },
        "log_level": "INFO",
        "log_max_bytes": 1048576,
        "log_backups": 3,
        "lock_enabled": True,
        "lock_timeout": 0,
        "lock_stale_seconds": 3600,
        "protected_paths": [],
        "theme": "dark",
        "json_indent": 2,
    }


@dataclass
class AppPaths:
    config_dir: Path
    config_file: Path
    data_dir: Path
    db_file: Path
    log_file: Path
    quarantine_dir: Path
    lock_file: Path

    def ensure(self) -> None:
        for directory in (
            self.config_dir,
            self.data_dir,
            self.log_file.parent,
            self.quarantine_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def resolve_paths(config_path: str | os.PathLike[str] | None = None) -> AppPaths:
    """Resolve configuration, data and log locations.

    Environment overrides make the app easy to sandbox and test:
    ``JAR_CONFIG_DIR``, ``JAR_DATA_DIR`` and ``JAR_CONFIG_FILE``.
    """
    if config_path:
        config_file = Path(config_path).expanduser()
        config_dir = config_file.parent
    else:
        env_file = os.environ.get("JAR_CONFIG_FILE")
        if env_file:
            config_file = Path(env_file).expanduser()
            config_dir = config_file.parent
        else:
            config_dir = Path(
                os.environ.get("JAR_CONFIG_DIR")
                or (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "jar")
            ).expanduser()
            config_file = config_dir / "config.json"

    data_dir = Path(
        os.environ.get("JAR_DATA_DIR")
        or (Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jar")
    ).expanduser()

    return AppPaths(
        config_dir=config_dir,
        config_file=config_file,
        data_dir=data_dir,
        db_file=data_dir / "jar.db",
        log_file=data_dir / "logs" / "jar.log",
        quarantine_dir=data_dir / "quarantine",
        lock_file=data_dir / "jar.lock",
    )


def _detect_default_dirs() -> list[str]:
    found: list[str] = []
    for name in ("Downloads", "Desktop", "Documents", "Pictures"):
        path = Path.home() / name
        if path.is_dir():
            found.append(str(path))
    return found


class Config:
    """Loaded configuration with profile support and safe persistence."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        profile: str | None = None,
        *,
        load: bool = True,
    ):
        self.paths = resolve_paths(path)
        self.exists = self.paths.config_file.exists()
        self.raw: dict[str, Any] = {}
        self.profile = "default"
        if load:
            self.reload(profile=profile)
        else:
            self.raw = {}
            self.profile = profile or "default"
            self.data = self._merge()

    # ------------------------------------------------------------------ load
    def reload(self, profile: str | None = None) -> None:
        self.exists = self.paths.config_file.exists()
        self.raw = {}
        if self.exists:
            try:
                text = self.paths.config_file.read_text(encoding="utf-8-sig")
            except OSError as exc:
                raise ConfigError(f"cannot read {self.paths.config_file}: {exc}") from exc
            if text.strip():
                try:
                    loaded = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        f"invalid JSON in {self.paths.config_file} at line {exc.lineno}: {exc.msg}"
                    ) from exc
                if not isinstance(loaded, dict):
                    raise ConfigError(f"{self.paths.config_file} must contain a JSON object")
                self.raw = loaded
        self.profile = profile or str(self.raw.get("profile") or "default")
        self.data = self._merge()
        if not self.exists and not self.data.get("watch_dirs"):
            self.data["watch_dirs"] = _detect_default_dirs()

    def _merge(self) -> dict[str, Any]:
        merged = deep_merge(default_config(), self.raw)
        profiles = merged.get("profiles") or {}
        if self.profile != "default":
            if not isinstance(profiles, dict) or self.profile not in profiles:
                raise ConfigError(
                    f"unknown profile: {self.profile!r}. "
                    f"Available profiles: {', '.join(sorted(profiles)) or 'default'}"
                )
            profile_data = profiles.get(self.profile)
            if not isinstance(profile_data, dict):
                raise ConfigError(f"profile {self.profile!r} must be a JSON object")
            merged = deep_merge(merged, profile_data)
        merged["profile"] = self.profile
        merged["version"] = CONFIG_VERSION
        return merged

    # ------------------------------------------------------------------ read
    def get(self, key: str, default: Any = None) -> Any:
        return deep_get(self.data, key, default)

    @property
    def watch_dirs(self) -> list[str]:
        return list(self.data.get("watch_dirs") or [])

    @property
    def destination_root(self) -> Path:
        value = self.data.get("dest_root") or ""
        path = expand_path(value, Path.home())
        return (path or Path.home()).resolve(strict=False)

    @property
    def quarantine_dir(self) -> Path:
        value = self.data.get("quarantine_dir") or ""
        path = expand_path(value, self.paths.data_dir)
        return (path or self.paths.quarantine_dir).resolve(strict=False)

    def resolved_watch_dirs(self) -> list[Path]:
        result: list[Path] = []
        for value in self.watch_dirs:
            path = expand_path(value)
            if path is not None:
                result.append(path)
        return result

    def profile_names(self) -> list[str]:
        profiles = set((self.raw.get("profiles") or {}).keys())
        profiles.add("default")
        return sorted(profiles)

    # ----------------------------------------------------------------- write
    def _write_target(self) -> dict[str, Any]:
        if self.profile == "default":
            return self.raw
        profiles = self.raw.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigError("'profiles' must be a JSON object")
        target = profiles.setdefault(self.profile, {})
        if not isinstance(target, dict):
            raise ConfigError(f"profile {self.profile!r} must be a JSON object")
        return target

    def set(self, key: str, value: Any) -> None:
        deep_set(self._write_target(), key, value)
        self.data = self._merge()

    def unset(self, key: str) -> bool:
        removed = deep_unset(self._write_target(), key)
        self.data = self._merge()
        return removed

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            deep_set(self._write_target(), key, value)
        self.data = self._merge()

    def save(self) -> Path:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        payload = copy.deepcopy(self.raw)
        payload["version"] = CONFIG_VERSION
        payload.setdefault("profile", self.profile)
        atomic_write_json(self.paths.config_file, payload)
        self.exists = True
        return self.paths.config_file

    def create_default(self, force: bool = False) -> Path:
        if self.exists and not force:
            raise ConfigError(
                f"config already exists at {self.paths.config_file} (use --force to overwrite)"
            )
        payload = default_config()
        payload["watch_dirs"] = _detect_default_dirs()
        self.raw = payload
        self.profile = "default"
        self.data = self._merge()
        return self.save()

    # --------------------------------------------------------------- profiles
    def create_profile(self, name: str, values: dict[str, Any] | None = None) -> None:
        if not name or name == "default":
            raise ConfigError("profile name must be non-empty and cannot be 'default'")
        profiles = self.raw.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigError("'profiles' must be a JSON object")
        profiles[name] = values or {}
        self.data = self._merge()

    def delete_profile(self, name: str) -> bool:
        profiles = self.raw.get("profiles") or {}
        if name == "default":
            raise ConfigError("the 'default' profile cannot be deleted")
        if name not in profiles:
            return False
        del profiles[name]
        if self.profile == name:
            self.profile = "default"
            self.raw["profile"] = "default"
        self.data = self._merge()
        return True

    def use_profile(self, name: str) -> None:
        if name not in self.profile_names():
            raise ConfigError(f"unknown profile: {name}")
        self.profile = name
        self.raw["profile"] = name
        self.data = self._merge()

    # --------------------------------------------------------------- overrides
    def with_overrides(self, overrides: dict[str, Any]) -> "Config":
        """Return a copy with dotted-key overrides applied to the merged view."""
        clone = copy.deepcopy(self)
        for key, value in (overrides or {}).items():
            if value is not None:
                deep_set(clone.data, key, value)
        return clone

    # --------------------------------------------------------------- migration
    def migrate_from(self, source: str | os.PathLike[str]) -> dict[str, Any]:
        source_path = Path(source).expanduser()
        try:
            legacy = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ConfigError(f"cannot read {source_path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON in {source_path}: {exc}") from exc
        if not isinstance(legacy, dict):
            raise ConfigError("legacy config must be a JSON object")
        migrated: dict[str, Any] = {}
        watch_dirs = legacy.get("watch_dirs") or legacy.get("watchDirs") or []
        if isinstance(watch_dirs, list):
            migrated["watch_dirs"] = [str(item) for item in watch_dirs if str(item).strip()]
        raw_mode = str(legacy.get("mode") or "").lower()
        if "local" in raw_mode or "mode 2" in raw_mode:
            migrated["mode"] = "local"
        elif raw_mode:
            migrated["mode"] = "global"
        dest_root = legacy.get("dest_root") or legacy.get("destRoot")
        if dest_root:
            migrated["dest_root"] = str(dest_root)
        self.raw = deep_merge(self.raw, migrated)
        self.data = self._merge()
        return migrated

    # --------------------------------------------------------------- validation
    def validate(self) -> list[tuple[str, str]]:
        issues: list[tuple[str, str]] = []
        data = self.data

        if data.get("mode") not in MODES:
            issues.append(("error", f"mode must be one of {', '.join(MODES)}"))
        if data.get("conflict") not in CONFLICT_STRATEGIES:
            issues.append(
                ("error", f"conflict must be one of {', '.join(CONFLICT_STRATEGIES)}")
            )

        for key in ("min_age_seconds", "max_age_seconds", "min_size", "max_size"):
            try:
                if int(data.get(key) or 0) < 0:
                    issues.append(("error", f"{key} cannot be negative"))
            except (TypeError, ValueError):
                issues.append(("error", f"{key} must be a number"))

        if data.get("min_size") and data.get("max_size"):
            try:
                if int(data["min_size"]) > int(data["max_size"]):
                    issues.append(("error", "min_size cannot be greater than max_size"))
            except (TypeError, ValueError):
                pass

        if not isinstance(data.get("categories"), dict):
            issues.append(("error", "categories must be an object of category -> extension list"))
        else:
            for name, extensions in data["categories"].items():
                if not isinstance(extensions, list):
                    issues.append(("error", f"category {name!r} must map to a list of extensions"))

        if not isinstance(data.get("category_destinations"), dict):
            issues.append(("error", "category_destinations must be an object"))

        if not isinstance(data.get("rules"), list):
            issues.append(("error", "rules must be a list"))
        else:
            names: set[str] = set()
            for idx, rule in enumerate(data["rules"]):
                if not isinstance(rule, dict):
                    issues.append(("error", f"rule #{idx + 1} must be an object"))
                    continue
                name = str(rule.get("name") or f"rule-{idx + 1}")
                if name in names:
                    issues.append(("warning", f"duplicate rule name: {name}"))
                names.add(name)
                if not rule.get("category"):
                    issues.append(("error", f"rule {name!r} is missing a category"))
                if not any(rule.get(key) for key in ("extensions", "globs", "regex")):
                    issues.append(
                        ("warning", f"rule {name!r} has no matcher and will never match")
                    )
                regex = rule.get("regex")
                if regex:
                    try:
                        import re

                        re.compile(str(regex))
                    except re.error as exc:
                        issues.append(("error", f"rule {name!r} has an invalid regex: {exc}"))

        template = str(data.get("destination_template") or "")
        if not template:
            issues.append(("error", "destination_template cannot be empty"))
        if "{" not in template and not data.get("category_destinations"):
            issues.append(("warning", "destination_template does not use any {variables}"))

        dest_root = self.destination_root
        if not dest_root.exists():
            issues.append(("warning", f"destination root does not exist: {dest_root}"))
        elif not os.access(dest_root, os.W_OK):
            issues.append(("error", f"destination root is not writable: {dest_root}"))

        for directory in self.resolved_watch_dirs():
            if not directory.exists():
                issues.append(("warning", f"watched folder does not exist: {directory}"))
            elif not directory.is_dir():
                issues.append(("warning", f"watched path is not a folder: {directory}"))

        for name in data.get("include_categories") or []:
            if name not in (data.get("categories") or {}):
                issues.append(("warning", f"include_categories references unknown category: {name}"))
        for name in data.get("exclude_categories") or []:
            if name not in (data.get("categories") or {}):
                issues.append(("warning", f"exclude_categories references unknown category: {name}"))

        if self.profile != "default" and self.profile not in self.profile_names():
            issues.append(("error", f"active profile does not exist: {self.profile}"))

        try:
            if not self.paths.data_dir.parent.exists():
                issues.append(("warning", f"data directory parent is missing: {self.paths.data_dir.parent}"))
            if not os.access(self.paths.config_dir if self.paths.config_dir.exists() else self.paths.config_dir.parent, os.W_OK):
                issues.append(("error", f"config directory is not writable: {self.paths.config_dir}"))
        except OSError as exc:
            issues.append(("warning", f"cannot check config directory: {exc}"))

        if shutil.which("notify-send") is None and data.get("notifications") and os.name != "nt":
            issues.append(("warning", "notifications are enabled but notify-send was not found"))

        return issues

    def describe(self) -> dict[str, Any]:
        return {
            "config_file": str(self.paths.config_file),
            "data_dir": str(self.paths.data_dir),
            "db_file": str(self.paths.db_file),
            "log_file": str(self.paths.log_file),
            "quarantine_dir": str(self.quarantine_dir),
            "destination_root": str(self.destination_root),
            "profile": self.profile,
            "profiles": self.profile_names(),
            "exists": self.exists,
        }
