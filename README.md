# JAR — Just Automated Routing

**JAR** is a fast, safe, scriptable file organizer for Windows, macOS and Linux.
Point it at a messy folder and it routes files into clean category folders using
rules you control. It ships with a full command line interface, an optional
desktop app, duplicate detection, undoable moves, a quarantine, and a complete
audit journal.

```
Downloads/                         Downloads/
├── invoice.pdf          ┌──▶      ├── Documents/invoice.pdf
├── holiday.jpg          │         ├── Pictures/holiday.jpg
├── setup.exe            │         ├── Installers/setup.exe
├── notes.md             │         ├── Documents/notes.md
└── song.flac            └──▶      ├── Audio/song.flac
                                   └── …
```

- **Zero required dependencies** — the core engine, CLI and test suite use the
  Python standard library only.
- **Seven conflict strategies** — rename, skip, overwrite, trash, dedupe,
  keep newest, keep oldest.
- **Everything is undoable** — every batch is recorded in a local SQLite
  journal.
- **Safe by design** — protected paths, dry runs, a lock file, filename
  sanitising, path-escape checks, and an undoable quarantine.

---

## Quick start

```bash
# 1. Install (Python 3.9+)
pipx install jar-organizer          # or: pip install jar-organizer

# 2. Create a starter configuration
jar config init

# 3. See what would happen (nothing is changed)
jar organize ~/Downloads --dry-run

# 4. Do it
jar organize ~/Downloads

# 5. Change your mind
jar undo
```

Prefer a binary? Download the archive for your platform from the
[releases page](https://github.com/neg-sudo/JAR/releases), unpack it and run
`jar` (or `jar.exe` on Windows). A separate `jar-desktop` application is
included.

---

## Installation

### From source

```bash
git clone https://github.com/neg-sudo/JAR.git
cd JAR
python -m pip install .
jar --version
```

### Optional extras

```bash
pip install "jar-organizer[gui]"    # desktop app (Tk/customtkinter + pillow + pystray)
pip install "jar-organizer[trash]"  # send deletions to the OS trash
pip install "jar-organizer[all]"    # everything
pip install "jar-organizer[dev]"    # tests and build tooling
```

`jar` works without any extras. `jar doctor` tells you what is available.

---

## Command line

| Command | What it does |
| --- | --- |
| `jar organize [paths]` | Plan and move files into category folders |
| `jar watch [paths]` | Watch folders and organize new files as they arrive |
| `jar scan [paths]` | Preview the plan without touching anything |
| `jar duplicates [paths]` | Find (and optionally remove) duplicate files |
| `jar stats` | Activity statistics and report export |
| `jar history` | Browse or search the operation journal |
| `jar undo` | Undo the last — or any recorded — batch |
| `jar quarantine list\|restore\|purge` | Manage replaced/removed files |
| `jar rules list\|test\|add\|remove\|enable\|disable` | Inspect and edit classification rules |
| `jar config show\|get\|set\|unset\|path\|init\|validate\|migrate\|profiles` | Manage configuration |
| `jar doctor` | Diagnose installation and configuration problems |
| `jar completions bash\|zsh\|fish` | Print shell completion code |
| `jar autostart install\|remove\|status` | Install a systemd user watcher (Linux) |
| `jar gui` | Launch the desktop app |
| `jar version` | Print version information |

Global flags work before or after the command: `--json`, `-q/--quiet`,
`-v/--verbose`, `--no-color`, `--config PATH`, `--profile NAME`, `--dry-run`.

### Everyday examples

```bash
# Organize two folders recursively, skipping anything already there
jar organize ~/Downloads ~/Desktop --recursive --conflict skip

# Preview only: show the table and totals
jar scan ~/Downloads --stats

# Move replaced files to quarantine instead of overwriting
jar organize ~/Downloads --conflict trash --trash

# Watch forever, starting with what is already there
jar watch ~/Downloads --existing

# Find duplicates and move extras to quarantine
jar duplicates ~/Downloads --recursive --trash --keep oldest

# Reclaim space permanently (asks for confirmation)
jar duplicates ~/Downloads --delete

# Export a report for the last week
jar stats --export report.md

# Undo the last three batches
jar undo --last 3 --yes
```

### Machine-readable output

Every command accepts `--json` and emits exactly one JSON document:

```bash
jar --json organize ~/Downloads --dry-run | jq '.plan.moves'
jar --json duplicates ~/Downloads | jq '.wasted_bytes'
jar --json stats | jq '.by_category'
```

Exit codes: `0` success, `1` error or a failed operation, `130` interrupted.

---

## How classification works

JAR ships with sensible categories: Images, Videos, Audio, Documents, Ebooks,
Data, Code, Archives, Installers, DiskImages, Executables, Fonts, 3DModels,
Spreadsheets, Presentations, Design, Torrents, and a fallback to Others.

Resolution order:

1. **Custom rules** (`rules`) sorted by `priority` (lower wins).
2. **Built-in categories** from the `categories` map.
3. **Fallback** to `Others`.

A custom rule can match on `extensions`, `globs`, `regex`, size and age, and can
stop or continue rule evaluation. Test a rule before using it:

```bash
jar rules test ~/Downloads/screenshot-2026-01-01.png
jar rules add --name screenshots --category Screenshots \
    --regex '^screenshot.*\.png$' --dest 'Pictures/Screenshots' --priority 5
jar rules list --custom
```

### Destination templates

The default template is `{category}`. Templates support:

`{category}` `{ext}` `{name}` `{stem}` `{year}` `{month}` `{day}` `{weekday}`
`{size}` `{profile}` `{home}` `{dest}`

```jsonc
"destination_template": "{category}/{year}/{month}",
"date_subfolders": false,
"category_destinations": {
  "Images": "Pictures",
  "Documents": "Documents",
  "Code": "Projects/Code"
}
```

Templates may not be absolute and may not contain `..`; JAR refuses to move a
file outside the destination root.

### Global vs local mode

- **Global** (default): everything goes under `dest_root`.
- **Local**: files are sorted into category folders beside the files themselves
  — ideal for a single project or drive.

```bash
jar organize ~/Downloads --mode local
```

### Ignoring files

Hidden files, temporary downloads (`.part`, `.crdownload`, …), Office lock files
and well-known system files are skipped by default. Add your own patterns to the
configuration or drop a `.jarignore` in a watched folder:

```gitignore
# .jarignore
*.iso
private/
!keep-me.iso
```

Patterns support `*`, `?`, `**`, directory patterns ending in `/`, and `!`
negation.

---

## Conflicts

When the destination already contains a file with the same name:

| Strategy | Behaviour |
| --- | --- |
| `rename` *(default)* | Keep both, add ` (1)`, ` (2)`, … |
| `skip` | Leave the source where it is |
| `overwrite` | Replace the existing file (recorded, undoable) |
| `trash` | Move the existing file to quarantine, then move the new one |
| `dedupe` | Skip identical content; rename different content |
| `keep_newest` | Keep the newer file |
| `keep_oldest` | Keep the older file |

```bash
jar organize ~/Downloads --conflict dedupe
```

---

## Undo, history and quarantine

Every move, skip, delete and restore is written to a SQLite journal in the data
directory. That makes operations auditable and reversible.

```bash
jar history                       # recent operations
jar history --batches             # groups by run
jar history --search invoice.pdf  # search paths, categories and errors
jar undo                          # undo the last batch
jar undo --batch <id>             # undo a specific batch
jar undo --last 3                 # undo several batches
```

Replaced or duplicate files are moved to an undoable quarantine when enabled:

```bash
jar quarantine list
jar quarantine restore 20260101-120000-abc__report.pdf --to ~/Downloads
jar quarantine purge --older-than 30d
```

---

## Watching folders

`jar watch` uses a dependency-free polling watcher. Files are only processed
once they have stopped changing, so partially downloaded files are ignored.

```bash
jar watch ~/Downloads ~/Desktop
jar watch ~/Downloads --interval 1 --stability 3
jar watch --once                 # one pass, useful in scripts and cron
```

On Linux, install it as a systemd user service:

```bash
jar autostart install
jar autostart status
jar autostart remove
```

---

## Desktop app

```bash
pip install "jar-organizer[gui]"
jar gui          # or run the jar-desktop binary
```

The desktop app provides ten tabs — Overview, Organize, Watch, Rules,
Duplicates, Quarantine, History, Stats & Reports, Settings and Doctor — plus an
optional tray icon and keyboard shortcuts:

| Shortcut | Action |
| --- | --- |
| `F5` | Refresh everything |
| `Ctrl+O` | Organize now |
| `Ctrl+D` | Find duplicates |
| `Ctrl+Z` | Undo last batch |

The GUI uses the same engine and journal as the CLI, so changes made in either
place are visible in both.

---

## Configuration

Default locations:

| Platform | Configuration | Data (journal, logs, quarantine) |
| --- | --- | --- |
| Linux | `~/.config/jar/config.json` | `~/.local/share/jar/` |
| macOS | `~/.config/jar/config.json` | `~/.local/share/jar/` |
| Windows | `~/.config/jar/config.json` | `~/.local/share/jar/` |

Override with `--config`, `JAR_CONFIG_DIR`, `JAR_DATA_DIR` or
`JAR_CONFIG_FILE`.

```bash
jar config init                    # create a starter config
jar config path                    # show every path
jar config show                    # effective configuration
jar config get conflict
jar config set conflict dedupe
jar config unset conflict
jar config validate
jar config profiles --create media --use media
jar config migrate --from old-config.json
```

Frequently used keys:

| Key | Default | Purpose |
| --- | --- | --- |
| `mode` | `global` | `global` or `local` |
| `dest_root` | auto-detected | destination for global mode |
| `watch_dirs` | auto-detected | folders used when no path is given |
| `conflict` | `rename` | conflict strategy |
| `recursive` | `false` | descend into sub-folders |
| `use_trash` | `false` | quarantine replaced files |
| `dry_run` | `false` | never modify files |
| `min_size` / `max_size` | `0` | size filters (bytes) |
| `min_age_seconds` / `max_age_seconds` | `0` | age filters |
| `include_categories` / `exclude_categories` | `[]` | category filters |
| `sanitize_names` | `false` | remove characters invalid on Windows |
| `normalize_names` | `false` | collapse repeated whitespace |
| `lowercase_names` | `false` | lowercase file names |
| `cleanup_empty_dirs` | `false` | remove emptied source folders |
| `ignore_hidden` | `true` | skip dotfiles |
| `watch_interval` / `watch_stability` | `2.0` | polling seconds |
| `notifications` | `true` | desktop notifications |
| `lock_enabled` | `true` | prevent concurrent runs |
| `hooks.before_move` / `after_move` / `on_error` | `""` | shell hooks |

Profiles let you keep independent setups (for example `media` and `work`):

```bash
jar config profiles --create media
jar config profiles --use media
jar config set dest_root ~/Media
jar organize --profile media ~/Downloads
```

---

## Safety model

- Refuses to organize your home directory or a filesystem root.
- All destinations must stay inside the destination root; `..` is rejected.
- Dry runs are available on every mutating command.
- A lock file prevents two JAR processes from organizing the same data at once.
- Moves are journaled before/after they happen, so failures are visible.
- Replaced files go to quarantine, never straight to oblivion, when enabled.
- Optional hooks run with a timeout and can fail closed.
- No telemetry, no network access, no accounts.

---

## Development

```bash
git clone https://github.com/neg-sudo/JAR.git
cd JAR
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m unittest discover -s tests -t .   # full test suite
python -m compileall -q jar
python scripts/smoke_test.py --source
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, and
[FEATURES.md](FEATURES.md) for an exhaustive feature list.

### Building release binaries

PyInstaller specs live in `packaging/`. Convenience scripts build, test and
package the binaries on each platform:

```bash
./build_linux.sh
./build_macos.sh
build_windows.bat
```

The scripts run the test suite, build `jar` and `jar-desktop`, smoke test the
CLI binary, and produce a versioned archive plus `SHA256SUMS.txt` in `release/`.

GitHub Actions does the same automatically:

- `.github/workflows/ci.yml` — tests on Ubuntu, Windows and macOS with Python
  3.9 and 3.12.
- `.github/workflows/release.yml` — triggered by a `v*` tag (or manually);
  builds Linux x86_64/arm64, Windows x86_64 and macOS x86_64/arm64, then
  publishes a GitHub release with all archives and checksums.

```bash
git tag v2.0.0
git push origin v2.0.0
```

---

## License

MIT — see [LICENSE](LICENSE).

JAR is an independent project. It stores everything locally and never uploads
your file names, paths or contents.
