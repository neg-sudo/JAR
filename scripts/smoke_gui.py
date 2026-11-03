#!/usr/bin/env python3
"""Start the JAR desktop app, let it render, then close it.

This catches startup-order bugs that unit tests miss (for example a menu that
references tabs before the tabs exist).  On headless Linux run it under Xvfb:

    xvfb-run -a python scripts/smoke_gui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jar-gui-smoke-") as temporary:
        sandbox = Path(temporary)
        os.environ["JAR_CONFIG_DIR"] = str(sandbox / "config")
        os.environ["JAR_DATA_DIR"] = str(sandbox / "data")
        os.environ.setdefault("NO_COLOR", "1")

        from jar.gui.app import JarApp

        app = JarApp()
        app.root.after(750, app.root.destroy)
        app.root.mainloop()

    print("ok   desktop app started and closed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
