#!/usr/bin/env python3
"""Package the PyInstaller output into a release archive.

Examples
--------
    python scripts/package_release.py
    python scripts/package_release.py --dist dist --output release
    python scripts/package_release.py --platform linux --arch x86_64
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jar.version import __version__  # noqa: E402

DOC_FILES = ("README.md", "FEATURES.md", "CHANGELOG.md", "LICENSE", "CONTRIBUTING.md")

PLATFORM_ALIASES = {
    "win32": "windows",
    "windows": "windows",
    "darwin": "macos",
    "macos": "macos",
    "mac": "macos",
    "linux": "linux",
    "linux2": "linux",
}

ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "x64": "x86_64",
    "i386": "x86",
    "i686": "x86",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv8": "arm64",
}


def normalize_platform(value: str) -> str:
    return PLATFORM_ALIASES.get(value.lower(), value.lower())


def normalize_arch(value: str) -> str:
    return ARCH_ALIASES.get(value.lower(), value.lower())


def find_binaries(dist: Path) -> list[Path]:
    """Return release binaries in a stable order, skipping debug files."""
    expected = [
        dist / "jar",
        dist / "jar.exe",
        dist / "jar-desktop",
        dist / "jar-desktop.exe",
        dist / "JAR.app",
    ]
    found = [path for path in expected if path.exists()]
    if not found:
        raise SystemExit(f"no JAR binaries found in {dist}; run PyInstaller first")
    return found


def copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    else:
        shutil.copy2(source, target)


def build_staging(dist: Path, staging: Path) -> Path:
    payload = staging / "jar"
    payload.mkdir(parents=True, exist_ok=True)
    for binary in find_binaries(dist):
        copy_tree(binary, payload / binary.name)
    for name in DOC_FILES:
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, payload / name)
    return payload


def make_zip(payload: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(payload.parent))


def make_tar(payload: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(payload, arcname=payload.name)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(archives: list[Path], output: Path) -> Path:
    target = output / "SHA256SUMS.txt"
    lines = [f"{sha256(archive)}  {archive.name}" for archive in archives]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--output", default=str(ROOT / "release"))
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--arch", default=platform.machine() or "unknown")
    parser.add_argument(
        "--format",
        choices=("zip", "tar.gz", "auto"),
        default="auto",
        help="archive format (auto: zip except Linux, which uses tar.gz)",
    )
    args = parser.parse_args(argv)

    dist = Path(args.dist).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    target_platform = normalize_platform(args.platform)
    target_arch = normalize_arch(args.arch)
    archive_format = args.format
    if archive_format == "auto":
        archive_format = "tar.gz" if target_platform == "linux" else "zip"

    suffix = ".tar.gz" if archive_format == "tar.gz" else ".zip"
    base = f"jar-{args.version}-{target_platform}-{target_arch}"
    archive = output / f"{base}{suffix}"

    with tempfile.TemporaryDirectory(prefix="jar-release-") as temporary:
        staging = Path(temporary)
        payload = build_staging(dist, staging)
        if archive_format == "zip":
            make_zip(payload, archive)
        else:
            make_tar(payload, archive)

    checksums = write_checksums([archive], output)
    print(f"built {archive} ({archive.stat().st_size} bytes)")
    print(f"checksums written to {checksums}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
