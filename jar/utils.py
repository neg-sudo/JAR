"""Small, dependency-free helpers shared by the CLI, GUI and engine."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence


_UNITS = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}

_DURATION_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}


def human_size(num: float | int | None) -> str:
    """Format a byte count as a compact human readable string."""
    if num is None:
        return "-"
    num = float(num)
    if num < 0:
        return "-" + human_size(-num)
    if num < 1024:
        return f"{int(num)} B"
    for unit in ("KB", "MB", "GB", "TB", "PB"):
        num /= 1024.0
        if num < 1024 or unit == "PB":
            return f"{num:.1f} {unit}".replace(".0 ", " ")
    return f"{num:.1f} PB"


def parse_size(value: str | int | None) -> int:
    """Parse ``'10MB'``/``'512k'``/``'1024'`` into bytes.

    Raises ``ValueError`` for malformed input.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower().replace("_", "")
    if not text:
        return 0
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([a-z]*)", text)
    if not match:
        raise ValueError(f"invalid size: {value!r}")
    number = float(match.group(1))
    unit = match.group(2) or "b"
    if unit not in _UNITS:
        raise ValueError(f"unknown size unit: {unit!r}")
    return int(number * _UNITS[unit])


def parse_duration(value: str | int | float | None) -> int:
    """Parse ``'30s'``/``'5m'``/``'2h'``/``'1d'`` into seconds."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower()
    if not text:
        return 0
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([a-z]*)", text)
    if not match:
        raise ValueError(f"invalid duration: {value!r}")
    number = float(match.group(1))
    unit = match.group(2) or "s"
    if unit not in _DURATION_UNITS:
        raise ValueError(f"unknown duration unit: {unit!r}")
    return int(number * _DURATION_UNITS[unit])


def human_duration(seconds: float | int | None) -> str:
    """Format seconds as ``1d 2h 3m`` style text."""
    if seconds is None:
        return "-"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    parts: list[str] = []
    for label, unit in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    if seconds and len(parts) < 3:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def format_ts(ts: float | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not ts:
        return "-"
    return time.strftime(fmt, time.localtime(ts))


def now_ts() -> float:
    return time.time()


def deep_get(data: dict, dotted: str, default: Any = None) -> Any:
    """Read ``a.b.c`` from nested dictionaries."""
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def deep_set(data: dict, dotted: str, value: Any) -> None:
    """Write ``a.b.c`` into nested dictionaries, creating levels as needed."""
    parts = dotted.split(".")
    current = data
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def deep_unset(data: dict, dotted: str) -> bool:
    parts = dotted.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]
        return True
    return False


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write *text* atomically so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


def truncate(text: Any, width: int, marker: str = "...") -> str:
    text = str(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(marker):
        return text[:width]
    return text[: width - len(marker)] + marker


def truncate_middle(text: str, width: int, marker: str = "...") -> str:
    """Keep the start and end of a path-like string readable."""
    if width <= 0 or len(text) <= width:
        return text
    if width <= len(marker) * 2:
        return text[:width]
    side = (width - len(marker)) // 2
    return text[:side] + marker + text[-(width - len(marker) - side):]


def format_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    max_widths: Sequence[int] | None = None,
) -> str:
    """Render a simple aligned text table without third-party dependencies."""
    rows = [["" if cell is None else str(cell) for cell in row] for row in rows]
    if not rows:
        return ""
    widths = [len(str(header)) for header in headers]
    limits = list(max_widths) if max_widths else [0] * len(headers)
    for row in rows:
        for idx in range(min(len(row), len(widths))):
            widths[idx] = max(widths[idx], len(row[idx]))
    for idx, limit in enumerate(limits):
        if limit and idx < len(widths):
            widths[idx] = min(widths[idx], limit)

    def render(row: Sequence[str]) -> str:
        cells = []
        for idx, width in enumerate(widths):
            value = truncate(row[idx] if idx < len(row) else "", width)
            cells.append(value.ljust(width))
        return "  ".join(cells).rstrip()

    lines = [render([str(h) for h in headers])]
    lines.append("  ".join("-" * width for width in widths).rstrip())
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def normalize_text(value: str) -> str:
    """Unicode-normalize and collapse whitespace without changing meaning."""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def guess_text_encoding(path: Path) -> str:
    """Best-effort encoding for ignore files."""
    try:
        raw = Path(path).read_bytes()[:4096]
    except OSError:
        return "utf-8"
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def expand_path(value: str | os.PathLike[str] | None, base: Path | None = None) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(os.path.expandvars(str(value))).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path


def path_is_within(child: Path, parent: Path) -> bool:
    """Return True when *child* is inside *parent* (or equal to it)."""
    try:
        child = Path(child).resolve(strict=False)
        parent = Path(parent).resolve(strict=False)
    except OSError:
        return False
    if child == parent:
        return True
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def first_existing(paths: Sequence[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None
