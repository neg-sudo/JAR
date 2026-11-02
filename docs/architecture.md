# Architecture

JAR is organized around a small, dependency-free core and thin presentation
layers. The CLI and the desktop app both drive the same `Organizer`, so behaviour
cannot drift between them.

```
                ┌──────────────┐      ┌──────────────┐
                │   jar.cli    │      │  jar.gui.*   │
                └──────┬───────┘      └──────┬───────┘
                       │                     │
                       └─────────┬───────────┘
                                 ▼
                         ┌───────────────┐
                         │   Organizer   │
                         └───────┬───────┘
             ┌───────────────────┼────────────────────┐
             ▼                   ▼                    ▼
      ┌────────────┐      ┌────────────┐       ┌────────────┐
      │  Scanner   │      │ RuleEngine │       │  Journal   │
      └─────┬──────┘      └─────┬──────┘       └─────┬──────┘
            │                   │                    │
            ▼                   ▼                    ▼
      ┌────────────┐      ┌────────────┐       ┌────────────┐
      │  Safety    │      │ Categories │       │  SQLite    │
      └────────────┘      └────────────┘       └────────────┘
```

## Modules

| Module | Responsibility |
| --- | --- |
| `jar.cli` | Argument parsing, command handlers, human and JSON output. |
| `jar.organizer` | Planning, execution, conflict resolution, undo and dedupe. |
| `jar.scanner` | File discovery, filters and candidate construction. |
| `jar.rules` | Classification, ignore files and destination rendering. |
| `jar.categories` | Built-in extension map and category destinations. |
| `jar.config` | Defaults, profiles, validation, paths and migration. |
| `jar.safety` | Filename hygiene, containment checks, protected roots, lock file. |
| `jar.journal` | SQLite schema, batch/operation records, stats and search. |
| `jar.duplicates` | Size grouping, streaming hashes and keeper selection. |
| `jar.trash` | Quarantine, restore, purge and OS-trash integration. |
| `jar.reports` | Text/Markdown/JSON/CSV/TSV report generation. |
| `jar.watcher` | Polling watcher with stability detection. |
| `jar.notify` | Best-effort desktop notifications. |
| `jar.plugins` | Hooks and plugin-like command execution. |
| `jar.logging_setup` | Rotating file and console logging. |
| `jar.gui` | Optional Tk/customtkinter desktop app and tray icon. |

## Plan/execute split

Mutating commands follow a strict two-phase model:

1. **Plan** (`Organizer.plan`) discovers candidates, classifies them, resolves
   destinations, detects conflicts and returns a `Plan` of `PlanItem`s. Nothing
   is modified. A dry run prints this plan and stops.
2. **Execute** (`Organizer.execute`) re-checks each source, resolves the final
   conflict decision, runs optional hooks, moves the file and records the result
   in the journal.

The split makes dry runs trustworthy, keeps the UI responsive, and allows the
watcher to plan/execute a single file at a time.

## Conflict resolution

Conflicts are resolved twice:

- During planning, so the preview shows `report (1).txt` and so two source files
  in the same batch cannot target the same destination.
- During execution, because the filesystem can change between the two phases.

The second pass handles the race correctly even if another program created the
target in the meantime.

## Journal schema

The SQLite journal has two tables:

- `batches` — one row per command run: mode, profile, counters, start/finish
  times.
- `operations` — one row per file: action, source, destination, category, size,
  digest, status, error and an `undone` flag.

Undo works backwards through successful operations, restoring moved files and
reversing quarantine/deletion where possible. Every restore is itself journaled
as a new batch, so audit history remains complete.

## Safety invariants

- A destination must remain inside its computed destination root.
- Templates cannot be absolute or contain `..`.
- Protected roots (home, filesystem roots, configured paths) are rejected.
- Generated names are sanitised and collision-checked.
- A lock file serialises mutating runs per data directory.
- Missing sources, permission errors and full disks are captured per file; one
  failure never aborts the batch.

## Optional dependencies

The following imports are deliberately local and optional:

| Feature | Module |
| --- | --- |
| Desktop window | `tkinter` |
| Fancier widgets | `customtkinter` |
| Tray icon and images | `pystray`, `PIL` |
| OS trash | `send2trash` |

If they are missing, the CLI still works and `jar doctor` reports the affected
feature as a warning. The desktop entry point exits with a clear installation
hint rather than a traceback.

## Testing strategy

- `tests/helpers.py` creates an isolated config/data/inbox sandbox and sets
  `JAR_CONFIG_DIR` / `JAR_DATA_DIR` for every test.
- Unit tests cover utilities, safety, configuration, rules, scanning,
  duplicates, journal and reports.
- Integration tests drive `Organizer` through every conflict strategy, undo,
  dedupe and local mode.
- CLI tests call `jar.cli.main()` in-process and assert exit codes, text and
  JSON.
- The watcher is tested with real threads and short timeouts.
- `scripts/smoke_test.py` validates a packaged binary end to end.

## Packaging

PyInstaller builds single-file executables from `scripts/entry_cli.py` and
`scripts/entry_gui.py`. The CLI spec excludes GUI libraries to stay small; the
desktop spec collects `customtkinter`, `PIL` and `pystray` when present. On
macOS the desktop spec also emits a `JAR.app` bundle.

`scripts/package_release.py` adds documentation, normalises platform and
architecture names, creates a versioned archive and writes `SHA256SUMS.txt`.
CI builds the same artifacts on every push, and the release workflow uploads
them to GitHub when a `v*` tag is pushed.
