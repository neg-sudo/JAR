"""Path safety, filename hygiene and a cross-platform single-instance lock."""

from __future__ import annotations

import errno
import os
import platform
import re
import time
import unicodedata
from pathlib import Path

from .errors import LockError, SafetyError
from .utils import normalize_text, path_is_within

WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

# Roots that must never be organized directly.  Files *inside* these roots are
# still fine (for example /home/user/Downloads); it is the root itself that is
# protected from being used as a watch/destination root or removed as "empty".
DEFAULT_PROTECTED_ROOTS = [
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/opt",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
    "C:\\",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
    "C:\\Users",
]


def protected_roots(extra: list[str] | None = None) -> list[Path]:
    roots = [Path(value) for value in DEFAULT_PROTECTED_ROOTS]
    for value in extra or []:
        try:
            roots.append(Path(value).expanduser())
        except (OSError, ValueError):
            continue
    return roots


def is_protected_root(path: Path | str, extra: list[str] | None = None) -> bool:
    """True when *path* itself is a protected filesystem root."""
    try:
        candidate = Path(path).expanduser().resolve(strict=False)
    except OSError:
        return False
    home = Path.home().resolve(strict=False)
    if candidate == home:
        return True
    if candidate.parent == candidate:  # filesystem root
        return True
    for root in protected_roots(extra):
        try:
            if candidate == root.expanduser().resolve(strict=False):
                return True
        except OSError:
            continue
    return False


def ensure_safe_destination(destination: Path, root: Path) -> Path:
    """Refuse destinations that escape their base root via ``..`` or a symlink."""
    destination = Path(destination)
    if not path_is_within(destination, root):
        raise SafetyError(f"destination escapes its root: {destination}")
    return destination


def sanitize_filename(name: str, replacement: str = "_", max_length: int = 200) -> str:
    """Make a single filename safe on Windows, macOS and Linux."""
    path = Path(name)
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name

    forbidden = r'<>:"/\\|?*\x00-\x1f\x7f'
    stem = re.sub(f"[{forbidden}]", replacement, stem)
    suffix = re.sub(f"[{forbidden}]", "", suffix)
    stem = re.sub(re.escape(replacement) + r"{2,}", replacement, stem).strip(" .")
    if not stem:
        stem = "file"
    if stem.lower() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    suffix = suffix.rstrip(" .")
    limit = max(8, int(max_length))
    room = limit - len(suffix)
    if room < 1:
        suffix = ""
        room = limit
    stem = stem[:room]
    return f"{stem}{suffix}"


def normalize_filename(name: str, lowercase: bool = False) -> str:
    """Unicode-normalize and tidy whitespace in a filename."""
    path = Path(name)
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    stem = normalize_text(stem)
    if lowercase:
        stem = stem.lower()
    return f"{stem}{suffix}"


def apply_name_policy(
    name: str,
    *,
    sanitize: bool = False,
    normalize: bool = False,
    lowercase: bool = False,
    max_length: int = 200,
) -> str:
    """Apply the configured filename transforms in a stable order."""
    result = name
    if normalize:
        result = normalize_filename(result, lowercase=lowercase)
    elif lowercase:
        result = normalize_filename(result, lowercase=True)
    if sanitize:
        result = sanitize_filename(result, max_length=max_length)
    return result


def is_hidden_name(name: str) -> bool:
    return name.startswith(".") and name not in {".", ".."}


def is_hidden_path(path: Path) -> bool:
    """Cross-platform hidden check (dotfiles plus Windows attributes)."""
    if any(part.startswith(".") for part in Path(path).parts if part not in ("/", "\\")):
        return True
    if platform.system() == "Windows":
        try:
            import stat as stat_module

            attrs = os.stat(path).st_file_attributes
            return bool(attrs & stat_module.FILE_ATTRIBUTE_HIDDEN)
        except (OSError, AttributeError):
            return False
    return False


def process_is_alive(pid: int) -> bool:
    """Return True when *pid* exists, without ever signalling the process.

    ``os.kill(pid, 0)`` is safe on POSIX but on Windows Python forwards any
    non-console signal to ``TerminateProcess``.  That would kill an unrelated
    process during stale-lock detection, so Windows uses ``OpenProcess``.
    """
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                # Access denied still means the process exists.
                return kernel32.GetLastError() == 5
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - never let lock checks crash a run
            return True
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    except Exception:  # noqa: BLE001
        return True
    return True


def unique_path(destination: Path, name: str | None = None) -> Path:
    """Return a non-existing path inside *destination* using ``name (1).ext``."""
    destination = Path(destination)
    name = name or "file"
    candidate = destination / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    while True:
        candidate = destination / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class FileLock:
    """A tiny, dependency-free single-instance lock based on ``O_EXCL``.

    A stale lock (dead process or older than ``stale_after`` seconds) is
    reclaimed automatically so a crashed run never blocks the user forever.
    """

    def __init__(self, path: Path, timeout: float = 0, stale_after: float = 3600):
        self.path = Path(path)
        self.timeout = max(0.0, float(timeout))
        self.stale_after = max(0.0, float(stale_after))
        self._fd: int | None = None
        self._owned = False

    def _read_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8").strip()
            return int(text.split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return True
        if self.stale_after and age > self.stale_after:
            return True
        pid = self._read_pid()
        if pid is None:
            return True
        if pid == os.getpid():
            return False
        return not process_is_alive(pid)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, f"{os.getpid()} {int(time.time())}\n".encode("utf-8"))
                os.fsync(fd)
                os.close(fd)
                self._owned = True
                return
            except FileExistsError:
                if self._is_stale():
                    try:
                        self.path.unlink()
                        continue
                    except OSError:
                        pass
                if time.monotonic() >= deadline:
                    raise LockError(
                        f"another JAR process is already running (lock: {self.path}). "
                        "Wait for it to finish or delete the lock file if it is stale."
                    )
                time.sleep(0.1)
            except OSError as exc:
                raise LockError(f"cannot create lock {self.path}: {exc}") from exc

    def release(self) -> None:
        if self._owned:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            self._owned = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
