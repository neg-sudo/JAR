# JAR features

JAR 2.0 is a complete rewrite and expansion of the original organizer. The list
below is deliberately exhaustive; every item is implemented in this repository
and covered by the test suite where practical.

## Classification

1. **20+ built-in categories** — Images, Videos, Audio, Documents, Ebooks, Data,
   Code, Archives, Installers, DiskImages, Executables, Fonts, 3DModels,
   Spreadsheets, Presentations, Design, Torrents and Others.
2. **Hundreds of known file extensions** mapped out of the box.
3. **Editable extension map** — add or remove extensions per category.
4. **Custom rules** with their own name, category and destination.
5. **Priority ordering** — lower numbers are evaluated first.
6. **Extension matching** in custom rules.
7. **Glob matching** (`*.tar.gz`, `screenshot-*.png`, …).
8. **Regular-expression matching** on file names.
9. **Minimum and maximum size** conditions per rule.
10. **Minimum and maximum age** conditions per rule.
11. **Stop/continue chaining** so broad rules can feed narrow ones.
12. **Per-rule destination templates**.
13. **Enable/disable individual rules** without deleting them.
14. **Rule testing** (`jar rules test FILE`) before you trust a rule.
15. **Rule management from the CLI** — add, remove, enable, disable.
16. **Custom rule listing** with `--custom`.
17. **Sensible fallback** to `Others` for unknown files.
18. **Category allow/deny filters** for one-off runs.
19. **Disabled or malformed rules are skipped safely**, never crash a run.

## Destinations and modes

20. **Destination templates** with `{category}`, `{ext}`, `{name}`, `{stem}`,
    `{year}`, `{month}`, `{day}`, `{weekday}`, `{size}`, `{profile}`,
    `{home}` and `{dest}`.
21. **Per-category destination overrides** (e.g. Images → `Pictures`).
22. **Date sub-folders** (`year/month`) with a single switch.
23. **Global mode** — everything under one destination root.
24. **Local mode** — sort beside the source file, perfect for projects/drives.
25. **Automatic destination-root detection** for new installations.
26. **Existing-folder detection** so already-sorted files are not re-sorted.
27. **Cross-device moves** handled by `shutil.move`.

## Scanning and filtering

28. **Recursive scanning** (`-r/--recursive`) with a safe default.
29. **Direct file arguments**, not just folders.
30. **Minimum and maximum file size** filters.
31. **Minimum and maximum file age** filters.
32. **Hidden-file skipping**.
33. **Temporary/partial download skipping** (`.part`, `.crdownload`, `.tmp`, …).
34. **Office lock-file skipping** (`~$…`, `.~lock.…`).
35. **System junk skipping** (`.DS_Store`, `Thumbs.db`, `desktop.ini`, …).
36. **Built-in ignore patterns** for VCS, virtualenvs, caches and node modules.
37. **`.jarignore` support** in every watched folder.
38. **Ignore negation** with `!pattern`.
39. **Directory ignore patterns** (`private/`).
40. **Optional symlink following**, off by default.
41. **Graceful handling of unreadable folders** — one bad folder does not abort
    the scan.
42. **Deterministic ordering** of scan results.
43. **Grouped scan statistics** by category.

## Conflict handling

44. **Seven strategies**: rename, skip, overwrite, trash, dedupe, keep newest,
    keep oldest.
45. **Intra-batch collision handling** when two source files share a name.
46. **Content-aware `dedupe`** — identical files are skipped, differing files
    are renamed.
47. **Overwrite is journaled** so it can be undone.
48. **`trash` quarantines the loser** before the winner is moved.
49. **Timestamp comparison** for keep-newest/keep-oldest.
50. **Conflict previews during planning**, before anything is touched.

## Naming and path safety

51. **Filename sanitising** for Windows-invalid characters.
52. **Repeated-whitespace normalisation**.
53. **Optional lowercasing**.
54. **Maximum filename length** with extension preservation.
55. **Windows reserved-name protection** (`CON`, `LPT1`, …).
56. **Trailing dot/space removal**.
57. **Path traversal prevention** — destinations containing `..` are rejected.
58. **Absolute-template rejection**.
59. **Protected-root refusal** — home and filesystem roots cannot be organized.
60. **Destination containment checks** before every move.
61. **Collision-safe `(1)`, `(2)` renaming**.

## Journal, undo and audit

62. **SQLite journal** stored locally in the data directory.
63. **Batch IDs** for every run.
64. **Per-file operation records** with source, destination, category, size,
    digest, status and error.
65. **Undo the last batch**.
66. **Undo multiple batches** with `--last N`.
67. **Undo a specific batch** by ID.
68. **Undo deduplication** as well as organization.
69. **Undo dry runs** to preview a restore.
70. **Idempotent undo** — already-restored operations are skipped.
71. **History browsing** with limits.
72. **Batch history view** (`--batches`).
73. **Full-text history search** across paths, categories and errors.
74. **History clearing** with confirmation.
75. **SQLite vacuum** to reclaim journal space.
76. **Statistics**: files moved, skipped, failed, bytes moved, bytes reclaimed.
77. **Per-category statistics**.
78. **Top file extensions**.
79. **Seven-day activity chart data**.
80. **Database size reporting**.
81. **Text, Markdown, JSON, CSV and TSV report export**.
82. **All commands support `--json`** for scripting and dashboards.

## Duplicates

83. **Size-first grouping** to avoid unnecessary hashing.
84. **Streaming SHA-256** so huge files do not exhaust memory.
85. **Optional empty-file handling**.
86. **Four keeper strategies**: first, oldest, newest, shortest path.
87. **Quarantine duplicates** (undoable) or delete permanently.
88. **Dry-run duplicate removal**.
89. **Duplicate summaries** with file counts and reclaimable bytes.
90. **Duplicate scans can be scoped** by path, age and size.

## Quarantine and deletion

91. **Timestamped quarantine** with collision-safe names.
92. **Quarantine listing** with sizes and ages.
93. **Restore to any folder**, with automatic rename on collision.
94. **Restore path-traversal protection**.
95. **Bulk purge by age** (`--older-than 30d`) with dry-run.
96. **Optional OS trash integration** via Send2Trash.
97. **Permanent deletion** when explicitly requested.

## Watching and automation

98. **Dependency-free polling watcher** — no watchdog required.
99. **File-stability window** so partially downloaded files are ignored.
100. **Process-existing mode** for a first pass at startup.
101. **`--once` mode** for cron, CI and one-shot scripts.
102. **Systemd user-service autostart** (`install`, `remove`, `status`).
103. **Watcher error isolation** — one bad file does not stop the loop.
104. **Graceful start/stop/join** behaviour in tests and long-running sessions.
105. **Configurable poll interval and stability window**.

## CLI experience

106. **Full command set**: organize, watch, scan, stats, history, undo,
     duplicates, quarantine, rules, config, doctor, completions, autostart,
     gui and version.
107. **Aliases** (`org`, `dupes`, `q`) for fast typing.
108. **JSON output everywhere**.
109. **Quiet, verbose and no-colour modes**.
110. **Progress display** for long runs on a TTY.
111. **Colourised tables** and summaries.
112. **Meaningful exit codes** (0 success, 1 failure, 130 interrupted).
113. **Shell completions** for bash, zsh and fish.
114. **Configuration profiles** for separate workflows.
115. **Dotted-key config get/set/unset**.
116. **Configuration validation** with actionable warnings.
117. **Legacy configuration migration**.
118. **`jar doctor`** checks Python, GUI extras, paths, journal, config and
     rules.
119. **`--config` and environment overrides** for sandboxing.
120. **No required third-party packages**.

## Desktop app

121. **Ten-tab desktop app**: Overview, Organize, Watch, Rules, Duplicates,
     Quarantine, History, Stats & Reports, Settings, Doctor.
122. **Uses the same engine and journal** as the CLI.
123. **Optional tray icon** (pystray).
124. **Keyboard shortcuts** — F5 refresh, Ctrl+O organize, Ctrl+D duplicates,
     Ctrl+Z undo.
125. **Live plan preview** before organizing.
126. **Profile switcher and settings editor**.
127. **Report export from the GUI**.
128. **Graceful degradation** to stock Tk when customtkinter is unavailable.
129. **Clear error message** when GUI dependencies are missing.

## Reliability, safety and quality

130. **Lock file** prevents concurrent organizers from colliding.
131. **Stale-lock reclamation**.
132. **Dry-run support on every mutating command**.
133. **Before/after/error hooks** with a timeout.
134. **Fail-closed hook mode**.
135. **Desktop notifications** on Linux, macOS and Windows.
136. **Structured rotating logs**.
137. **Missing-source detection** between plan and execution.
138. **Per-file error isolation** — one failure does not abort the batch.
139. **198-test standard-library suite** covering utilities, safety, config,
     rules, scanning, duplicates, journal, organizer, reports, trash, watcher
     and CLI.
140. **Single-version source of truth** shared by CLI, GUI, packaging and tests.

## Packaging and delivery

141. **PyInstaller specs** for CLI and desktop builds.
142. **Standalone binaries** for Windows, Linux and macOS.
143. **Build scripts** for Linux, macOS and Windows.
144. **Release packager** with versioned archive names and SHA-256 checksums.
145. **Cross-platform smoke test** that runs the real binary through version,
     doctor, organize and undo.
146. **GitHub Actions CI** on Ubuntu, Windows and macOS, Python 3.9 and 3.12.
147. **GitHub Actions release pipeline** for Linux x86_64/arm64, Windows x86_64
     and macOS x86_64/arm64.
148. **MIT licensed** and dependency-light by design.
