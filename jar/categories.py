"""Built-in file categories and their default destinations.

The order of ``CATEGORY_EXTENSIONS`` matters: when an extension appears in more
than one category the first category wins.  For example ``.iso`` belongs to
``DiskImages`` before ``Archives`` and ``.exe`` belongs to ``Installers``
before ``Executables``.
"""

from __future__ import annotations

CATEGORY_EXTENSIONS: dict[str, list[str]] = {
    "Installers": [
        ".exe", ".msi", ".msix", ".msixbundle", ".apk", ".aab", ".dmg", ".pkg",
        ".deb", ".rpm", ".appimage", ".flatpak", ".snap", ".appx",
    ],
    "DiskImages": [
        ".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".qcow2", ".dmg",
    ],
    "Images": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tif",
        ".tiff", ".heic", ".heif", ".avif", ".ico", ".raw", ".cr2", ".nef",
        ".arw", ".dng", ".orf", ".rw2",
    ],
    "Design": [
        ".psd", ".ai", ".eps", ".xcf", ".sketch", ".fig", ".indd", ".afdesign",
        ".afphoto", ".blend",
    ],
    "3D": [
        ".obj", ".stl", ".fbx", ".gltf", ".glb", ".3ds", ".dae", ".ply", ".usdz",
    ],
    "Videos": [
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
        ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts", ".ogv",
    ],
    "Audio": [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus",
        ".aiff", ".aif", ".alac", ".mid", ".midi", ".amr",
    ],
    "Ebooks": [
        ".epub", ".mobi", ".azw", ".azw3", ".fb2", ".djvu", ".cbz", ".cbr", ".lit",
    ],
    "Documents": [
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".markdown",
        ".tex", ".pages", ".wpd", ".log", ".nfo",
    ],
    "Spreadsheets": [
        ".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv", ".numbers",
    ],
    "Presentations": [
        ".ppt", ".pptx", ".pptm", ".odp", ".key",
    ],
    "Archives": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2",
        ".zst", ".lz", ".lzma", ".cab", ".arj", ".lzh",
    ],
    "Code": [
        ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html",
        ".htm", ".css", ".scss", ".sass", ".less", ".c", ".h", ".cc", ".cpp",
        ".cxx", ".hpp", ".hxx", ".java", ".kt", ".kts", ".go", ".rs", ".rb",
        ".php", ".cs", ".swift", ".m", ".mm", ".lua", ".pl", ".pm", ".sh",
        ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".sql", ".vue",
        ".svelte", ".dart", ".r", ".scala", ".hs", ".clj", ".ex", ".exs",
        ".erl", ".elm", ".nim", ".zig", ".asm", ".s", ".v", ".vhd", ".sv",
        ".ipynb", ".dockerfile", ".makefile",
    ],
    "Data": [
        ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf",
        ".env", ".db", ".sqlite", ".sqlite3", ".parquet", ".avro", ".ndjson",
        ".proto", ".graphql", ".gql", ".lock",
    ],
    "Fonts": [
        ".ttf", ".otf", ".woff", ".woff2", ".eot", ".fon",
    ],
    "Subtitles": [
        ".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx",
    ],
    "Shortcuts": [
        ".lnk", ".url", ".desktop", ".webloc", ".website",
    ],
    "Executables": [
        ".bin", ".run", ".app", ".out", ".elf", ".com", ".scr",
    ],
    "Torrents": [
        ".torrent",
    ],
}

# Human friendly folder names for categories whose folder name differs from the
# category label.  Everything else defaults to its category name.
DEFAULT_CATEGORY_DESTINATIONS: dict[str, str] = {
    "Images": "Pictures",
    "Audio": "Music",
    "Others": "Misc",
}

CATEGORY_ORDER = list(CATEGORY_EXTENSIONS.keys())
ALL_EXTENSIONS = sorted({ext for exts in CATEGORY_EXTENSIONS.values() for ext in exts})


def default_destination(category: str) -> str:
    """Return the default destination folder name for *category*."""
    return DEFAULT_CATEGORY_DESTINATIONS.get(category, category)
