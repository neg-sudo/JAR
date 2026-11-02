#!/usr/bin/env python3
"""Write one SHA256SUMS.txt covering every release archive in a directory.

Release builds are produced on separate runners, so each uploads its own
single-line checksum file and they overwrite each other when artifacts are
merged.  The publish job runs this script after downloading every archive so
the published checksum file covers all platforms.

    python scripts/checksums.py release
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_archives(directory: Path) -> list[Path]:
    suffixes = (".zip", ".tar.gz", ".tgz")
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.endswith(suffixes)
    )


def write_checksums(directory: Path) -> Path:
    archives = find_archives(directory)
    if not archives:
        raise SystemExit(f"no release archives found in {directory}")
    target = directory / "SHA256SUMS.txt"
    lines = [f"{sha256(archive)}  {archive.name}" for archive in archives]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="release",
        help="directory containing release archives (default: release)",
    )
    args = parser.parse_args(argv)
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise SystemExit(f"not a directory: {directory}")
    target = write_checksums(directory)
    print(target.read_text(encoding="utf-8"), end="")
    print(f"checksums written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
