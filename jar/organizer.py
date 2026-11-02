"""Planning and executing file moves, conflict policies, undo and dedupe."""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .config import Config
from .duplicates import DuplicateGroup, choose_keeper, file_digest, find_duplicates
from .errors import JarError, RuleError, SafetyError
from .journal import Journal
from .notify import notify_summary
from .plugins import HookRunner
from .rules import RuleEngine, RuleMatch
from .safety import (
    FileLock,
    apply_name_policy,
    is_protected_root,
    unique_path,
)
from .scanner import Candidate, scan_candidates
from .trash import quarantine_file
from .utils import expand_path, human_size, path_is_within

log = logging.getLogger("jar.organize")

ProgressCallback = Callable[[int, int, str], None]
ErrorCallback = Callable[[Path, OSError], None]


def _key(path: Path | str) -> str:
    try:
        value = str(Path(path).resolve(strict=False))
    except OSError:
        value = str(path)
    return os.path.normcase(value)


@dataclass
class PlanItem:
    src: Path
    dst: Path | None
    category: str
    rule: str
    size: int
    mtime: float
    action: str = "move"
    reason: str = ""
    conflict: bool = False
    digest: str = ""

    def describe(self) -> dict:
        return {
            "source": str(self.src),
            "destination": str(self.dst) if self.dst else None,
            "category": self.category,
            "rule": self.rule,
            "size": self.size,
            "mtime": self.mtime,
            "action": self.action,
            "reason": self.reason,
            "conflict": self.conflict,
        }


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    roots: list[Path] = field(default_factory=list)
    mode: str = "global"
    dest_root: Path = field(default_factory=Path.home)
    errors: list[dict] = field(default_factory=list)

    @property
    def moves(self) -> list[PlanItem]:
        return [item for item in self.items if item.action == "move"]

    @property
    def skips(self) -> list[PlanItem]:
        return [item for item in self.items if item.action != "move"]

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.moves)

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "destination_root": str(self.dest_root),
            "items": [item.describe() for item in self.items],
            "moves": len(self.moves),
            "skips": len(self.skips),
            "bytes": self.total_size,
            "errors": self.errors,
        }


@dataclass
class ExecutionResult:
    batch_id: str | None
    moved: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    dry_run: bool = False
    bytes_moved: int = 0
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed

    def describe(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "dry_run": self.dry_run,
            "moved": len(self.moved),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "bytes_moved": self.bytes_moved,
            "started": self.started,
            "finished": self.finished,
            "results": {
                "moved": self.moved,
                "skipped": self.skipped,
                "failed": self.failed,
            },
        }


@dataclass
class UndoResult:
    batches: list[str] = field(default_factory=list)
    restored: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    dry_run: bool = False

    def describe(self) -> dict:
        return {
            "batches": self.batches,
            "restored": len(self.restored),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "dry_run": self.dry_run,
            "results": {
                "restored": self.restored,
                "skipped": self.skipped,
                "failed": self.failed,
            },
        }


@dataclass
class DedupeResult:
    batch_id: str | None
    kept: list[str] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    dry_run: bool = False
    bytes_reclaimed: int = 0

    def describe(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "dry_run": self.dry_run,
            "kept": self.kept,
            "removed": self.removed,
            "failed": self.failed,
            "bytes_reclaimed": self.bytes_reclaimed,
        }


class Organizer:
    """High level facade used by both the CLI and the GUI."""

    def __init__(self, config: Config, journal: Journal | None = None, logger: logging.Logger | None = None):
        self.config = config
        self.paths = config.paths
        self.engine = RuleEngine(config)
        self.journal = journal or Journal(config.paths.db_file)
        self.logger = logger or log
        self.hooks = HookRunner(config)
        self._hash_cache: dict[tuple[str, float, int], str] = {}

    # ----------------------------------------------------------------- helpers
    def _resolved_roots(self, paths: Iterable[str | os.PathLike[str]] | None) -> list[Path]:
        raw = list(paths) if paths else list(self.config.watch_dirs)
        roots: list[Path] = []
        for value in raw:
            path = expand_path(value)
            if path is not None and path.exists():
                roots.append(path)
        return roots

    def _digest(self, path: Path) -> str:
        try:
            stat_result = path.stat()
            key = (str(path), stat_result.st_mtime, stat_result.st_size)
        except OSError:
            return ""
        cached = self._hash_cache.get(key)
        if cached:
            return cached
        try:
            digest = file_digest(path)
        except OSError:
            return ""
        self._hash_cache[key] = digest
        return digest

    def _unique_planned(self, destination: Path, occupied: set[str]) -> Path:
        candidate = destination
        if not candidate.exists() and _key(candidate) not in occupied:
            return candidate
        stem = destination.stem
        suffix = destination.suffix
        counter = 1
        while True:
            candidate = destination.parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists() and _key(candidate) not in occupied:
                return candidate
            counter += 1

    def _apply_name_policy(self, path: Path) -> tuple[str, str]:
        data = self.config.data
        name = apply_name_policy(
            path.name,
            sanitize=bool(data.get("sanitize_names")),
            normalize=bool(data.get("normalize_names")),
            lowercase=bool(data.get("lowercase_names")),
            max_length=int(data.get("max_filename_length") or 200),
        )
        if name != path.name:
            return name, "filename cleaned"
        return name, ""

    def _preview_conflict(
        self,
        src: Path,
        destination: Path,
        occupied: set[str],
        stat_result,
    ) -> tuple[str, Path | None, str, bool, str]:
        strategy = str(self.config.data.get("conflict") or "rename")
        exists = destination.exists() or _key(destination) in occupied
        if not exists:
            occupied.add(_key(destination))
            return "move", destination, "", False, ""

        if strategy == "skip":
            return "skip", None, "destination already exists", True, ""
        if strategy == "rename":
            final = self._unique_planned(destination, occupied)
            occupied.add(_key(final))
            return "move", final, "renamed to avoid a conflict", True, ""
        if strategy == "trash":
            occupied.add(_key(destination))
            return "move", destination, "existing file will be quarantined", True, ""
        if strategy == "overwrite":
            occupied.add(_key(destination))
            return "move", destination, "existing file will be replaced", True, ""
        if strategy == "dedupe":
            if destination.exists() and destination.is_file():
                try:
                    if destination.stat().st_size == stat_result.st_size:
                        digest = self._digest(src)
                        if digest and digest == self._digest(destination):
                            return "skip", None, "identical duplicate", True, digest
                except OSError:
                    pass
            final = self._unique_planned(destination, occupied)
            occupied.add(_key(final))
            return "move", final, "content differs; renamed", True, ""
        if strategy in ("keep_newest", "keep_oldest"):
            if destination.exists():
                try:
                    existing_mtime = destination.stat().st_mtime
                    if strategy == "keep_newest" and existing_mtime >= stat_result.st_mtime:
                        return "skip", None, "existing file is newer or equal", True, ""
                    if strategy == "keep_oldest" and existing_mtime <= stat_result.st_mtime:
                        return "skip", None, "existing file is older or equal", True, ""
                except OSError:
                    pass
            occupied.add(_key(destination))
            return "move", destination, "replaces the older/newer file", True, ""
        # Unknown strategy: be safe and rename.
        final = self._unique_planned(destination, occupied)
        occupied.add(_key(final))
        return "move", final, "renamed to avoid a conflict", True, ""

    # -------------------------------------------------------------------- plan
    def plan(
        self,
        paths: Iterable[str | os.PathLike[str]] | None = None,
        *,
        recursive: bool | None = None,
        categories: Iterable[str] | None = None,
        on_error: ErrorCallback | None = None,
    ) -> Plan:
        data = self.config.data
        raw_paths = list(paths) if paths else list(self.config.watch_dirs)
        if not raw_paths:
            raise JarError(
                "no folders to organize. Pass a folder path or add one with 'jar config set watch_dirs ...'"
            )
        roots = self._resolved_roots(raw_paths)
        if not roots:
            raise JarError("none of the supplied folders exist")
        for root in roots:
            if root.is_dir() and is_protected_root(root, data.get("protected_paths")):
                raise SafetyError(f"refusing to organize a protected system folder: {root}")

        errors: list[dict] = []

        def record_error(path: Path, exc: OSError) -> None:
            errors.append({"path": str(path), "error": str(exc)})
            if on_error:
                on_error(path, exc)

        candidates = scan_candidates(
            roots,
            self.config,
            self.engine,
            recursive=recursive,
            categories=categories,
            on_error=record_error,
        )

        plan = Plan(
            roots=roots,
            mode=str(data.get("mode") or "global"),
            dest_root=self.config.destination_root,
            errors=errors,
        )
        occupied: set[str] = set()

        for candidate in candidates:
            self._plan_candidate(candidate, plan, occupied)

        return plan

    def _plan_candidate(self, candidate: Candidate, plan: Plan, occupied: set[str]) -> None:
        src = candidate.path
        name, name_reason = self._apply_name_policy(src)
        stat_result = None
        try:
            stat_result = src.stat()
        except OSError:
            stat_result = None

        try:
            destination = self.engine.render_destination(
                src,
                candidate.match,
                mode=plan.mode,
                dest_root=plan.dest_root,
                stat_result=stat_result,
            )
        except RuleError as exc:
            plan.items.append(
                PlanItem(
                    src=src,
                    dst=None,
                    category=candidate.match.category,
                    rule=candidate.match.rule,
                    size=candidate.size,
                    mtime=candidate.mtime,
                    action="skip",
                    reason=f"invalid destination: {exc}",
                )
            )
            return

        if name != src.name:
            destination = destination.with_name(name)

        if _key(src) == _key(destination):
            plan.items.append(
                PlanItem(
                    src=src,
                    dst=destination,
                    category=candidate.match.category,
                    rule=candidate.match.rule,
                    size=candidate.size,
                    mtime=candidate.mtime,
                    action="skip",
                    reason="already in its destination",
                )
            )
            return

        if stat_result is None:
            class _StatView:
                st_size = candidate.size
                st_mtime = candidate.mtime

            preview_stat = _StatView()
        else:
            preview_stat = stat_result
        action, final, reason, conflict, digest = self._preview_conflict(
            src, destination, occupied, preview_stat
        )
        if name_reason and action == "move":
            reason = f"{name_reason}; {reason}".strip("; ")
        plan.items.append(
            PlanItem(
                src=src,
                dst=final if action == "move" else (final or destination),
                category=candidate.match.category,
                rule=candidate.match.rule,
                size=candidate.size,
                mtime=candidate.mtime,
                action=action,
                reason=reason,
                conflict=conflict,
                digest=digest,
            )
        )

    # ----------------------------------------------------------------- execute
    def execute(
        self,
        plan: Plan,
        *,
        dry_run: bool | None = None,
        progress: ProgressCallback | None = None,
    ) -> ExecutionResult:
        data = self.config.data
        dry = bool(data.get("dry_run")) if dry_run is None else bool(dry_run)
        result = ExecutionResult(batch_id=None, dry_run=dry)
        if dry:
            result.moved = [item.describe() for item in plan.moves]
            result.skipped = [item.describe() for item in plan.skips]
            result.bytes_moved = plan.total_size
            result.finished = time.time()
            return result
        if not plan.moves:
            result.finished = time.time()
            return result

        lock = (
            FileLock(
                self.paths.lock_file,
                timeout=float(data.get("lock_timeout") or 0),
                stale_after=float(data.get("lock_stale_seconds") or 3600),
            )
            if data.get("lock_enabled", True)
            else None
        )
        context = lock if lock else _NullLock()
        with context:
            batch_id = self.journal.start_batch(
                mode="organize",
                dry_run=False,
                profile=self.config.profile,
                note=f"{plan.mode} mode",
                total=len(plan.moves),
            )
            result.batch_id = batch_id
            total = len(plan.moves)
            for index, item in enumerate(plan.moves, start=1):
                outcome = self._execute_item(item, batch_id)
                if outcome["status"] == "moved":
                    result.moved.append(outcome)
                    result.bytes_moved += int(outcome.get("size") or 0)
                elif outcome["status"] == "skipped":
                    result.skipped.append(outcome)
                else:
                    result.failed.append(outcome)
                if progress:
                    progress(index, total, f"{outcome['status']}: {item.src.name}")
            self.journal.finish_batch(
                batch_id,
                moved=len(result.moved),
                skipped=len(result.skipped),
                failed=len(result.failed),
                total=total,
            )
            result.finished = time.time()

            if data.get("cleanup_empty_dirs"):
                for outcome in result.moved:
                    try:
                        self._cleanup_empty(Path(outcome["source"]).parent, plan.roots)
                    except OSError:
                        continue

            if data.get("notifications") and data.get("notify_on_summary"):
                notify_summary(
                    len(result.moved),
                    len(result.skipped),
                    len(result.failed),
                    result.bytes_moved,
                    enabled=True,
                )
        return result

    def _execute_item(self, item: PlanItem, batch_id: str) -> dict:
        src = item.src
        destination = item.dst
        if destination is None:
            destination = src
        entry: dict = {
            "status": "skipped",
            "source": str(src),
            "destination": str(destination),
            "category": item.category,
            "size": item.size,
            "reason": item.reason,
        }
        if not src.exists():
            entry["reason"] = "source disappeared"
            self.journal.record(
                batch_id,
                "skip",
                src,
                destination,
                category=item.category,
                size=item.size,
                status="skipped",
                error=entry["reason"],
            )
            return entry

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            entry.update(status="failed", reason=f"cannot create destination: {exc}")
            self.journal.record(
                batch_id, "move", src, destination, category=item.category,
                size=item.size, status="error", error=str(exc),
            )
            self._error_hook(item, exc, batch_id)
            return entry

        final, reason = self._resolve_conflict(src, destination, batch_id)
        if final is None:
            entry.update(status="skipped", reason=reason)
            self.journal.record(
                batch_id,
                "skip",
                src,
                destination,
                category=item.category,
                size=item.size,
                status="skipped",
                error=reason,
            )
            return entry

        values = {
            "source": str(src),
            "dest": str(final),
            "category": item.category,
            "size": item.size,
            "batch": batch_id,
        }
        if self.hooks.enabled("before_move"):
            ok = self.hooks.run("before_move", values)
            if not ok and self.config.data.get("hooks", {}).get("fail_closed"):
                entry.update(status="skipped", reason="before_move hook failed")
                self.journal.record(
                    batch_id, "skip", src, final, category=item.category,
                    size=item.size, status="skipped", error=entry["reason"],
                )
                return entry

        try:
            shutil.move(str(src), str(final))
        except Exception as exc:  # noqa: BLE001 - record and continue with next file
            entry.update(status="failed", reason=str(exc))
            self.journal.record(
                batch_id, "move", src, final, category=item.category,
                size=item.size, status="error", error=str(exc),
            )
            self._error_hook(item, exc, batch_id)
            return entry

        entry.update(status="moved", destination=str(final), reason=reason)
        self.journal.record(
            batch_id,
            "move",
            src,
            final,
            category=item.category,
            size=item.size,
            digest=item.digest,
            status="ok",
        )
        if self.hooks.enabled("after_move"):
            self.hooks.run("after_move", values)
        return entry

    def _error_hook(self, item: PlanItem, exc: Exception, batch_id: str) -> None:
        if self.hooks.enabled("on_error"):
            self.hooks.run(
                "on_error",
                {
                    "source": str(item.src),
                    "dest": str(item.dst or ""),
                    "category": item.category,
                    "size": item.size,
                    "batch": batch_id,
                    "error": str(exc),
                },
            )

    def _quarantine_existing(self, existing: Path, batch_id: str, category: str = "") -> Path:
        try:
            size = existing.stat().st_size
        except OSError:
            size = 0
        target = quarantine_file(existing, self.config.quarantine_dir)
        self.journal.record(
            batch_id,
            "quarantine",
            existing,
            target,
            category=category,
            size=size,
            status="ok",
        )
        return target

    def _resolve_conflict(self, src: Path, destination: Path, batch_id: str) -> tuple[Path | None, str]:
        strategy = str(self.config.data.get("conflict") or "rename")
        use_trash = bool(self.config.data.get("use_trash"))
        if not destination.exists():
            return destination, ""

        if strategy == "skip":
            return None, "destination already exists"
        if strategy == "rename":
            return unique_path(destination.parent, destination.name), "renamed to avoid a conflict"
        if strategy == "trash":
            self._quarantine_existing(destination, batch_id)
            return destination, "replaced existing file (quarantined)"
        if strategy == "overwrite":
            if destination.is_dir() and not destination.is_symlink():
                return unique_path(destination.parent, destination.name), "destination is a folder; renamed"
            if use_trash:
                self._quarantine_existing(destination, batch_id)
                return destination, "replaced existing file (quarantined)"
            try:
                size = destination.stat().st_size
            except OSError:
                size = 0
            self.journal.record(
                batch_id, "delete", destination, None, size=size, status="ok"
            )
            try:
                destination.unlink()
            except OSError:
                return unique_path(destination.parent, destination.name), "could not replace; renamed"
            return destination, "replaced existing file"
        if strategy == "dedupe":
            if destination.is_file():
                try:
                    if destination.stat().st_size == src.stat().st_size:
                        digest = self._digest(src)
                        if digest and digest == self._digest(destination):
                            return None, "identical duplicate"
                except OSError:
                    pass
            return unique_path(destination.parent, destination.name), "content differs; renamed"
        if strategy in ("keep_newest", "keep_oldest"):
            try:
                existing_mtime = destination.stat().st_mtime
                src_mtime = src.stat().st_mtime
            except OSError:
                return unique_path(destination.parent, destination.name), "could not compare; renamed"
            if strategy == "keep_newest" and existing_mtime >= src_mtime:
                return None, "existing file is newer or equal"
            if strategy == "keep_oldest" and existing_mtime <= src_mtime:
                return None, "existing file is older or equal"
            if destination.is_dir() and not destination.is_symlink():
                return unique_path(destination.parent, destination.name), "destination is a folder; renamed"
            if use_trash:
                self._quarantine_existing(destination, batch_id)
                return destination, "replaced existing file (quarantined)"
            try:
                destination.unlink()
            except OSError:
                return unique_path(destination.parent, destination.name), "could not replace; renamed"
            return destination, "replaced existing file"
        return unique_path(destination.parent, destination.name), "renamed to avoid a conflict"

    def _cleanup_empty(self, start: Path, roots: Iterable[Path]) -> None:
        roots_resolved = {_key(root) for root in roots}
        current = start.resolve(strict=False)
        for _ in range(6):
            if _key(current) in roots_resolved:
                break
            if is_protected_root(current, self.config.data.get("protected_paths")):
                break
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
            except OSError:
                break
            current = current.parent

    # -------------------------------------------------------------------- undo
    def undo(
        self,
        *,
        count: int = 1,
        batch_id: str | None = None,
        dry_run: bool = False,
    ) -> UndoResult:
        batches, operations = self.journal.undo_candidates(count=count, batch_id=batch_id)
        result = UndoResult(
            batches=[batch["id"] for batch in batches],
            dry_run=dry_run,
        )
        if not operations:
            return result
        if dry_run:
            result.restored = [
                {
                    "source": op["dst"],
                    "destination": op["src"],
                    "size": op["size"],
                    "dry_run": True,
                }
                for op in operations
            ]
            return result

        data = self.config.data
        lock = (
            FileLock(
                self.paths.lock_file,
                timeout=float(data.get("lock_timeout") or 0),
                stale_after=float(data.get("lock_stale_seconds") or 3600),
            )
            if data.get("lock_enabled", True)
            else None
        )
        context = lock if lock else _NullLock()
        with context:
            undo_batch = self.journal.start_batch(
                mode="undo",
                dry_run=False,
                profile=self.config.profile,
                note=f"undo of {', '.join(result.batches) or 'batch'}",
                total=len(operations),
            )
            for op in operations:
                source = Path(op["dst"]) if op.get("dst") else None
                target = Path(op["src"])
                if source is None or not source.exists():
                    result.skipped.append(
                        {"source": str(source), "destination": str(target), "reason": "file no longer exists"}
                    )
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    final = target if not target.exists() else unique_path(target.parent, target.name)
                    shutil.move(str(source), str(final))
                except Exception as exc:  # noqa: BLE001
                    result.failed.append(
                        {"source": str(source), "destination": str(target), "reason": str(exc)}
                    )
                    continue
                self.journal.mark_undone(int(op["id"]))
                self.journal.record(
                    undo_batch,
                    "restore",
                    source,
                    final,
                    category=op.get("category") or "",
                    size=op.get("size") or 0,
                    status="ok",
                )
                result.restored.append(
                    {
                        "source": str(source),
                        "destination": str(final),
                        "size": op.get("size") or 0,
                    }
                )
            self.journal.finish_batch(
                undo_batch,
                moved=len(result.restored),
                skipped=len(result.skipped),
                failed=len(result.failed),
                total=len(operations),
            )
        return result

    # ------------------------------------------------------------------ dedupe
    def scan_duplicates(
        self,
        paths: Iterable[str | os.PathLike[str]] | None = None,
        *,
        recursive: bool | None = None,
        on_error: ErrorCallback | None = None,
    ) -> list[DuplicateGroup]:
        roots = self._resolved_roots(paths)
        if not roots:
            raise JarError("no folders to scan for duplicates")
        candidates = scan_candidates(
            roots,
            self.config,
            self.engine,
            recursive=recursive,
            on_error=on_error,
        )
        return find_duplicates([candidate.path for candidate in candidates])

    def dedupe(
        self,
        groups: Iterable[DuplicateGroup],
        *,
        keep: str = "first",
        permanent: bool = False,
        dry_run: bool = False,
        progress: ProgressCallback | None = None,
    ) -> DedupeResult:
        groups = list(groups)
        result = DedupeResult(batch_id=None, dry_run=dry_run)
        if not groups:
            return result
        if dry_run:
            for group in groups:
                result.kept.append(str(choose_keeper(group, keep)))
                keeper = choose_keeper(group, keep)
                for path in group.files:
                    if path == keeper:
                        continue
                    result.removed.append(
                        {"source": str(path), "destination": None, "size": group.size}
                    )
                    result.bytes_reclaimed += group.size
            return result

        data = self.config.data
        lock = (
            FileLock(
                self.paths.lock_file,
                timeout=float(data.get("lock_timeout") or 0),
                stale_after=float(data.get("lock_stale_seconds") or 3600),
            )
            if data.get("lock_enabled", True)
            else None
        )
        context = lock if lock else _NullLock()
        with context:
            batch_id = self.journal.start_batch(
                mode="dedupe",
                profile=self.config.profile,
                note=f"keep={keep}",
                total=sum(max(0, len(group.files) - 1) for group in groups),
            )
            result.batch_id = batch_id
            total = sum(max(0, len(group.files) - 1) for group in groups)
            done = 0
            for group in groups:
                keeper = choose_keeper(group, keep)
                result.kept.append(str(keeper))
                for path in group.files:
                    if path == keeper:
                        continue
                    try:
                        if permanent:
                            path.unlink()
                            destination = None
                            action = "delete"
                        else:
                            destination = quarantine_file(path, self.config.quarantine_dir)
                            action = "trash"
                        self.journal.record(
                            batch_id,
                            action,
                            path,
                            destination,
                            category="Duplicates",
                            size=group.size,
                            digest=group.digest,
                            status="ok",
                        )
                        result.removed.append(
                            {
                                "source": str(path),
                                "destination": str(destination) if destination else None,
                                "size": group.size,
                            }
                        )
                        result.bytes_reclaimed += group.size
                    except Exception as exc:  # noqa: BLE001
                        result.failed.append({"source": str(path), "reason": str(exc)})
                    done += 1
                    if progress:
                        progress(done, total, f"duplicate: {path.name}")
            self.journal.finish_batch(
                batch_id,
                moved=len(result.removed),
                skipped=0,
                failed=len(result.failed),
                total=total,
            )
        return result

    # --------------------------------------------------------------- shortcuts
    def organize(
        self,
        paths: Iterable[str | os.PathLike[str]] | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> tuple[Plan, ExecutionResult]:
        plan = self.plan(paths)
        return plan, self.execute(plan, progress=progress)

    def stats(self) -> dict:
        return self.journal.stats()

    def close(self) -> None:
        self.journal.close()


class _NullLock:
    def __enter__(self) -> "_NullLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
