# Changelog

All notable changes to JAR are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — 2026-11-02

JAR 2.0 is a ground-up rebuild under a new name. The core engine was rewritten
to be standard-library-only, the CLI was expanded into a complete tool, and a
desktop app, release pipeline and test suite were added.

### Added

- **New identity**: JAR — Just Automated Routing.
- **Complete CLI** with `organize`, `watch`, `scan`, `stats`, `history`,
  `undo`, `duplicates`, `quarantine`, `rules`, `config`, `doctor`,
  `completions`, `autostart`, `gui` and `version`.
- **Custom rule engine** with extension, glob, regex, size and age matching,
  priorities and per-rule destinations.
- **Destination templates** with date, name, size and profile variables.
- **Seven conflict strategies**: rename, skip, overwrite, trash, dedupe,
  keep newest, keep oldest.
- **Content-aware duplicate detection** with streaming SHA-256 hashing and four
  keeper strategies.
- **Undoable quarantine** with restore, purge and path-traversal protection.
- **SQLite journal** recording every operation, with batch history, search,
  statistics, report export (text/Markdown/JSON/CSV/TSV) and undo.
- **Dependency-free polling watcher** with stability detection, one-shot mode
  and systemd user-service integration.
- **Configuration profiles**, dotted-key editing, validation, legacy migration
  and environment overrides.
- **JSON output** for every command, plus quiet, verbose and no-colour modes.
- **Shell completions** for bash, zsh and fish.
- **Desktop app** with ten tabs, optional tray icon and keyboard shortcuts.
- **Safety layer**: protected roots, path containment, filename sanitising,
  Windows reserved names, lock file and stale-lock recovery.
- **Hooks and notifications**: before/after/error hooks with timeouts, and
  native desktop notifications.
- **198-test standard-library suite**.
- **Packaging**: PyInstaller specs, per-platform build scripts, release
  packager with checksums, cross-platform smoke test, CI and release workflows.
- **Documentation**: README, feature list, configuration reference,
  architecture notes and contribution guide.
- **MIT license**.

### Changed

- The core engine no longer requires any third-party packages.
- Watcher uses polling instead of an external filesystem-event library.
- Configuration is validated before every mutating run.
- CLI output is consistent, colourised and script-friendly.

### Fixed

- File extensions are preserved when sanitising names (a trailing dot in the
  suffix no longer strips the extension).
- JSON output is always a single valid document for `organize` and
  `duplicates`.
- Intra-batch name collisions are detected before execution.
- Files that disappear between planning and moving are reported as skipped
  instead of raising.
- Restoring from quarantine never overwrites an existing file silently.

### Compatibility

- Python 3.9 or newer.
- Windows 10+, macOS 11+ and modern Linux distributions.
- Existing JSON configuration can be imported with
  `jar config migrate --from <file>`.
