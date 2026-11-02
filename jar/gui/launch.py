"""Launch the JAR desktop app (used by the ``jar-desktop`` entry point)."""

from __future__ import annotations

from ..config import Config
from .app import launch


def main() -> None:
    launch(Config())


if __name__ == "__main__":
    main()
