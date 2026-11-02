"""Human, JSON, CSV and Markdown reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .utils import atomic_write_text, format_table, format_ts, human_size


def _summary_lines(stats: dict[str, Any]) -> list[str]:
    return [
        f"Files moved:      {stats.get('moved', 0)}",
        f"Bytes routed:     {human_size(stats.get('bytes_moved', 0))}",
        f"Restored:         {stats.get('restored', 0)}",
        f"Trashed/deleted:  {stats.get('trashed', 0)}",
        f"Skipped:          {stats.get('skipped', 0)}",
        f"Failed:           {stats.get('failed', 0)}",
        f"Batches:          {stats.get('batches', 0)}",
        f"Space reclaimed:  {human_size(stats.get('bytes_reclaimed', 0))}",
        f"First activity:   {format_ts(stats.get('first_activity'))}",
        f"Last activity:    {format_ts(stats.get('last_activity'))}",
    ]


def report_text(stats: dict[str, Any]) -> str:
    """Render a readable multi-section report."""
    lines = ["JAR report", "=" * 60]
    lines.append(f"Generated: {format_ts(stats.get('generated_at'))}")
    lines.append("")
    lines.extend(_summary_lines(stats))

    categories = stats.get("by_category") or []
    lines.extend(["", "By category", "-" * 60])
    if categories:
        lines.append(
            format_table(
                ["Category", "Files", "Size"],
                [[row["category"], row["count"], human_size(row["bytes"])] for row in categories],
                max_widths=[30, 8, 12],
            )
        )
    else:
        lines.append("No category activity yet.")

    extensions = stats.get("by_extension") or []
    lines.extend(["", "Top extensions", "-" * 60])
    if extensions:
        lines.append(
            format_table(
                ["Extension", "Files", "Size"],
                [
                    [f".{row['extension']}" if row["extension"] != "none" else "-", row["count"], human_size(row["bytes"])]
                    for row in extensions
                ],
                max_widths=[14, 8, 12],
            )
        )
    else:
        lines.append("No extension activity yet.")

    days = stats.get("last_7_days") or []
    lines.extend(["", "Last 7 days", "-" * 60])
    if days:
        lines.append(
            format_table(
                ["Date", "Files", "Size"],
                [[row["date"], row["count"], human_size(row["bytes"])] for row in days],
            )
        )
    else:
        lines.append("No recent activity.")

    actions = stats.get("by_action") or []
    if actions:
        lines.extend(["", "Actions", "-" * 60])
        lines.append(
            format_table(
                ["Action", "Count"],
                [[row["action"], row["count"]] for row in actions],
            )
        )
    return "\n".join(lines)


def export_report(stats: dict[str, Any], path: Path | str, fmt: str | None = None) -> Path:
    """Export *stats* to JSON, CSV or Markdown based on the extension."""
    target = Path(path).expanduser()
    if fmt is None:
        fmt = target.suffix.lower().lstrip(".") or "json"
    fmt = fmt.lower()
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ("json",):
        atomic_write_text(target, json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    elif fmt in ("md", "markdown"):
        atomic_write_text(target, report_text(stats) + "\n")
    elif fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        rows = []
        for section, key in (("category", "by_category"), ("extension", "by_extension")):
            for row in stats.get(key) or []:
                rows.append(
                    {
                        "section": section,
                        "name": row.get("category") or row.get("extension"),
                        "count": row.get("count", 0),
                        "bytes": row.get("bytes", 0),
                    }
                )
        for row in stats.get("last_7_days") or []:
            rows.append(
                {
                    "section": "day",
                    "name": row.get("date"),
                    "count": row.get("count", 0),
                    "bytes": row.get("bytes", 0),
                }
            )
        import io

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["section", "name", "count", "bytes"], delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
        atomic_write_text(target, buffer.getvalue())
    else:
        raise ValueError(f"unsupported report format: {fmt}")
    return target
