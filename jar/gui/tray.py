"""Optional system tray integration for the JAR desktop app."""

from __future__ import annotations

import threading
from pathlib import Path

try:
    import pystray
    from PIL import Image
    TRAY_OK = True
except ImportError:  # pragma: no cover - optional dependency
    pystray = None
    Image = None
    TRAY_OK = False


def _icon_image():
    path = Path(__file__).resolve().parent.parent / "assets" / "jar-tray.png"
    if Image is not None and path.exists():
        try:
            return Image.open(path)
        except OSError:
            pass
    if Image is None:
        return None
    image = Image.new("RGB", (64, 64), color=(15, 23, 42))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 10, 50, 54), radius=6, fill=(74, 222, 128))
    draw.rounded_rectangle((20, 4, 44, 14), radius=4, fill=(34, 197, 94))
    return image


class TrayIcon:
    """A small pystray wrapper that must be started while the Tk loop runs."""

    def __init__(self, app, title: str = "JAR"):
        if not TRAY_OK:
            raise ImportError("pystray and Pillow are required for the tray icon")
        self.app = app
        menu = pystray.Menu(
            pystray.MenuItem("Show JAR", self._show, default=True),
            pystray.MenuItem("Organize (dry run)", self._organize),
            pystray.MenuItem("Undo last batch", self._undo),
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon("jar", _icon_image(), title, menu)
        self._thread: threading.Thread | None = None

    def _call(self, method: str) -> None:
        try:
            getattr(self.app, method)()
        except Exception:
            pass

    def _show(self, icon, item) -> None:
        self.stop()
        self._call("show_from_tray")

    def _organize(self, icon, item) -> None:
        self._call("run_organize")
        self._call("show_from_tray")

    def _undo(self, icon, item) -> None:
        self._call("undo_last")
        self._call("show_from_tray")

    def _quit(self, icon, item) -> None:
        self.stop()
        self._call("on_close")

    def start(self) -> None:
        self._thread = threading.Thread(target=self.icon.run, name="jar-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
