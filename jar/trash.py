"""Quarantine and system-trash helpers.

Quarantine is JAR's own undo-friendly bin.  Files are stored with a timestamp
prefix so identical names never collide, and the original path is also written
to the journal by the organizer.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .safety import unique_path
from .utils import path_is_within


def _timestamp() -> str:
    now = time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int(now * 1000) % 1000:03d}"


def quarantine_file(path: Path, quarantine_dir: Path, reason: str = "") -> Path:
    """Move *path* into quarantine and return its new location."""
    path = Path(path)
    root = Path(quarantine_dir)
    day = time.strftime("%Y-%m-%d", time.localtime())
    destination_dir = root / day
    destination_dir.mkdir(parents=True, exist_ok=True)
    name = f"{_timestamp()}__{path.name}"
    target = unique_path(destination_dir, name)
    if path.is_dir() and not path.is_symlink():
        shutil.move(str(path), str(target))
    else:
        shutil.move(str(path), str(target))
    return target


def send_to_system_trash(path: Path) -> bool:
    """Send to the OS trash when Send2Trash is installed."""
    try:
        from send2trash import send2trash
    except ImportError:
        return False
    try:
        send2trash(str(path))
        return True
    except Exception:  # noqa: BLE001 - optional integration
        return False


def delete_path(path: Path, *, use_trash: bool, quarantine_dir: Path | None = None) -> Path | None:
    """Delete a file using the best available safe mechanism.

    Returns the quarantine path when the file was moved there, otherwise None.
    """
    path = Path(path)
    if use_trash and quarantine_dir:
        return quarantine_file(path, quarantine_dir)
    if use_trash and send_to_system_trash(path):
        return None
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return None


def list_quarantine(quarantine_dir: Path) -> list[dict]:
    root = Path(quarantine_dir)
    if not root.exists():
        return []
    items: list[dict] = []
    for current, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(current) / filename
            try:
                stat_result = path.stat()
            except OSError:
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
            items.append(
                {
                    "name": relative,
                    "path": str(path),
                    "size": stat_result.st_size,
                    "mtime": stat_result.st_mtime,
                }
            )
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


def resolve_quarantine_item(quarantine_dir: Path, name: str) -> Path:
    root = Path(quarantine_dir).resolve(strict=False)
    candidate = (root / name).resolve(strict=False)
    if not path_is_within(candidate, root) or candidate == root:
        raise ValueError(f"quarantine item escapes the quarantine folder: {name}")
    if not candidate.is_file() and not candidate.is_symlink():
        raise FileNotFoundError(f"quarantine item not found: {name}")
    return candidate


def restore_quarantine_item(
    quarantine_dir: Path,
    name: str,
    destination_dir: Path,
    *,
    overwrite: bool = False,
) -> Path:
    source = resolve_quarantine_item(quarantine_dir, name)
    destination_dir = Path(destination_dir).expanduser()
    destination_dir.mkdir(parents=True, exist_ok=True)
    # Strip the timestamp prefix to recover the original filename.
    original_name = source.name
    if "__" in original_name:
        prefix, rest = original_name.split("__", 1)
        if prefix and prefix.replace("-", "").isdigit() and rest:
            original_name = rest
    target = destination_dir / original_name
    if target.exists() and not overwrite:
        target = unique_path(destination_dir, original_name)
    shutil.move(str(source), str(target))
    return target


def purge_quarantine(quarantine_dir: Path, older_than_seconds: int, *, dry_run: bool = False) -> list[Path]:
    """Delete quarantine items older than *older_than_seconds*."""
    root = Path(quarantine_dir)
    cutoff = time.time() - max(0, older_than_seconds)
    removed: list[Path] = []
    for item in list_quarantine(root):
        if older_than_seconds and item["mtime"] > cutoff:
            continue
        path = Path(item["path"])
        removed.append(path)
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
    if not dry_run:
        for current, dirnames, filenames in os.walk(root, topdown=False):
            if not dirnames and not filenames:
                try:
                    Path(current).rmdir()
                except OSError:
                    pass
    return removed
