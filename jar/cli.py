"""JAR command line interface."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from . import APP_NAME, APP_TAGLINE, __version__
from .config import CONFLICT_STRATEGIES, Config, MODES
from .duplicates import DuplicateGroup, choose_keeper
from .errors import ConfigError, JarError
from .journal import Journal
from .logging_setup import configure_logging
from .notify import send as send_notification
from .organizer import Organizer, Plan
from .reports import export_report, report_text
from .rules import RuleEngine, custom_rules, normalize_extension
from .safety import FileLock, is_protected_root
from .scanner import scan_candidates
from .trash import list_quarantine, purge_quarantine, restore_quarantine_item
from .utils import (
    format_table,
    format_ts,
    human_duration,
    human_size,
    parse_duration,
    parse_size,
    path_is_within,
    split_csv,
    truncate,
    truncate_middle,
)

COMMANDS = [
    "organize", "watch", "scan", "stats", "history", "undo", "duplicates",
    "quarantine", "rules", "config", "doctor", "completions", "autostart",
    "gui", "version",
]


# --------------------------------------------------------------------------- UI
class Colors:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _style(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._style(text, "1")
    def dim(self, text: str) -> str:
        return self._style(text, "2")
    def red(self, text: str) -> str:
        return self._style(text, "31")
    def green(self, text: str) -> str:
        return self._style(text, "32")
    def yellow(self, text: str) -> str:
        return self._style(text, "33")
    def blue(self, text: str) -> str:
        return self._style(text, "34")
    def cyan(self, text: str) -> str:
        return self._style(text, "36")


def _colors(args: argparse.Namespace) -> Colors:
    enabled = (
        sys.stdout.isatty()
        and not bool(getattr(args, "no_color", False))
        and not os.environ.get("NO_COLOR")
    )
    return Colors(enabled)


class Progress:
    """Single-line progress output that stays quiet for pipes/JSON."""

    def __init__(self, enabled: bool, width: int = 60):
        self.enabled = enabled
        self.width = width
        self._last = ""

    def __call__(self, done: int, total: int, message: str) -> None:
        if not self.enabled:
            return
        total = max(1, int(total))
        text = f"[{done}/{total}] {message}"
        self._last = text
        print("\r" + truncate(text, self.width + 20).ljust(self.width + 20), end="", flush=True)
        if done >= total:
            print()


# ----------------------------------------------------------------------- parser
def _common() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default=None, help="path to config.json")
    parser.add_argument("--profile", default=None, help="configuration profile to use")
    parser.add_argument("--json", dest="json", action="store_true", default=None, help="machine-readable JSON output")
    parser.add_argument("-q", "--quiet", dest="quiet", action="store_true", default=None, help="only print errors")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=None, help="debug logging")
    parser.add_argument("--no-color", dest="no_color", action="store_true", default=None, help="disable ANSI colors")
    parser.add_argument("--dry-run", dest="dry_run", action=argparse.BooleanOptionalAction, default=None, help="preview without changing files")
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="jar",
        description=f"{APP_NAME} {__version__} - {APP_TAGLINE}. Organize files from the terminal or the desktop.",
        epilog=(
            "Examples:\n"
            "  jar organize ~/Downloads --dry-run\n"
            "  jar organize ~/Downloads --recursive --conflict dedupe\n"
            "  jar watch ~/Downloads --existing\n"
            "  jar duplicates ~/Downloads --trash --keep oldest\n"
            "  jar undo --last 2\n"
            "  jar stats --export report.md\n"
            "  jar gui\n\n"
            f"Run 'jar <command> --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} ({APP_TAGLINE})")
    # Global copies so both `jar --json stats` and `jar stats --json` work.
    parser.add_argument("--config", dest="g_config", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--profile", dest="g_profile", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json", dest="g_json", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("-q", "--quiet", dest="g_quiet", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", dest="g_verbose", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("--no-color", dest="g_no_color", action="store_true", default=False, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # organize ---------------------------------------------------------------
    p = sub.add_parser("organize", aliases=["org"], parents=[common], help="organize files now")
    p.add_argument("paths", nargs="*", help="folders or files (default: configured watch folders)")
    p.add_argument("-r", "--recursive", dest="recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--mode", choices=MODES, default=None)
    p.add_argument("--dest", "--dest-root", dest="dest", default=None, help="global destination root")
    p.add_argument("--conflict", choices=CONFLICT_STRATEGIES, default=None)
    p.add_argument("--min-age", default=None, help="only files older than e.g. 5m, 2h, 1d")
    p.add_argument("--max-age", default=None, help="only files newer than e.g. 30d")
    p.add_argument("--min-size", default=None, help="minimum file size, e.g. 10KB")
    p.add_argument("--max-size", default=None, help="maximum file size, e.g. 2GB")
    p.add_argument("--category", action="append", default=None, help="only this category (repeatable)")
    p.add_argument("--exclude-category", action="append", default=None)
    p.add_argument("--trash", dest="use_trash", action=argparse.BooleanOptionalAction, default=None, help="quarantine replaced files")
    p.add_argument("--cleanup-empty", dest="cleanup_empty", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--follow-symlinks", dest="follow_symlinks", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--sanitize-names", dest="sanitize_names", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--normalize-names", dest="normalize_names", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--date-subfolders", dest="date_subfolders", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--notify", dest="notifications", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--all", action="store_true", help="show every planned row")
    p.set_defaults(func=cmd_organize)

    # watch ------------------------------------------------------------------
    p = sub.add_parser("watch", parents=[common], help="watch folders and organize new files")
    p.add_argument("paths", nargs="*", help="folders to watch (default: configured watch folders)")
    p.add_argument("--interval", default=None, help="poll interval in seconds (default: 2)")
    p.add_argument("--stability", default=None, help="seconds a file must stay unchanged (default: 2)")
    p.add_argument("--existing", action="store_true", help="also organize files already present at startup")
    p.add_argument("--once", action="store_true", help="run a single organize pass and exit")
    p.add_argument("-r", "--recursive", dest="recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--conflict", choices=CONFLICT_STRATEGIES, default=None)
    p.add_argument("--mode", choices=MODES, default=None)
    p.add_argument("--dest", "--dest-root", dest="dest", default=None)
    p.set_defaults(func=cmd_watch)

    # scan -------------------------------------------------------------------
    p = sub.add_parser("scan", parents=[common], help="preview what would happen")
    p.add_argument("paths", nargs="*")
    p.add_argument("-r", "--recursive", dest="recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--category", action="append", default=None)
    p.add_argument("--stats", action="store_true", help="show a category summary")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_scan)

    # stats ------------------------------------------------------------------
    p = sub.add_parser("stats", parents=[common], help="show activity statistics")
    p.add_argument("--export", default=None, help="write a report (.json, .csv, .md)")
    p.add_argument("--format", default=None, help="report format when exporting")
    p.set_defaults(func=cmd_stats)

    # history ----------------------------------------------------------------
    p = sub.add_parser("history", parents=[common], help="show operation history")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--batch", default=None, help="filter by batch id")
    p.add_argument("--search", default=None, help="search paths, categories and errors")
    p.add_argument("--batches", action="store_true", help="show batches instead of operations")
    p.add_argument("--clear", action="store_true", help="delete all history")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(func=cmd_history)

    # undo -------------------------------------------------------------------
    p = sub.add_parser("undo", parents=[common], help="undo the last organize/dedupe batch")
    p.add_argument("--last", type=int, default=1, help="number of batches to undo (default: 1)")
    p.add_argument("--batch", default=None, help="undo a specific batch id")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(func=cmd_undo)

    # duplicates -------------------------------------------------------------
    p = sub.add_parser("duplicates", aliases=["dupes"], parents=[common], help="find or remove duplicate files")
    p.add_argument("paths", nargs="*")
    p.add_argument("-r", "--recursive", dest="recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--min-age", default=None, help="only consider files older than e.g. 1d")
    p.add_argument("--max-age", default=None)
    p.add_argument("--min-size", default=None)
    p.add_argument("--max-size", default=None)
    p.add_argument("--keep", choices=["first", "oldest", "newest", "shortest"], default="first")
    p.add_argument("--trash", dest="trash", action="store_true", help="quarantine duplicates (undoable)")
    p.add_argument("--delete", dest="delete", action="store_true", help="delete duplicates permanently")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(func=cmd_duplicates)

    # quarantine -------------------------------------------------------------
    p = sub.add_parser("quarantine", aliases=["q"], parents=[common], help="inspect or restore quarantined files")
    qsub = p.add_subparsers(dest="quarantine_action", required=True)
    qp = qsub.add_parser("list", parents=[common], help="list quarantined files")
    qp.add_argument("--limit", type=int, default=50)
    qp.set_defaults(func=cmd_quarantine_list)
    qp = qsub.add_parser("restore", parents=[common], help="restore a quarantined file")
    qp.add_argument("name", help="relative name from 'jar quarantine list'")
    qp.add_argument("--to", default=None, help="destination folder (default: current folder)")
    qp.add_argument("--force", action="store_true", help="overwrite an existing file")
    qp.set_defaults(func=cmd_quarantine_restore)
    qp = qsub.add_parser("purge", parents=[common], help="delete old quarantined files")
    qp.add_argument("--older-than", default="30d", help="age threshold (default: 30d)")
    qp.add_argument("--yes", "-y", action="store_true")
    qp.set_defaults(func=cmd_quarantine_purge)

    # rules ------------------------------------------------------------------
    p = sub.add_parser("rules", parents=[common], help="list, test and edit rules")
    rsub = p.add_subparsers(dest="rules_action", required=True)
    rp = rsub.add_parser("list", parents=[common], help="list rules")
    rp.add_argument("--custom", action="store_true", help="only user rules")
    rp.set_defaults(func=cmd_rules_list)
    rp = rsub.add_parser("test", parents=[common], help="test which rule matches a file")
    rp.add_argument("file")
    rp.set_defaults(func=cmd_rules_test)
    rp = rsub.add_parser("add", parents=[common], help="add a custom rule")
    rp.add_argument("--name", required=True)
    rp.add_argument("--category", required=True)
    rp.add_argument("--ext", action="append", default=[], help="extension(s), comma separated or repeated")
    rp.add_argument("--glob", action="append", default=[], help="glob(s)")
    rp.add_argument("--regex", default="")
    rp.add_argument("--dest", default="", help="destination template")
    rp.add_argument("--priority", type=int, default=10)
    rp.add_argument("--no-stop", dest="stop", action="store_false", default=True)
    rp.set_defaults(func=cmd_rules_add)
    rp = rsub.add_parser("remove", parents=[common], help="remove a custom rule")
    rp.add_argument("name")
    rp.set_defaults(func=cmd_rules_remove)
    for action in ("enable", "disable"):
        rp = rsub.add_parser(action, parents=[common], help=f"{action} a custom rule")
        rp.add_argument("name")
        rp.set_defaults(func=cmd_rules_toggle, toggle=action == "enable")

    # config -----------------------------------------------------------------
    p = sub.add_parser("config", parents=[common], help="inspect and edit configuration")
    csub = p.add_subparsers(dest="config_action", required=True)
    cp = csub.add_parser("show", parents=[common], help="print the effective configuration")
    cp.add_argument("--raw", action="store_true", help="show only values stored on disk")
    cp.set_defaults(func=cmd_config_show)
    cp = csub.add_parser("get", parents=[common], help="read a dotted key")
    cp.add_argument("key")
    cp.set_defaults(func=cmd_config_get)
    cp = csub.add_parser("set", parents=[common], help="write a dotted key")
    cp.add_argument("key")
    cp.add_argument("value")
    cp.set_defaults(func=cmd_config_set)
    cp = csub.add_parser("unset", parents=[common], help="remove a dotted key")
    cp.add_argument("key")
    cp.set_defaults(func=cmd_config_unset)
    cp = csub.add_parser("path", parents=[common], help="print config, data and log paths")
    cp.set_defaults(func=cmd_config_path)
    cp = csub.add_parser("init", parents=[common], help="create a starter config")
    cp.add_argument("--force", action="store_true")
    cp.set_defaults(func=cmd_config_init)
    cp = csub.add_parser("validate", parents=[common], help="validate configuration")
    cp.set_defaults(func=cmd_config_validate)
    cp = csub.add_parser("migrate", parents=[common], help="import a legacy JSON config")
    cp.add_argument("--from", dest="source", required=True, help="path to a legacy config.json")
    cp.set_defaults(func=cmd_config_migrate)
    cp = csub.add_parser("profiles", parents=[common], help="list or edit profiles")
    cp.add_argument("--create", default=None)
    cp.add_argument("--delete", default=None)
    cp.add_argument("--use", default=None)
    cp.set_defaults(func=cmd_config_profiles)

    # doctor -----------------------------------------------------------------
    p = sub.add_parser("doctor", parents=[common], help="diagnose the installation")
    p.set_defaults(func=cmd_doctor)

    # completions ------------------------------------------------------------
    p = sub.add_parser("completions", parents=[common], help="print shell completion code")
    p.add_argument("shell", choices=["bash", "zsh", "fish"])
    p.set_defaults(func=cmd_completions)

    # autostart --------------------------------------------------------------
    p = sub.add_parser("autostart", parents=[common], help="install a systemd user watcher")
    p.add_argument("action", choices=["install", "remove", "status"])
    p.add_argument("--no-start", action="store_true", help="do not enable/start immediately")
    p.set_defaults(func=cmd_autostart)

    # gui --------------------------------------------------------------------
    p = sub.add_parser("gui", parents=[common], help="launch the desktop app")
    p.set_defaults(func=cmd_gui)

    # version ----------------------------------------------------------------
    p = sub.add_parser("version", parents=[common], help="print the version")
    p.set_defaults(func=cmd_version)

    return parser


def _finalize_args(args: argparse.Namespace) -> None:
    for local, glob in (("json", "g_json"), ("quiet", "g_quiet"), ("verbose", "g_verbose"), ("no_color", "g_no_color")):
        setattr(args, local, bool(getattr(args, local, None) or getattr(args, glob, False)))
    for local, glob in (("config", "g_config"), ("profile", "g_profile")):
        if getattr(args, local, None) is None:
            setattr(args, local, getattr(args, glob, None))


# ------------------------------------------------------------------- utilities
def _load_config(args: argparse.Namespace) -> Config:
    try:
        config = Config(args.config, profile=args.profile)
    except ConfigError as exc:
        raise JarError(str(exc)) from exc
    configure_logging(config, verbose=bool(args.verbose), quiet=bool(args.quiet))
    return config


def _json_output(value: Any, config: Config | None = None) -> None:
    indent = int(config.data.get("json_indent", 2)) if config else 2
    print(json.dumps(value, indent=indent, ensure_ascii=False, default=str))


def _fail(message: str, code: int = 1) -> int:
    print(f"jar: error: {message}", file=sys.stderr)
    return code


def _confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def _parse_value(text: str) -> Any:
    stripped = text.strip()
    if stripped == "":
        return ""
    lowered = stripped.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    mapping = {
        "mode": "mode",
        "dest": "dest_root",
        "conflict": "conflict",
        "recursive": "recursive",
        "use_trash": "use_trash",
        "cleanup_empty": "cleanup_empty_dirs",
        "follow_symlinks": "follow_symlinks",
        "sanitize_names": "sanitize_names",
        "normalize_names": "normalize_names",
        "date_subfolders": "date_subfolders",
        "notifications": "notifications",
        "dry_run": "dry_run",
    }
    for attr, key in mapping.items():
        value = getattr(args, attr, None)
        if value is not None:
            overrides[key] = value
    if getattr(args, "min_age", None) is not None:
        overrides["min_age_seconds"] = parse_duration(args.min_age)
    if getattr(args, "max_age", None) is not None:
        overrides["max_age_seconds"] = parse_duration(args.max_age)
    if getattr(args, "min_size", None) is not None:
        overrides["min_size"] = parse_size(args.min_size)
    if getattr(args, "max_size", None) is not None:
        overrides["max_size"] = parse_size(args.max_size)
    if getattr(args, "category", None):
        overrides["include_categories"] = list(args.category)
    if getattr(args, "exclude_category", None):
        overrides["exclude_categories"] = list(args.exclude_category)
    if getattr(args, "interval", None) is not None:
        overrides["watch_interval"] = max(0.25, float(args.interval))
    if getattr(args, "stability", None) is not None:
        overrides["watch_stability"] = max(0.0, float(args.stability))
    return overrides


def _paths_or_config(paths: Iterable[str], config: Config) -> list[str]:
    values = [str(path) for path in paths if str(path).strip()]
    return values or list(config.watch_dirs)


def _print_plan(plan: Plan, args: argparse.Namespace, colors: Colors, show_all: bool = False) -> None:
    print(colors.bold(f"JAR plan - {plan.mode} mode"))
    print(
        f"  destination: {plan.dest_root}\n"
        f"  files:       {len(plan.items)} ({len(plan.moves)} to move, {len(plan.skips)} skipped)\n"
        f"  size:        {human_size(plan.total_size)}"
    )
    if plan.errors:
        print(colors.yellow(f"  scan warnings: {len(plan.errors)}"))
    rows = plan.items if show_all or len(plan.items) <= 40 else plan.items[:40]
    if rows:
        table_rows = []
        for item in rows:
            action = item.action
            if action == "move":
                action_text = colors.green("move") if colors.enabled else "move"
            else:
                action_text = colors.yellow("skip") if colors.enabled else "skip"
            destination = str(item.dst) if item.dst else "-"
            table_rows.append(
                [
                    action_text,
                    item.category,
                    truncate_middle(str(item.src), 52),
                    truncate_middle(destination, 52),
                    truncate(item.reason, 34),
                ]
            )
        print()
        print(format_table(["Action", "Category", "Source", "Destination", "Note"], table_rows, [7, 14, 52, 52, 34]))
        if len(rows) < len(plan.items):
            print(colors.dim(f"... {len(plan.items) - len(rows)} more row(s); use --all to show everything"))
    if plan.errors:
        print()
        for error in plan.errors[:10]:
            print(colors.yellow(f"  warning: {error['path']}: {error['error']}"))


def _print_execution(result, colors: Colors) -> None:
    print()
    print(colors.bold("JAR result"))
    print(f"  moved:   {result.moved if isinstance(result.moved, int) else len(result.moved)}")
    print(f"  skipped: {result.skipped if isinstance(result.skipped, int) else len(result.skipped)}")
    print(f"  failed:  {result.failed if isinstance(result.failed, int) else len(result.failed)}")
    if getattr(result, "bytes_moved", 0):
        print(f"  routed:  {human_size(result.bytes_moved)}")
    if getattr(result, "batch_id", None):
        print(f"  batch:   {result.batch_id}")
        print(colors.dim(f"  undo with: jar undo --batch {result.batch_id}"))


# -------------------------------------------------------------------- commands
def cmd_organize(args: argparse.Namespace) -> int:
    config = _load_config(args)
    colors = _colors(args)
    try:
        overrides = _overrides_from_args(args)
    except ValueError as exc:
        return _fail(str(exc))
    effective = config.with_overrides(overrides) if overrides else config
    paths = _paths_or_config(getattr(args, "paths", []), effective)
    if not paths:
        return _fail("no folders to organize. Pass a path or run 'jar config set watch_dirs ...'")
    organizer = Organizer(effective)
    try:
        plan = organizer.plan(paths)
        dry = bool(effective.data.get("dry_run"))
        if not args.json:
            _print_plan(plan, args, colors, show_all=bool(getattr(args, "all", False)))
        if dry:
            if args.json:
                _json_output({"plan": plan.describe(), "dry_run": True}, config)
            else:
                print(colors.yellow("\nDry run: no files were changed."))
            return 0
        if not plan.moves:
            if args.json:
                _json_output({"plan": plan.describe(), "dry_run": False, "result": None}, config)
            else:
                print(colors.green("\nNothing to do."))
            return 0
        progress = Progress(
            enabled=sys.stdout.isatty() and not args.json and not args.quiet
        )
        result = organizer.execute(plan, progress=progress)
        if args.json:
            _json_output(
                {"plan": plan.describe(), "result": result.describe()}, config
            )
        else:
            _print_execution(result, colors)
        return 0 if result.ok else 1
    finally:
        organizer.close()


def cmd_watch(args: argparse.Namespace) -> int:
    from .watcher import WatchService

    config = _load_config(args)
    colors = _colors(args)
    try:
        overrides = _overrides_from_args(args)
    except ValueError as exc:
        return _fail(str(exc))
    effective = config.with_overrides(overrides) if overrides else config
    paths = _paths_or_config(getattr(args, "paths", []), effective)
    if not paths:
        return _fail("no folders to watch. Pass a path or run 'jar config set watch_dirs ...'")
    if args.once:
        args.paths = paths
        return cmd_organize(args)

    organizer = Organizer(effective)
    stats = {"moved": 0, "skipped": 0, "failed": 0, "bytes": 0}

    def handle(path: Path) -> None:
        plan = organizer.plan([path])
        if not plan.moves:
            return
        result = organizer.execute(plan)
        stats["moved"] += len(result.moved)
        stats["skipped"] += len(result.skipped)
        stats["failed"] += len(result.failed)
        stats["bytes"] += result.bytes_moved
        if args.json:
            _json_output(
                {
                    "event": "organized",
                    "file": str(path),
                    "result": result.describe(),
                    "totals": stats,
                },
                config,
            )
        else:
            if result.moved:
                for entry in result.moved:
                    print(
                        colors.green("moved ")
                        + f"{Path(entry['source']).name} -> {entry['destination']}"
                    )
            if result.failed:
                for entry in result.failed:
                    print(colors.red("failed ") + f"{entry['source']}: {entry.get('reason')}")
            if result.skipped and args.verbose:
                for entry in result.skipped:
                    print(colors.yellow("skip  ") + f"{entry['source']}: {entry.get('reason')}")

    try:
        service = WatchService(
            effective,
            paths,
            handle,
            recursive=args.recursive,
            interval=float(args.interval) if args.interval else None,
            stability=float(args.stability) if args.stability else None,
            process_existing=bool(args.existing),
            on_error=lambda path, exc: print(f"warning: {path}: {exc}", file=sys.stderr),
        )
    except JarError as exc:
        organizer.close()
        return _fail(str(exc))

    if not args.json:
        print(colors.bold(f"JAR watching {len(paths)} folder(s)"))
        print(colors.dim(f"interval={service.interval}s stability={service.stability}s recursive={service.recursive}"))
        print(colors.dim("Press Ctrl+C to stop."))
    try:
        service.run()
    except KeyboardInterrupt:
        if not args.json:
            print("\nStopped.")
    finally:
        service.stop()
        organizer.close()
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    config = _load_config(args)
    colors = _colors(args)
    overrides = _overrides_from_args(args)
    effective = config.with_overrides(overrides) if overrides else config
    paths = _paths_or_config(getattr(args, "paths", []), effective)
    if not paths:
        return _fail("no folders to scan")
    organizer = Organizer(effective)
    try:
        plan = organizer.plan(paths, recursive=args.recursive)
        if args.json:
            payload: dict[str, Any] = plan.describe()
            if args.stats:
                payload["category_summary"] = _category_summary(plan)
            _json_output(payload, config)
            return 0
        _print_plan(plan, args, colors, show_all=bool(args.all) or bool(args.stats))
        if args.stats:
            summary = _category_summary(plan)
            print()
            print(colors.bold("By category"))
            print(
                format_table(
                    ["Category", "Files", "Size"],
                    [[row["category"], row["files"], human_size(row["bytes"])] for row in summary],
                )
            )
        return 0
    finally:
        organizer.close()


def _category_summary(plan: Plan) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in plan.moves:
        bucket = buckets.setdefault(item.category, {"category": item.category, "files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += item.size
    return sorted(buckets.values(), key=lambda row: (-row["bytes"], row["category"]))


def cmd_stats(args: argparse.Namespace) -> int:
    config = _load_config(args)
    journal = Journal(config.paths.db_file)
    try:
        stats = journal.stats()
        stats["config"] = config.describe()
        try:
            usage = shutil.disk_usage(config.destination_root)
            stats["disk"] = {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "destination_root": str(config.destination_root),
            }
        except OSError:
            pass
        if args.export:
            path = export_report(stats, args.export, args.format)
            if args.json:
                _json_output({**stats, "exported": str(path)}, config)
            else:
                print(f"Report written to {path}")
        elif args.json:
            _json_output(stats, config)
        else:
            print(report_text(stats))
        return 0
    finally:
        journal.close()


def cmd_history(args: argparse.Namespace) -> int:
    config = _load_config(args)
    colors = _colors(args)
    journal = Journal(config.paths.db_file)
    try:
        if args.clear:
            if not _confirm("Delete all JAR history?", args.yes):
                return _fail("cancelled (use --yes in scripts)")
            journal.clear()
            if args.json:
                _json_output({"cleared": True}, config)
            else:
                print("History cleared.")
            return 0
        if args.batches:
            batches = journal.batches(args.limit)
            if args.json:
                _json_output(batches, config)
                return 0
            print(
                format_table(
                    ["Batch", "Started", "Mode", "Moved", "Skipped", "Failed", "Note"],
                    [
                        [
                            row["id"],
                            format_ts(row["started"]),
                            row["mode"],
                            row["moved"],
                            row["skipped"],
                            row["failed"],
                            truncate(row["note"], 30),
                        ]
                        for row in batches
                    ],
                    [18, 19, 9, 7, 8, 7, 30],
                )
            )
            return 0
        operations = journal.operations(
            limit=args.limit,
            batch_id=args.batch,
            search=args.search,
        )
        if args.json:
            _json_output(operations, config)
            return 0
        if not operations:
            print("No history yet.")
            return 0
        rows = []
        for row in operations:
            status = row["status"]
            if status == "ok":
                status_text = colors.green("ok")
            elif status == "skipped":
                status_text = colors.yellow("skip")
            else:
                status_text = colors.red("error")
            rows.append(
                [
                    format_ts(row["ts"], "%m-%d %H:%M"),
                    row["action"],
                    status_text,
                    row["category"] or "-",
                    truncate_middle(row["src"], 44),
                    truncate_middle(row["dst"] or "-", 44),
                    truncate(row["error"], 28),
                ]
            )
        print(
            format_table(
                ["When", "Action", "Status", "Category", "Source", "Destination", "Error"],
                rows,
                [12, 9, 6, 12, 44, 44, 28],
            )
        )
        return 0
    finally:
        journal.close()


def cmd_undo(args: argparse.Namespace) -> int:
    config = _load_config(args)
    colors = _colors(args)
    dry = bool(config.data.get("dry_run"))
    if not dry and sys.stdin.isatty() and not args.yes:
        if not _confirm("Restore files from the selected batch?", False):
            return _fail("cancelled")
    organizer = Organizer(config)
    try:
        result = organizer.undo(count=args.last, batch_id=args.batch, dry_run=dry)
        if args.json:
            _json_output(result.describe(), config)
        else:
            if not result.restored and not result.failed and not result.skipped:
                print("Nothing to undo.")
            else:
                if dry:
                    print(colors.yellow("Dry run - would restore:"))
                    for entry in result.restored:
                        print(f"  {entry['source']} -> {entry['destination']}")
                    print(colors.yellow("No files were changed."))
                else:
                    print(colors.green(f"Restored {len(result.restored)} file(s)."))
                    if result.skipped:
                        print(colors.yellow(f"Skipped {len(result.skipped)} file(s)."))
                    if result.failed:
                        print(colors.red(f"Failed to restore {len(result.failed)} file(s)."))
                    for entry in result.failed:
                        print(f"  {entry['source']}: {entry['reason']}")
        return 0 if not result.failed else 1
    finally:
        organizer.close()


def cmd_duplicates(args: argparse.Namespace) -> int:
    config = _load_config(args)
    colors = _colors(args)
    overrides = _overrides_from_args(args)
    effective = config.with_overrides(overrides) if overrides else config
    paths = _paths_or_config(getattr(args, "paths", []), effective)
    if not paths:
        return _fail("no folders to scan for duplicates")
    organizer = Organizer(effective)
    try:
        groups = organizer.scan_duplicates(paths, recursive=args.recursive)
        removing = bool(args.trash or args.delete)
        summary = {
            "groups": [group.describe() for group in groups],
            "files": sum(len(group.files) for group in groups),
            "wasted_bytes": sum(group.wasted_bytes for group in groups),
        }
        if not args.json:
            if not groups:
                print(colors.green("No duplicates found."))
            else:
                rows = []
                for index, group in enumerate(groups, start=1):
                    keeper = choose_keeper(group, args.keep)
                    rows.append(
                        [
                            index,
                            len(group.files),
                            human_size(group.size),
                            human_size(group.wasted_bytes),
                            truncate_middle(str(keeper), 56),
                        ]
                    )
                print(
                    format_table(
                        ["Group", "Files", "Each", "Wasted", "Keeping"],
                        rows,
                    )
                )
                print(
                    colors.dim(
                        f"\n{sum(len(g.files) for g in groups)} files in {len(groups)} groups; "
                        f"{human_size(sum(g.wasted_bytes for g in groups))} could be reclaimed."
                    )
                )
        if not removing or not groups:
            if args.json:
                _json_output(summary, config)
            return 0
        if not args.dry_run:
            if not _confirm(
                f"Remove duplicates permanently?" if args.delete else "Move duplicates to quarantine?",
                args.yes,
            ):
                return _fail("cancelled (use --yes in scripts)")
        result = organizer.dedupe(
            groups,
            keep=args.keep,
            permanent=bool(args.delete),
            dry_run=bool(args.dry_run),
        )
        if args.json:
            summary["removal"] = result.describe()
            _json_output(summary, config)
        else:
            label = "Would remove" if args.dry_run else "Removed"
            print(
                colors.green(
                    f"{label} {len(result.removed)} duplicate(s), "
                    f"reclaiming {human_size(result.bytes_reclaimed)}."
                )
            )
            if result.failed:
                print(colors.red(f"{len(result.failed)} failed."))
                for entry in result.failed:
                    print(f"  {entry['source']}: {entry['reason']}")
        return 0 if not result.failed else 1
    finally:
        organizer.close()


def cmd_quarantine_list(args: argparse.Namespace) -> int:
    config = _load_config(args)
    items = list_quarantine(config.quarantine_dir)[: args.limit]
    if args.json:
        _json_output(items, config)
        return 0
    if not items:
        print(f"Quarantine is empty ({config.quarantine_dir}).")
        return 0
    print(f"Quarantine: {config.quarantine_dir}")
    print(
        format_table(
            ["Name", "Size", "Deleted"],
            [[item["name"], human_size(item["size"]), format_ts(item["mtime"])] for item in items],
            [70, 12, 19],
        )
    )
    return 0


def cmd_quarantine_restore(args: argparse.Namespace) -> int:
    config = _load_config(args)
    destination = Path(args.to).expanduser() if args.to else Path.cwd()
    try:
        restored = restore_quarantine_item(
            config.quarantine_dir, args.name, destination, overwrite=args.force
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _fail(str(exc))
    if args.json:
        _json_output({"restored": str(restored)}, config)
    else:
        print(f"Restored to {restored}")
    return 0


def cmd_quarantine_purge(args: argparse.Namespace) -> int:
    config = _load_config(args)
    try:
        older = parse_duration(args.older_than)
    except ValueError as exc:
        return _fail(str(exc))
    dry = bool(args.dry_run)
    if not dry and not _confirm(
        f"Permanently delete quarantine files older than {human_duration(older)}?", args.yes
    ):
        return _fail("cancelled (use --yes in scripts)")
    removed = purge_quarantine(config.quarantine_dir, older, dry_run=dry)
    if args.json:
        _json_output(
            {"purged": len(removed), "dry_run": dry, "files": [str(path) for path in removed]},
            config,
        )
    else:
        print(
            f"{'Would purge' if dry else 'Purged'} {len(removed)} file(s) "
            f"from {config.quarantine_dir}."
        )
    return 0


# ----------------------------------------------------------------------- rules
def cmd_rules_list(args: argparse.Namespace) -> int:
    config = _load_config(args)
    engine = RuleEngine(config)
    rules = engine.describe()
    if args.custom:
        rules = [rule for rule in rules if not rule["builtin"]]
    if args.json:
        _json_output(rules, config)
        return 0
    rows = []
    for rule in rules:
        matchers = []
        if rule["extensions"]:
            matchers.append("ext:" + ",".join(rule["extensions"][:6]))
        if rule["globs"]:
            matchers.append("glob:" + ",".join(rule["globs"][:3]))
        if rule["regex"]:
            matchers.append("re:" + rule["regex"])
        rows.append(
            [
                rule["name"],
                rule["category"],
                rule["priority"],
                "yes" if rule["enabled"] else "no",
                truncate(" ".join(matchers), 60),
                truncate(rule["destination"] or "-", 24),
            ]
        )
    print(
        format_table(
            ["Name", "Category", "Priority", "Enabled", "Matchers", "Destination"],
            rows,
            [28, 14, 8, 7, 60, 24],
        )
    )
    return 0


def cmd_rules_test(args: argparse.Namespace) -> int:
    config = _load_config(args)
    engine = RuleEngine(config)
    path = Path(args.file).expanduser()
    if not path.exists():
        return _fail(f"file not found: {path}")
    try:
        match = engine.classify(path)
        destination = engine.render_destination(path, match)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))
    payload = {
        "file": str(path),
        "category": match.category,
        "rule": match.rule,
        "destination": str(destination),
        "builtin": match.builtin,
    }
    if args.json:
        _json_output(payload, config)
    else:
        print(f"File:        {path}")
        print(f"Category:    {match.category}")
        print(f"Rule:        {match.rule} (priority {match.priority})")
        print(f"Destination: {destination}")
    return 0


def cmd_rules_add(args: argparse.Namespace) -> int:
    config = _load_config(args)
    extensions: list[str] = []
    for value in args.ext:
        extensions.extend(normalize_extension(part) for part in split_csv(value))
    globs: list[str] = []
    for value in args.glob:
        globs.extend(split_csv(value))
    if not extensions and not globs and not args.regex:
        return _fail("a rule needs at least one --ext, --glob or --regex matcher")
    if args.regex:
        try:
            re.compile(args.regex)
        except re.error as exc:
            return _fail(f"invalid regex: {exc}")
    rules = list(config.data.get("rules") or [])
    if any(str(rule.get("name")) == args.name for rule in rules):
        return _fail(f"a custom rule named {args.name!r} already exists")
    rule = {
        "name": args.name,
        "category": args.category,
        "priority": args.priority,
        "enabled": True,
        "extensions": extensions,
        "globs": globs,
        "regex": args.regex,
        "destination": args.dest,
        "stop": args.stop,
    }
    rules.append(rule)
    config.set("rules", rules)
    config.save()
    if args.json:
        _json_output(rule, config)
    else:
        print(f"Added rule {args.name!r} -> {args.category}")
    return 0


def _modify_custom_rule(config: Config, name: str, mutate) -> bool:
    rules = list(config.data.get("rules") or [])
    found = False
    for rule in rules:
        if str(rule.get("name")) == name:
            mutate(rule)
            found = True
            break
    if found:
        config.set("rules", rules)
        config.save()
    return found


def cmd_rules_remove(args: argparse.Namespace) -> int:
    config = _load_config(args)
    rules = [rule for rule in (config.data.get("rules") or []) if str(rule.get("name")) != args.name]
    if len(rules) == len(config.data.get("rules") or []):
        return _fail(f"custom rule not found: {args.name}")
    config.set("rules", rules)
    config.save()
    if args.json:
        _json_output({"removed": args.name}, config)
    else:
        print(f"Removed rule {args.name!r}")
    return 0


def cmd_rules_toggle(args: argparse.Namespace) -> int:
    config = _load_config(args)

    def mutate(rule: dict) -> None:
        rule["enabled"] = bool(args.toggle)

    if not _modify_custom_rule(config, args.name, mutate):
        return _fail(f"custom rule not found: {args.name}")
    print(f"{'Enabled' if args.toggle else 'Disabled'} rule {args.name!r}")
    return 0


# ---------------------------------------------------------------------- config
def cmd_config_show(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = config.raw if args.raw else config.data
    if args.json or not sys.stdout.isatty():
        _json_output(payload, config)
    else:
        _json_output(payload, config)
    return 0


def cmd_config_get(args: argparse.Namespace) -> int:
    config = _load_config(args)
    sentinel = object()
    from .utils import deep_get

    value = deep_get(config.data, args.key, sentinel)
    if value is sentinel:
        return _fail(f"unknown config key: {args.key}")
    if args.json:
        _json_output(value, config)
    else:
        if isinstance(value, str):
            print(value)
        else:
            print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    config = _load_config(args)
    value = _parse_value(args.value)
    if args.key in ("mode",) and value not in MODES:
        return _fail(f"mode must be one of {', '.join(MODES)}")
    if args.key in ("conflict",) and value not in CONFLICT_STRATEGIES:
        return _fail(f"conflict must be one of {', '.join(CONFLICT_STRATEGIES)}")
    config.set(args.key, value)
    path = config.save()
    if args.json:
        _json_output({"key": args.key, "value": value, "config": str(path)}, config)
    else:
        print(f"{args.key} = {json.dumps(value, ensure_ascii=False)}")
        print(f"Saved to {path}")
    return 0


def cmd_config_unset(args: argparse.Namespace) -> int:
    config = _load_config(args)
    removed = config.unset(args.key)
    if not removed:
        return _fail(f"key is not set: {args.key}")
    config.save()
    print(f"Removed {args.key}")
    return 0


def cmd_config_path(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = config.describe()
    if args.json:
        _json_output(payload, config)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    config = Config(args.config, profile=args.profile, load=False)
    try:
        path = config.create_default(force=args.force)
    except ConfigError as exc:
        return _fail(str(exc))
    if args.json:
        _json_output({"created": str(path)}, config)
    else:
        print(f"Created {path}")
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    config = _load_config(args)
    issues = config.validate()
    errors = [issue for issue in issues if issue[0] == "error"]
    if args.json:
        _json_output(
            {
                "valid": not errors,
                "errors": len(errors),
                "warnings": len(issues) - len(errors),
                "issues": [{"level": level, "message": message} for level, message in issues],
                "config": str(config.paths.config_file),
            },
            config,
        )
    else:
        if not issues:
            print("Configuration is valid.")
        for level, message in issues:
            print(f"{level.upper():7} {message}")
        print(f"\n{len(errors)} error(s), {len(issues) - len(errors)} warning(s).")
    return 0 if not errors else 1


def cmd_config_migrate(args: argparse.Namespace) -> int:
    config = _load_config(args)
    try:
        migrated = config.migrate_from(args.source)
        path = config.save()
    except ConfigError as exc:
        return _fail(str(exc))
    if args.json:
        _json_output({"migrated": migrated, "config": str(path)}, config)
    else:
        print(f"Imported {len(migrated)} setting(s) into {path}")
        for key, value in migrated.items():
            print(f"  {key}: {value}")
    return 0


def cmd_config_profiles(args: argparse.Namespace) -> int:
    config = _load_config(args)
    try:
        if args.create:
            config.create_profile(args.create)
            config.save()
        if args.delete:
            if not config.delete_profile(args.delete):
                return _fail(f"unknown profile: {args.delete}")
            config.save()
        if args.use:
            config.use_profile(args.use)
            config.save()
    except ConfigError as exc:
        return _fail(str(exc))
    payload = {"active": config.profile, "profiles": config.profile_names()}
    if args.json:
        _json_output(payload, config)
    else:
        for name in payload["profiles"]:
            marker = "*" if name == payload["active"] else " "
            print(f"{marker} {name}")
    return 0


# ---------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    config = _load_config(args)
    checks: list[dict[str, str]] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    version = sys.version_info
    if version >= (3, 9):
        check("python", "ok", f"{platform.python_version()} on {platform.platform()}")
    else:
        check("python", "fail", f"{platform.python_version()} (3.9+ required)")

    for module, label in (
        ("tkinter", "GUI base"),
        ("customtkinter", "GUI toolkit"),
        ("pystray", "tray icon"),
        ("PIL", "image support"),
        ("send2trash", "system trash"),
    ):
        import importlib.util

        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        check(module, "ok" if found else "warn", f"{label}: {'installed' if found else 'not installed (optional)'}")

    try:
        config.paths.ensure()
        check("config-dir", "ok", str(config.paths.config_dir))
        check("data-dir", "ok", str(config.paths.data_dir))
    except OSError as exc:
        check("config-dir", "fail", str(exc))

    try:
        journal = Journal(config.paths.db_file)
        journal.close()
        check("journal", "ok", str(config.paths.db_file))
    except Exception as exc:  # noqa: BLE001
        check("journal", "fail", str(exc))

    if config.paths.config_file.exists():
        check("config", "ok", str(config.paths.config_file))
    else:
        check("config", "warn", "config does not exist yet (run 'jar config init')")

    issues = config.validate()
    errors = [issue for issue in issues if issue[0] == "error"]
    warnings = [issue for issue in issues if issue[0] == "warning"]
    check(
        "validation",
        "fail" if errors else ("warn" if warnings else "ok"),
        f"{len(errors)} error(s), {len(warnings)} warning(s)",
    )
    for level, message in issues:
        check("config-check", "fail" if level == "error" else "warn", message)

    watch_dirs = config.resolved_watch_dirs()
    if watch_dirs:
        check("watch-folders", "ok", f"{len(watch_dirs)} configured")
    else:
        check("watch-folders", "warn", "no watch folders configured")

    dest = config.destination_root
    try:
        dest.mkdir(parents=True, exist_ok=True)
        probe = dest / f".jar-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check("destination", "ok", str(dest))
    except OSError as exc:
        check("destination", "fail", f"{dest}: {exc}")

    try:
        config.quarantine_dir.mkdir(parents=True, exist_ok=True)
        check("quarantine", "ok", str(config.quarantine_dir))
    except OSError as exc:
        check("quarantine", "fail", str(exc))

    if config.paths.lock_file.exists():
        lock = FileLock(config.paths.lock_file)
        check("lock", "warn" if not lock._is_stale() else "ok", f"lock file present: {config.paths.lock_file}")
    else:
        check("lock", "ok", "no active lock")

    if os.name == "posix" and shutil.which("notify-send"):
        check("notifications", "ok", "notify-send available")
    else:
        check("notifications", "warn", "desktop notifications not available")

    failures = [entry for entry in checks if entry["status"] == "fail"]
    if args.json:
        _json_output(
            {
                "ok": not failures,
                "failures": len(failures),
                "checks": checks,
                "config": config.describe(),
            },
            config,
        )
    else:
        print(
            format_table(
                ["Check", "Status", "Detail"],
                [[entry["check"], entry["status"], truncate(entry["detail"], 90)] for entry in checks],
                [18, 7, 90],
            )
        )
        print()
        if failures:
            print(f"{len(failures)} check(s) failed.")
        else:
            print("No failures. JAR looks healthy.")
    return 0 if not failures else 1


# ----------------------------------------------------------------- completions
def cmd_completions(args: argparse.Namespace) -> int:
    commands = " ".join(COMMANDS)
    if args.shell == "bash":
        print(
            f"""# JAR bash completion
_jar_completion() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{commands}" -- "$cur") )
        return 0
    fi
    case "$prev" in
        --mode) COMPREPLY=( $(compgen -W "global local" -- "$cur") ); return 0 ;;
        --conflict) COMPREPLY=( $(compgen -W "{' '.join(CONFLICT_STRATEGIES)}" -- "$cur") ); return 0 ;;
        --config) COMPREPLY=( $(compgen -f -- "$cur") ); return 0 ;;
        --shell|completions) : ;;
    esac
    COMPREPLY=( $(compgen -f -- "$cur") )
}}
complete -F _jar_completion jar
"""
        )
    elif args.shell == "zsh":
        print(
            f"""#compdef jar
_jar() {{
    local -a commands
    commands=({commands})
    if (( CURRENT == 2 )); then
        _describe 'command' commands
        return
    fi
    _arguments '1: :->cmds' '*: :->args'
    case $state in
        args) _files ;;
    esac
}}
compdef _jar jar
"""
        )
    else:
        print(
            f"""# JAR fish completion
complete -c jar -f
complete -c jar -n '__fish_use_subcommand' -a '{commands}'
complete -c jar -n '__fish_seen_subcommand_from organize watch scan duplicates' -a '(__fish_complete_directories)'
complete -c jar -l mode -a 'global local'
complete -c jar -l conflict -a "{' '.join(CONFLICT_STRATEGIES)}"
"""
        )
    return 0


# ------------------------------------------------------------------- autostart
def _systemd_unit(config: Config) -> str:
    executable = shutil.which("jar")
    if executable:
        command = [executable, "watch"]
    else:
        command = [sys.executable, "-m", "jar", "watch"]
    workdir = str(Path.home())
    return "\n".join(
        [
            "[Unit]",
            "Description=JAR file organizer watcher",
            "After=default.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={workdir}",
            f"ExecStart={shlex.join(command)}",
            "Restart=on-failure",
            "RestartSec=5",
            "Environment=PYTHONUNBUFFERED=1",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def cmd_autostart(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if platform.system() != "Linux":
        return _fail("autostart is currently implemented for Linux/systemd only")
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_file = unit_dir / "jar-watch.service"
    if args.action == "status":
        active = _run_quiet(["systemctl", "--user", "is-active", "jar-watch.service"])
        enabled = _run_quiet(["systemctl", "--user", "is-enabled", "jar-watch.service"])
        payload = {
            "unit": str(unit_file),
            "exists": unit_file.exists(),
            "active": active,
            "enabled": enabled,
        }
        if args.json:
            _json_output(payload, config)
        else:
            for key, value in payload.items():
                print(f"{key}: {value}")
        return 0
    if not shutil.which("systemctl"):
        return _fail("systemctl was not found")
    if args.action == "install":
        unit = _systemd_unit(config)
        if args.dry_run:
            print(unit)
            return 0
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file.write_text(unit, encoding="utf-8")
        _run_quiet(["systemctl", "--user", "daemon-reload"])
        if not args.no_start:
            _run_quiet(["systemctl", "--user", "enable", "--now", "jar-watch.service"])
        print(f"Installed {unit_file}")
        if args.no_start:
            print("Enable it with: systemctl --user enable --now jar-watch.service")
        return 0
    # remove
    if args.dry_run:
        print(f"Would remove {unit_file}")
        return 0
    _run_quiet(["systemctl", "--user", "disable", "--now", "jar-watch.service"])
    try:
        unit_file.unlink()
    except FileNotFoundError:
        pass
    _run_quiet(["systemctl", "--user", "daemon-reload"])
    print(f"Removed {unit_file}")
    return 0


def _run_quiet(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15, check=False
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ------------------------------------------------------------------------- gui
def cmd_gui(args: argparse.Namespace) -> int:
    config = _load_config(args)
    try:
        from .gui.app import launch
    except ImportError as exc:
        return _fail(
            "the desktop app needs optional dependencies: "
            "pip install 'jar-organizer[gui]' "
            f"({exc})"
        )
    launch(config)
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    if args.json:
        _json_output({"name": APP_NAME, "version": __version__, "tagline": APP_TAGLINE})
    else:
        print(f"{APP_NAME} {__version__} - {APP_TAGLINE}")
    return 0


# ------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _finalize_args(args)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0
    except JarError as exc:
        return _fail(str(exc))
    except ConfigError as exc:
        return _fail(str(exc))
    except ValueError as exc:
        return _fail(str(exc))
    except PermissionError as exc:
        return _fail(f"permission denied: {exc}")
    except OSError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
