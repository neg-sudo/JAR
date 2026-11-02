"""Best-effort desktop notifications with no hard dependency."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess

log = logging.getLogger("jar.notify")


def _run(command: list[str]) -> bool:
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def send(title: str, message: str, *, enabled: bool = True) -> bool:
    """Show a desktop notification when the platform supports it."""
    if not enabled:
        return False
    system = platform.system()
    if system == "Linux":
        if shutil.which("notify-send"):
            return _run(["notify-send", "--app-name=JAR", str(title), str(message)])
        return False
    if system == "Darwin":
        if shutil.which("osascript"):
            script = (
                f'display notification {message!r} with title {title!r}'
            )
            return _run(["osascript", "-e", script])
        return False
    if system == "Windows":
        if shutil.which("powershell"):
            safe_title = str(title).replace("'", "''")
            safe_message = str(message).replace("'", "''")
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] > $null; "
                "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                f"$template.GetElementsByTagName('text')[0].AppendChild($template.CreateTextNode('{safe_title}')) > $null; "
                f"$template.GetElementsByTagName('text')[1].AppendChild($template.CreateTextNode('{safe_message}')) > $null; "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('JAR').Show($toast)"
            )
            return _run(["powershell", "-NoProfile", "-Command", script])
    return False


def notify_summary(moved: int, skipped: int, failed: int, bytes_moved: int, *, enabled: bool = True) -> bool:
    from .utils import human_size

    if not enabled:
        return False
    title = "JAR finished"
    parts = [f"{moved} moved", f"{human_size(bytes_moved)} routed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if failed:
        parts.append(f"{failed} failed")
    return send(title, " - ".join(parts), enabled=enabled)
