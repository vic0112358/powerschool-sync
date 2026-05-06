#!/usr/bin/env python3
"""Render a date-sorted school/activity report from normalized event items."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any


SOURCE_LABELS = {
    "school": "School",
    "swim": "NOVA Swim",
    "piano": "Selah Studio",
    "hcps": "HCPS Calendar",
}

SOURCE_CLASS = {
    "school": "source-school",
    "swim": "source-swim",
    "piano": "source-piano",
    "hcps": "source-hcps",
}

PRIVATE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"gmail",
        r"mail\.google",
        r"Source Email",
        r"Open email",
        r"PayPal",
        r"paypal",
    )
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Normalized JSON item fixture.")
    parser.add_argument("--private-output", required=True, help="Path for private HTML.")
    parser.add_argument("--public-output", required=True, help="Path for sanitized public HTML.")
    parser.add_argument("--check", action="store_true", help="Validate sort/privacy after rendering.")
    parser.add_argument("--last-sync-attempt", default="", help="Visible last sync attempt timestamp.")
    parser.add_argument("--last-successful-sync", default="", help="Visible last successful sync timestamp.")
    parser.add_argument("--lookback-days", default="", help="Visible Gmail lookback window in days.")
    return parser.parse_args()


def parse_start(item: dict[str, Any]) -> dt.datetime:
    raw = item["start"]
    if len(raw) == 10:
        return dt.datetime.fromisoformat(raw + "T00:00:00+00:00")
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (parse_start(item), item.get("title", "")))


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def format_date(item: dict[str, Any]) -> str:
    return str(item.get("date_display") or esc(item["start"]))


def pill_class(item: dict[str, Any]) -> str:
    status = item.get("status", "").lower()
    if "pending" in item.get("calendar", "").lower():
        return "pill-pending"
    if "html" in item.get("calendar", "").lower():
        return "pill-html"
    if "important" in status or "closure" in status:
        return "pill-important"
    return "pill-standard"


def private_row(item: dict[str, Any]) -> str:
    source_type = item.get("source_type", "school")
    row_class = SOURCE_CLASS.get(source_type, "source-school")
    child = esc(item.get("child", ""))
    source_detail = esc(item.get("source_detail", ""))
    source_url = item.get("source_url")
    source_cell = source_detail
    if source_url:
        source_cell += f'<br><a href="{esc(source_url)}">Open source</a>'
    return f"""          <tr class="{row_class}">
            <td>{child}</td>
            <td>{esc(SOURCE_LABELS.get(source_type, source_type))}</td>
            <td>{esc(item.get("program", ""))}</td>
            <td>{esc(item.get("title", ""))}</td>
            <td>{format_date(item)}</td>
            <td><span class="pill {pill_class(item)}">{esc(item.get("status", ""))}</span></td>
            <td>{esc(item.get("calendar", ""))}</td>
            <td>{esc(item.get("notes", ""))}</td>
            <td>{source_cell}</td>
          </tr>"""


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    public["child"] = item.get("audience", "")
    calendar = str(public.get("calendar", ""))
    if "html" in calendar.lower():
        public["calendar"] = "HTML only"
    elif calendar:
        public["calendar"] = "Calendar covered"
    public.pop("source_detail", None)
    public.pop("source_url", None)
    return public


def public_row(item: dict[str, Any]) -> str:
    source_type = item.get("source_type", "school")
    row_class = SOURCE_CLASS.get(source_type, "source-school")
    return f"""          <tr class="{row_class}">
            <td>{esc(item.get("child", ""))}</td>
            <td>{esc(SOURCE_LABELS.get(source_type, source_type))}</td>
            <td>{esc(item.get("program", ""))}</td>
            <td>{esc(item.get("title", ""))}</td>
            <td>{format_date(item)}</td>
            <td><span class="pill {pill_class(item)}">{esc(item.get("status", ""))}</span></td>
            <td>{esc(item.get("calendar", ""))}</td>
            <td>{esc(item.get("notes", ""))}</td>
          </tr>"""


def render_html(
    items: list[dict[str, Any]],
    *,
    public: bool,
    last_sync_attempt: str = "",
    last_successful_sync: str = "",
    lookback_days: str = "",
) -> str:
    title = "School Events Public Summary" if public else "School Email Sync"
    rows = "\n".join(public_row(public_item(item)) if public else private_row(item) for item in items)
    source_col = "" if public else "\n            <th>Source</th>"
    robots_meta = '<meta name="robots" content="noindex">' if public else ""
    metadata = ""
    if last_sync_attempt or last_successful_sync or lookback_days:
        metadata = f"""
      <dl class="sync-meta">
        <div><dt>Last Sync Attempt</dt><dd>{esc(last_sync_attempt)}</dd></div>
        <div><dt>Last Successful Sync</dt><dd>{esc(last_successful_sync)}</dd></div>
        <div><dt>Lookback Window</dt><dd>{esc(lookback_days)} days</dd></div>
      </dl>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  {robots_meta}
  <title>{title}</title>
  <style>
    :root {{
      --ink: #1f2b37;
      --muted: #627081;
      --panel: #fffdf8;
      --line: #ddd2c4;
      --school: #f8f3ea;
      --swim: #e9f6fb;
      --piano: #f4edfc;
      --hcps: #fff1ea;
      --pending: #8f2f2f;
      --pending-bg: #f8dddd;
      --html: #8a5b00;
      --html-bg: #fff0cb;
      --important: #9b341f;
      --important-bg: #ffe1d5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background: #f6efe6;
    }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 32px 20px 56px; }}
    .hero, .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 16px 42px rgba(31, 43, 55, 0.08);
    }}
    .hero {{ padding: 24px; margin-bottom: 20px; }}
    h1 {{ margin: 0 0 8px; font-size: 38px; line-height: 1.08; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .sync-meta {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0 0; }}
    .sync-meta div {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fffaf2; min-width: 190px; }}
    .sync-meta dt {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }}
    .sync-meta dd {{ margin: 4px 0 0; font-size: 13px; font-weight: 700; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; min-width: {"1180px" if public else "1420px"}; border-collapse: collapse; }}
    th, td {{ padding: 14px 16px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); font-size: 14px; line-height: 1.45; }}
    th {{ background: #f3ede4; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; }}
    tr.source-school {{ background: var(--school); }}
    tr.source-swim {{ background: var(--swim); }}
    tr.source-piano {{ background: var(--piano); }}
    tr.source-hcps {{ background: var(--hcps); }}
    .pill {{ display: inline-flex; border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .pill-pending {{ background: var(--pending-bg); color: var(--pending); }}
    .pill-html {{ background: var(--html-bg); color: var(--html); }}
    .pill-important {{ background: var(--important-bg); color: var(--important); }}
    .pill-standard {{ background: #dff2eb; color: #0f6a58; }}
    a {{ color: #0f6a58; font-weight: 700; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{title}</h1>
      <p>Single-table preview sorted by event date. Row color indicates school, NOVA swim, Selah Studio piano, or HCPS calendar source.</p>{metadata}
    </section>
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{"Audience" if public else "Child"}</th>
            <th>Type</th>
            <th>School / Program</th>
            <th>Event / Deadline</th>
            <th>Date</th>
            <th>Status</th>
            <th>Calendar</th>
            <th>Notes</th>{source_col}
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def validate_public_privacy(path: Path) -> None:
    text = path.read_text()
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise SystemExit(f"public privacy check failed: {pattern.pattern}")


def validate_sorted(items: list[dict[str, Any]]) -> None:
    starts = [parse_start(item) for item in items]
    if starts != sorted(starts):
        raise SystemExit("items are not sorted by start datetime")


def main() -> None:
    args = parse_args()
    items = sort_items(json.loads(Path(args.input).read_text())["items"])
    private_output = Path(args.private_output)
    public_output = Path(args.public_output)
    private_output.parent.mkdir(parents=True, exist_ok=True)
    public_output.parent.mkdir(parents=True, exist_ok=True)
    private_output.write_text(
        render_html(
            items,
            public=False,
            last_sync_attempt=args.last_sync_attempt,
            last_successful_sync=args.last_successful_sync,
            lookback_days=args.lookback_days,
        )
    )
    public_output.write_text(
        render_html(
            items,
            public=True,
            last_sync_attempt=args.last_sync_attempt,
            last_successful_sync=args.last_successful_sync,
            lookback_days=args.lookback_days,
        )
    )
    if args.check:
        validate_sorted(items)
        validate_public_privacy(public_output)
    print(f"rendered private={private_output}")
    print(f"rendered public={public_output}")
    print(f"items={len(items)}")


if __name__ == "__main__":
    main()
