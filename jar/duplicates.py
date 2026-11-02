"""Duplicate detection and safe duplicate removal."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .trash import quarantine_file

CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """SHA-256 digest of a file, streamed in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class DuplicateGroup:
    digest: str
    size: int
    files: list[Path] = field(default_factory=list)

    @property
    def wasted_bytes(self) -> int:
        return self.size * max(0, len(self.files) - 1)

    def describe(self) -> dict:
        return {
            "digest": self.digest,
            "size": self.size,
            "wasted_bytes": self.wasted_bytes,
            "files": [str(path) for path in self.files],
        }


def find_duplicates(
    files: Iterable[Path],
    *,
    include_empty: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> list[DuplicateGroup]:
    """Find byte-identical files using size grouping then SHA-256.

    Files are only hashed when at least one other file shares their size, which
    keeps large scans fast.
    """
    by_size: dict[int, list[Path]] = {}
    for raw in files:
        path = Path(raw)
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        if stat_result.st_size == 0 and not include_empty:
            continue
        by_size.setdefault(stat_result.st_size, []).append(path)

    candidates = [paths for paths in by_size.values() if len(paths) > 1]
    total = sum(len(paths) for paths in candidates)
    done = 0
    groups: dict[tuple[int, str], DuplicateGroup] = {}

    for paths in sorted(candidates, key=len, reverse=True):
        for path in sorted(paths, key=str):
            digest = ""
            try:
                stat_size = path.stat().st_size
                digest = file_digest(path)
            except OSError:
                done += 1
                if progress:
                    progress(done, total)
                continue
            key = (stat_size, digest)
            group = groups.get(key)
            if group is None:
                groups[key] = DuplicateGroup(digest=digest, size=key[0], files=[path])
            else:
                group.files.append(path)
            done += 1
            if progress:
                progress(done, total)

    result = [group for group in groups.values() if len(group.files) > 1]
    result.sort(key=lambda group: (-group.wasted_bytes, str(group.files[0])))
    return result


def choose_keeper(group: DuplicateGroup, strategy: str = "first") -> Path:
    """Pick the file to keep according to *strategy*."""
    files = sorted(group.files, key=str)
    if strategy == "oldest":
        return min(files, key=lambda p: (p.stat().st_mtime, str(p)))
    if strategy == "newest":
        return max(files, key=lambda p: (p.stat().st_mtime, str(p)))
    if strategy == "shortest":
        return min(files, key=lambda p: (len(str(p)), str(p)))
    return files[0]


@dataclass
class RemovalResult:
    removed: list[tuple[Path, Path | None]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return len(self.removed)


def remove_duplicates(
    groups: Iterable[DuplicateGroup],
    *,
    keep: str = "first",
    dry_run: bool = True,
    use_trash: bool = True,
    quarantine_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RemovalResult:
    """Remove all but one file per duplicate group.

    By default files are moved to quarantine (undoable).  When ``use_trash`` is
    false the files are deleted permanently.
    """
    groups = list(groups)
    total = sum(max(0, len(group.files) - 1) for group in groups)
    done = 0
    result = RemovalResult()

    for group in groups:
        keeper = choose_keeper(group, keep)
        result.kept.append(keeper)
        for path in group.files:
            if path == keeper:
                continue
            if dry_run:
                result.removed.append((path, None))
            else:
                try:
                    if use_trash and quarantine_dir:
                        target = quarantine_file(path, Path(quarantine_dir))
                        result.removed.append((path, target))
                    elif use_trash:
                        from send2trash import send2trash

                        send2trash(str(path))
                        result.removed.append((path, None))
                    else:
                        os.remove(path)
                        result.removed.append((path, None))
                except Exception as exc:  # noqa: BLE001 - report per file
                    result.failed.append((path, str(exc)))
            done += 1
            if progress:
                progress(done, total)
    return result
