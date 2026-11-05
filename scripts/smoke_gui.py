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
import time
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
        app.root.update_idletasks()
        app.root.update()

        tabs = {
            "Overview": app.tab_overview,
            "Organize": app.tab_organize,
            "Watch": app.tab_watch,
            "Rules": app.tab_rules,
            "Duplicates": app.tab_duplicates,
            "Quarantine": app.tab_quarantine,
            "History": app.tab_history,
            "Stats & Reports": app.tab_stats,
            "Settings": app.tab_settings,
            "Doctor": app.tab_doctor,
        }
        for name, tab in tabs.items():
            if hasattr(app.notebook, "set"):
                app.notebook.set(name)
                # CTkTabview hides the previous tab via after(100, ...).
                deadline = time.monotonic() + 0.2
                while time.monotonic() < deadline:
                    app.root.update()
                    time.sleep(0.02)
            else:
                app.notebook.select(tab)
            app.root.update_idletasks()
            app.root.update()
            visible = [
                child
                for child in tab.winfo_children()
                if child.winfo_ismapped()
                and child.winfo_width() > 20
                and child.winfo_height() > 20
            ]
            if not visible:
                raise SystemExit(f"tab {name!r} has no visible content")
            print(f"ok   tab {name}")

        app.root.after(750, app.root.destroy)
        app.mainloop()

    print("ok   desktop app started and closed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
