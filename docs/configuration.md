# Configuration reference

JAR reads a single JSON document. Missing keys fall back to built-in defaults,
so you only need to write the values you want to change. Use
`jar config show` to see the effective result and `jar config validate` to
check it.

Default file: `~/.config/jar/config.json` on all platforms. Override it with
`--config PATH`, `JAR_CONFIG_FILE`, or relocate the whole directory with
`JAR_CONFIG_DIR` and `JAR_DATA_DIR`.

## Complete example

```json
{
  "version": 2,
  "profile": "default",
  "profiles": {},
  "mode": "global",
  "dest_root": "~/Sorted",
  "watch_dirs": ["~/Downloads", "~/Desktop"],
  "recursive": false,
  "follow_symlinks": false,
  "conflict": "rename",
  "dry_run": false,
  "use_trash": false,
  "quarantine_dir": "",
  "notifications": true,
  "notify_on_summary": true,
  "cleanup_empty_dirs": false,
  "sanitize_names": false,
  "normalize_names": false,
  "lowercase_names": false,
  "max_filename_length": 200,
  "date_subfolders": false,
  "destination_template": "{category}",
  "category_destinations": {
    "Images": "Pictures",
    "Videos": "Videos"
  },
  "categories": {
    "Documents": [".pdf", ".docx", ".txt", ".md"]
  },
  "rules": [
    {
      "name": "screenshots",
      "category": "Screenshots",
      "priority": 5,
      "enabled": true,
      "regex": "^screenshot.*\\.png$",
      "destination": "Pictures/Screenshots",
      "stop": true
    }
  ],
  "ignore_hidden": true,
  "ignore_patterns": ["node_modules/", "*.part"],
  "ignore_files": [".jarignore"],
  "min_age_seconds": 0,
  "max_age_seconds": 0,
  "min_size": 0,
  "max_size": 0,
  "include_categories": [],
  "exclude_categories": [],
  "watch_interval": 2.0,
  "watch_stability": 2.0,
  "watch_existing": false,
  "hooks": {
    "before_move": "",
    "after_move": "",
    "on_error": "",
    "timeout": 10,
    "fail_closed": false
  },
  "log_level": "INFO",
  "log_max_bytes": 1048576,
  "log_backups": 3,
  "lock_enabled": true,
  "lock_timeout": 0,
  "lock_stale_seconds": 3600,
  "protected_paths": [],
  "theme": "dark",
  "json_indent": 2
}
```

## Keys

### General

| Key | Type | Description |
| --- | --- | --- |
| `version` | integer | Configuration schema version. Do not edit manually. |
| `profile` | string | Active profile name. |
| `profiles` | object | Named overlays merged over the base configuration. |
| `mode` | `global` \| `local` | Sort under `dest_root` or beside the source. |
| `dest_root` | path | Root for global mode. Empty means auto-detect. |
| `watch_dirs` | list[path] | Default folders for commands run without paths. |
| `dry_run` | boolean | Force every run to be a preview. |
| `theme` | string | GUI theme name. |
| `json_indent` | integer | Indentation used by `--json` output. |

### Classification and destinations

| Key | Type | Description |
| --- | --- | --- |
| `categories` | object | Map of category → list of extensions. |
| `rules` | list[object] | Custom rules, evaluated by ascending `priority`. |
| `destination_template` | string | Template for destination folders. |
| `category_destinations` | object | Per-category override of the template. |
| `date_subfolders` | boolean | Append `year/month` unless the template has them. |

Rule object:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Unique, human-readable rule name. |
| `category` | string | Category assigned on a match. |
| `priority` | integer | Lower runs first (default 100 for built-ins, 10 for CLI-added rules). |
| `enabled` | boolean | Set to `false` to keep but disable. |
| `extensions` | list[string] | Extensions with or without a leading dot. |
| `globs` | list[string] | Shell-style patterns matched against name and full path. |
| `regex` | string | Case-insensitive pattern matched against the file name. |
| `destination` | string | Optional template override for this rule. |
| `min_size` / `max_size` | integer | Size window in bytes. |
| `min_age` / `max_age` | integer | Age window in seconds. |
| `stop` | boolean | Stop evaluating later rules on a match (default `true`). |

### Filtering

| Key | Type | Description |
| --- | --- | --- |
| `recursive` | boolean | Descend into sub-folders. |
| `follow_symlinks` | boolean | Follow symlinked directories. |
| `ignore_hidden` | boolean | Skip dotfiles and hidden directories. |
| `ignore_patterns` | list[string] | Global ignore patterns. |
| `ignore_files` | list[string] | Per-folder ignore file names (default `.jarignore`). |
| `min_age_seconds` / `max_age_seconds` | integer | File age window. |
| `min_size` / `max_size` | integer | File size window in bytes. |
| `include_categories` | list[string] | If non-empty, only these categories. |
| `exclude_categories` | list[string] | Categories to skip. |

### Conflicts and safety

| Key | Type | Description |
| --- | --- | --- |
| `conflict` | string | One of `rename`, `skip`, `overwrite`, `trash`, `dedupe`, `keep_newest`, `keep_oldest`. |
| `use_trash` | boolean | Quarantine replaced files. |
| `quarantine_dir` | path | Custom quarantine location (default: data dir). |
| `sanitize_names` | boolean | Remove Windows-invalid characters. |
| `normalize_names` | boolean | Collapse repeated whitespace. |
| `lowercase_names` | boolean | Lowercase file names. |
| `max_filename_length` | integer | Maximum name length including extension. |
| `cleanup_empty_dirs` | boolean | Remove source folders emptied by a move. |
| `protected_paths` | list[path] | Extra paths JAR must never modify. |
| `lock_enabled` | boolean | Prevent concurrent runs. |
| `lock_timeout` | number | Seconds to wait for a lock (0 = fail fast). |
| `lock_stale_seconds` | integer | Reclaim locks older than this. |

### Watching

| Key | Type | Description |
| --- | --- | --- |
| `watch_interval` | number | Seconds between scans (minimum 0.25). |
| `watch_stability` | number | Seconds a file must remain unchanged. |
| `watch_existing` | boolean | Process files present at watcher startup. |

### Hooks

| Key | Type | Description |
| --- | --- | --- |
| `hooks.before_move` | string | Shell command run before a move. |
| `hooks.after_move` | string | Shell command run after a move. |
| `hooks.on_error` | string | Shell command run after a failure. |
| `hooks.timeout` | number | Seconds before a hook is killed. |
| `hooks.fail_closed` | boolean | Skip the file if `before_move` fails. |

Hook commands receive `JAR_SOURCE`, `JAR_DEST`, `JAR_CATEGORY`, `JAR_SIZE` and
`JAR_BATCH` in the environment.

### Logging and notifications

| Key | Type | Description |
| --- | --- | --- |
| `notifications` | boolean | Enable desktop notifications. |
| `notify_on_summary` | boolean | Only notify with a summary, not per file. |
| `log_level` | string | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `log_max_bytes` | integer | Rotate the log at this size. |
| `log_backups` | integer | Number of rotated logs to keep. |

## Profiles

Profiles are overlays stored under `profiles`. The base configuration stays
intact; the active profile is selected with `profile`, `--profile` or
`jar config profiles --use NAME`.

```bash
jar config profiles --create media
jar config profiles --use media
jar config set dest_root ~/Media
jar config set conflict dedupe
```

While a profile is active, `jar config set` writes into that profile. Deleting
the active profile falls back to `default`.

## Environment variables

| Variable | Effect |
| --- | --- |
| `JAR_CONFIG_DIR` | Directory containing `config.json`. |
| `JAR_CONFIG_FILE` | Exact path to the configuration file. |
| `JAR_DATA_DIR` | Directory for the journal, logs and quarantine. |
| `NO_COLOR` | Disable ANSI colour output. |
| `XDG_CONFIG_HOME` / `XDG_DATA_HOME` | Standard Unix base directories. |

## Validation

`jar config validate` returns errors for invalid enums, malformed rules,
unknown destination templates and unsafe paths, and warnings for missing watch
folders. `jar doctor` combines validation with installation checks.
