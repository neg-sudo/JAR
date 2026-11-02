"""Rule engine: category classification, ignoring and destination templates."""

from __future__ import annotations

import fnmatch
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .categories import CATEGORY_EXTENSIONS, CATEGORY_ORDER, default_destination
from .config import Config
from .errors import RuleError
from .safety import is_hidden_path
from .utils import deep_get, expand_path, format_ts, path_is_within, truncate

log = logging.getLogger("jar.rules")

TEMP_SUFFIXES = {
    ".crdownload", ".part", ".partial", ".download", ".tmp", ".temp", ".swp",
    ".swo", ".lock", ".lck", ".opdownload",
}
IGNORED_NAMES = {
    ".DS_Store", "desktop.ini", "Thumbs.db", "ehthumbs.db", "$RECYCLE.BIN",
    ".directory",
}


def normalize_extension(value: str) -> str:
    value = str(value).strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


@dataclass
class Rule:
    name: str
    category: str
    priority: int = 100
    enabled: bool = True
    extensions: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    regex: str = ""
    destination: str = ""
    min_size: int = 0
    max_size: int = 0
    min_age: int = 0
    max_age: int = 0
    stop: bool = True
    builtin: bool = False
    index: int = 0
    _regex: Any = field(default=None, repr=False, compare=False)

    def compile(self) -> None:
        if self.regex:
            try:
                self._regex = re.compile(self.regex, re.IGNORECASE)
            except re.error as exc:
                raise RuleError(f"rule {self.name!r} has an invalid regex: {exc}") from exc

    def matches(self, path: Path, stat_result: Any, now: float) -> bool:
        if not self.enabled:
            return False
        suffix = path.suffix.lower()
        matched = False
        if self.extensions:
            if suffix not in self.extensions:
                return False
            matched = True
        if self.globs:
            name = path.name
            full = str(path)
            if not any(
                fnmatch.fnmatch(name, pattern)
                or fnmatch.fnmatch(full, pattern)
                or fnmatch.fnmatch(name.lower(), pattern.lower())
                for pattern in self.globs
            ):
                return False
            matched = True
        if self.regex:
            if not self._regex:
                self.compile()
            if not self._regex.search(path.name):
                return False
            matched = True
        if not matched:
            return False
        try:
            size = stat_result.st_size
            age = max(0.0, now - stat_result.st_mtime)
        except (AttributeError, OSError):
            return False
        if self.min_size and size < self.min_size:
            return False
        if self.max_size and size > self.max_size:
            return False
        if self.min_age and age < self.min_age:
            return False
        if self.max_age and age > self.max_age:
            return False
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "priority": self.priority,
            "enabled": self.enabled,
            "extensions": list(self.extensions),
            "globs": list(self.globs),
            "regex": self.regex,
            "destination": self.destination,
            "min_size": self.min_size,
            "max_size": self.max_size,
            "min_age": self.min_age,
            "max_age": self.max_age,
            "stop": self.stop,
            "builtin": self.builtin,
        }


@dataclass
class RuleMatch:
    category: str
    rule: str
    destination: str
    priority: int
    builtin: bool = True

    def describe(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "rule": self.rule,
            "destination": self.destination,
            "priority": self.priority,
            "builtin": self.builtin,
        }


def custom_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    rules = data.get("rules") or []
    return [rule for rule in rules if isinstance(rule, dict)]


def build_rules(data: dict[str, Any]) -> list[Rule]:
    """Build built-in and custom rules, sorted by ascending priority."""
    rules: list[Rule] = []
    categories = data.get("categories") or CATEGORY_EXTENSIONS
    order = list(categories.keys()) or CATEGORY_ORDER

    for index, category in enumerate(order):
        extensions = categories.get(category) or []
        if not extensions:
            continue
        rules.append(
            Rule(
                name=f"builtin:{category}",
                category=str(category),
                priority=100 + index,
                extensions=tuple(normalize_extension(ext) for ext in extensions if str(ext).strip()),
                builtin=True,
                index=len(rules),
            )
        )

    for index, raw in enumerate(custom_rules(data)):
        if not raw.get("enabled", True):
            enabled = False
        else:
            enabled = True
        category = str(raw.get("category") or "Others")
        extensions = raw.get("extensions") or []
        if isinstance(extensions, str):
            extensions = [part.strip() for part in extensions.split(",")]
        globs = raw.get("globs") or []
        if isinstance(globs, str):
            globs = [part.strip() for part in globs.split(",")]
        try:
            priority = int(raw.get("priority", 10))
        except (TypeError, ValueError):
            priority = 10
        rule = Rule(
            name=str(raw.get("name") or f"custom:{index + 1}"),
            category=category,
            priority=priority,
            enabled=enabled,
            extensions=tuple(
                normalize_extension(ext) for ext in extensions if str(ext).strip()
            ),
            globs=tuple(str(glob).strip() for glob in globs if str(glob).strip()),
            regex=str(raw.get("regex") or ""),
            destination=str(raw.get("destination") or ""),
            min_size=int(raw.get("min_size") or 0),
            max_size=int(raw.get("max_size") or 0),
            min_age=int(raw.get("min_age") or 0),
            max_age=int(raw.get("max_age") or 0),
            stop=bool(raw.get("stop", True)),
            builtin=False,
            index=index,
        )
        try:
            rule.compile()
        except RuleError as exc:
            log.warning("%s", exc)
            continue
        rules.append(rule)

    rules.sort(key=lambda rule: (rule.priority, rule.builtin, rule.index))
    rules.append(
        Rule(
            name="fallback:Others",
            category="Others",
            priority=10000,
            stop=True,
            builtin=True,
            index=len(rules),
        )
    )
    return rules


def _parse_lines(path: Path) -> list[str]:
    patterns: list[str] = []
    try:
        from .utils import guess_text_encoding

        text = path.read_text(encoding=guess_text_encoding(path), errors="replace")
    except OSError:
        return patterns
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


class RuleEngine:
    """Classify files and decide whether they should be ignored."""

    def __init__(self, config: Config):
        self.config = config
        self.data = config.data
        self.rules = build_rules(self.data)
        self.errors: list[str] = []
        self._ignore_cache: dict[tuple[str, float], list[str]] = {}
        self._dest_names = self._destination_names()

    # ------------------------------------------------------------- ignore logic
    def _ignore_file_patterns(self, root: Path) -> list[str]:
        patterns: list[str] = []
        for filename in self.data.get("ignore_files") or [".jarignore"]:
            candidate = root / filename
            if not candidate.is_file():
                continue
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            cache_key = (str(candidate), mtime)
            cached = self._ignore_cache.get(cache_key)
            if cached is None:
                cached = _parse_lines(candidate)
                self._ignore_cache[cache_key] = cached
            patterns.extend(cached)
        return patterns

    @staticmethod
    def _match_patterns(relative: str, name: str, full: str, patterns: Iterable[str]) -> bool:
        ignored = False
        for raw in patterns:
            pattern = raw.strip()
            if not pattern or pattern.startswith("#"):
                continue
            negate = pattern.startswith("!")
            if negate:
                pattern = pattern[1:].strip()
            if not pattern:
                continue
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            matched = False
            if directory_only:
                matched = (
                    relative == pattern
                    or relative.startswith(pattern + "/")
                    or f"/{pattern}/" in f"/{relative}/"
                )
            else:
                matched = (
                    fnmatch.fnmatch(relative, pattern)
                    or fnmatch.fnmatch(name, pattern)
                    or fnmatch.fnmatch(full, pattern)
                    or fnmatch.fnmatch(name.lower(), pattern.lower())
                    or relative.startswith(pattern.rstrip("/") + "/")
                )
            if matched:
                ignored = not negate
        return ignored

    def ignore_patterns(self, root: Path | None = None) -> list[str]:
        patterns = [str(item) for item in (self.data.get("ignore_patterns") or [])]
        return patterns

    def is_ignored(self, path: Path, roots: Iterable[Path] | None = None) -> bool:
        path = Path(path)
        name = path.name
        if name in IGNORED_NAMES:
            return True
        if path.suffix.lower() in TEMP_SUFFIXES:
            return True
        if path.name.startswith("~$") or path.name.startswith(".~lock."):
            return True
        if self.data.get("ignore_hidden", True) and is_hidden_path(path):
            return True

        patterns = list(self.data.get("ignore_patterns") or [])
        relative_candidates: list[tuple[str, str]] = []
        for root in roots or []:
            try:
                root = Path(root)
                rel = path.relative_to(root)
            except (ValueError, OSError):
                continue
            rel_text = rel.as_posix()
            relative_candidates.append((rel_text, str(root)))
            patterns.extend(self._ignore_file_patterns(root))

        full = str(path)
        if self._match_patterns(path.as_posix(), name, full, patterns):
            return True
        for rel_text, _ in relative_candidates:
            if self._match_patterns(rel_text, name, full, patterns):
                return True
        return False

    def is_ignored_dir(self, path: Path, roots: Iterable[Path] | None = None) -> bool:
        path = Path(path)
        if self.data.get("ignore_hidden", True) and path.name.startswith("."):
            return True
        patterns = list(self.data.get("ignore_patterns") or [])
        for root in roots or []:
            try:
                patterns.extend(self._ignore_file_patterns(Path(root)))
            except (ValueError, OSError):
                continue
        name = path.name
        full = str(path)
        if self._match_patterns(path.as_posix(), name, full, patterns):
            return True
        for root in roots or []:
            try:
                rel = path.relative_to(Path(root)).as_posix()
            except (ValueError, OSError):
                continue
            if self._match_patterns(rel, name, full, patterns):
                return True
        return False

    # -------------------------------------------------------------- classify
    def classify(self, path: Path, stat_result: Any | None = None) -> RuleMatch:
        path = Path(path)
        if stat_result is None:
            try:
                stat_result = path.stat()
            except OSError as exc:
                raise RuleError(f"cannot stat {path}: {exc}") from exc
        now = time.time()
        last: RuleMatch | None = None
        for rule in self.rules:
            if not rule.matches(path, stat_result, now):
                continue
            match = RuleMatch(
                category=rule.category,
                rule=rule.name,
                destination=rule.destination,
                priority=rule.priority,
                builtin=rule.builtin,
            )
            if rule.stop:
                return match
            last = match
        if last is not None:
            return last
        return RuleMatch(
            category="Others", rule="fallback:Others", destination="", priority=10000
        )

    # ------------------------------------------------------------ destinations
    def _destination_names(self) -> set[str]:
        names: set[str] = set()
        custom = self.data.get("category_destinations") or {}
        for category in (self.data.get("categories") or {}):
            value = str(custom.get(category) or default_destination(category))
            first = value.replace("\\", "/").split("/")[0]
            if first and not first.startswith("{"):
                names.add(first)
            elif first.startswith("{"):
                names.add(category)
        template = str(self.data.get("destination_template") or "{category}")
        first = template.replace("\\", "/").split("/")[0]
        if first and not first.startswith("{"):
            names.add(first)
        return names

    def in_destination(self, path: Path, mode: str | None = None, root: Path | None = None) -> bool:
        """Detect files that already live inside a category destination folder."""
        mode = mode or str(self.data.get("mode") or "global")
        path = Path(path)
        if mode == "global":
            dest_root = Path(root) if root else self.config.destination_root
            try:
                rel = path.relative_to(dest_root)
            except ValueError:
                return False
            return bool(rel.parts) and rel.parts[0] in self._dest_names
        # Local mode: the category folder is the file's parent or grandparent.
        parents = [path.parent, path.parent.parent]
        return any(parent.name in self._dest_names for parent in parents if parent.name)

    def template_values(self, path: Path, category: str, stat_result: Any | None = None) -> dict[str, Any]:
        path = Path(path)
        try:
            stat_result = stat_result or path.stat()
            mtime = stat_result.st_mtime
            size = stat_result.st_size
        except OSError:
            mtime = time.time()
            size = 0
        stamp = time.localtime(mtime)
        extension = path.suffix.lower().lstrip(".")
        return {
            "category": category,
            "category_lower": category.lower(),
            "category_slug": re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-") or "others",
            "name": path.name,
            "stem": path.stem,
            "ext": extension,
            "suffix": path.suffix,
            "year": time.strftime("%Y", stamp),
            "month": time.strftime("%m", stamp),
            "day": time.strftime("%d", stamp),
            "date": time.strftime("%Y-%m-%d", stamp),
            "datetime": time.strftime("%Y-%m-%d_%H-%M-%S", stamp),
            "size": size,
            "size_mb": f"{size / (1024 * 1024):.1f}",
            "profile": self.config.profile,
        }

    def template_for(self, match: RuleMatch) -> str:
        if match.destination:
            return match.destination
        custom = self.data.get("category_destinations") or {}
        return str(
            custom.get(match.category)
            or self.data.get("destination_template")
            or "{category}"
        )

    def render_destination(
        self,
        path: Path,
        match: RuleMatch,
        *,
        mode: str | None = None,
        dest_root: Path | None = None,
        stat_result: Any | None = None,
    ) -> Path:
        """Return the full destination *file* path for *path*."""
        path = Path(path)
        mode = mode or str(self.data.get("mode") or "global")
        template = self.template_for(match)
        values = self.template_values(path, match.category, stat_result)
        try:
            rendered = template.format_map(values)
        except (KeyError, IndexError, ValueError) as exc:
            raise RuleError(f"invalid destination template {template!r}: {exc}") from exc
        rendered = rendered.replace("\\", "/").strip()
        if not rendered:
            rendered = match.category
        if self.data.get("date_subfolders"):
            if "{year}" not in template:
                rendered = f"{rendered}/{values['year']}"
            if "{month}" not in template:
                rendered = f"{rendered}/{values['month']}"

        relative = Path(rendered)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuleError(f"destination must stay relative: {template!r}")

        if mode == "local":
            base = path.parent
        else:
            base = Path(dest_root) if dest_root else self.config.destination_root

        folder = base / relative
        destination = folder / path.name
        # Resolve without requiring the folder to exist, then verify containment.
        try:
            folder_resolved = folder.resolve(strict=False)
            base_resolved = base.resolve(strict=False)
        except OSError:
            folder_resolved = folder
            base_resolved = base
        if not path_is_within(folder_resolved, base_resolved):
            raise RuleError(f"destination escapes its root: {template!r} -> {folder}")
        return destination

    # ------------------------------------------------------------------ rules
    def find_rule(self, name: str) -> Rule | None:
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def describe(self) -> list[dict[str, Any]]:
        return [rule.describe() for rule in self.rules]
