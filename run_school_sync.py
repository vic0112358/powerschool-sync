#!/usr/bin/env python3
"""Unified local runner for report render, calendar sync, deploy, and logging."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from google_calendar_sync import load_config, sync_payload
from render_school_report import render_html, sort_items, validate_public_privacy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="school_sync_config.json")
    parser.add_argument("--catalog", default="school_events_catalog.json")
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-calendar", action="store_true")
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--deploy-gh-pages", action="store_true", help="Explicitly publish the sanitized public report to GitHub Pages.")
    return parser.parse_args()


def build_calendar_payload(config: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for item in items:
        sync = item.get("calendar_sync")
        if not sync:
            continue
        for target in sync["targets"]:
            event = {
                "source_event_id": item["id"],
                "calendar_key": target,
                "title": sync.get("title_by_target", {}).get(target, sync.get("title", item["title"])),
                "start": item["start"],
                "end": item["end"],
                "timezone": config["timezone"],
                "description": sync.get("description", item.get("notes", "")),
                "visibility": "private",
                "transparency": "transparent",
                "search_time_min": sync["search_time_min"],
                "search_time_max": sync["search_time_max"],
            }
            if "location" in sync:
                event["location"] = sync["location"]
            if "dedupe_query_by_target" in sync:
                event["dedupe_query"] = sync["dedupe_query_by_target"][target]
            elif "dedupe_query" in sync:
                event["dedupe_query"] = sync["dedupe_query"]
            events.append(event)
    return {"events": events}


def update_item_statuses(items: list[dict[str, Any]], sync_summary: dict[str, Any]) -> None:
    per_item: dict[str, dict[str, int]] = {}
    for result in sync_summary.get("results", []):
        source_id = result.get("source_event_id")
        if not source_id:
            continue
        bucket = per_item.setdefault(source_id, {"created": 0, "duplicate": 0, "targets": 0})
        bucket["targets"] += 1
        if result["status"] == "created":
            bucket["created"] += 1
        elif result["status"] == "duplicate":
            bucket["duplicate"] += 1

    for item in items:
        if item["id"] not in per_item:
            continue
        bucket = per_item[item["id"]]
        if bucket["created"] == bucket["targets"]:
            if bucket["targets"] > 1:
                item["calendar"] = "Added to both calendars"
            else:
                item["calendar"] = "Added"
        elif bucket["duplicate"] == bucket["targets"]:
            if bucket["targets"] > 1:
                item["calendar"] = "Both calendars covered"
            else:
                item["calendar"] = "Existing on calendar"
        else:
            item["calendar"] = "Partially synced"


def render_reports(config: dict[str, Any], items: list[dict[str, Any]], sync_at: str) -> None:
    private_path = Path(config["html_output_path"])
    public_path = Path(config["public_html_output_path"])
    private_path.write_text(
        render_html(
            items,
            public=False,
            last_sync_attempt=sync_at,
            last_successful_sync=sync_at,
            lookback_days=str(config["gmail_days_back"]),
        )
    )
    public_path.write_text(
        render_html(
            items,
            public=True,
            last_sync_attempt=sync_at,
            last_successful_sync=sync_at,
            lookback_days=str(config["gmail_days_back"]),
        )
    )
    validate_public_privacy(public_path)


def append_run_log(config: dict[str, Any], trigger: str, status: str, changed: bool, calendar_added: int, deploy_state: str, note: str) -> None:
    line = (
        f"{datetime.now().astimezone().isoformat(timespec='seconds')} | "
        f"status={status} | "
        f"trigger={trigger} | "
        f"lookback_days={config['gmail_days_back']} | "
        f"private_page_changed={'yes' if changed else 'no'} | "
        f"calendar_added={calendar_added} | "
        f"public_deploy={deploy_state} | "
        f"note={note}"
    )
    with Path(config["run_log_path"]).open("a") as fh:
        fh.write(line + "\n")


def deploy_public(project_dir: Path, config: dict[str, Any]) -> str:
    provider = config.get("public_deploy", {}).get("provider")
    if provider != "github_pages":
        return "unsupported"
    proc = subprocess.run(
        [str(project_dir / "deploy_public_to_gh_pages.sh")],
        cwd=project_dir,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GH_PAGES_SUPPRESS_RUN_LOG": "1"},
    )
    if proc.returncode != 0:
        return "failed"
    return "succeeded"


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent
    config = load_config(project_dir / args.config)
    catalog = json.loads((project_dir / args.catalog).read_text())
    items = sort_items(catalog["items"])
    calendar_added = 0
    note_bits: list[str] = []
    run_status = "success"
    sync_at = datetime.now().astimezone().isoformat(timespec="seconds")

    if not args.skip_calendar:
        payload = build_calendar_payload(config, items)
        try:
            sync_summary = sync_payload(config, payload, args.dry_run)
            update_item_statuses(items, sync_summary)
            calendar_added = sync_summary["created"]
            note_bits.append(f"calendar created={sync_summary['created']} skipped={sync_summary['skipped']}")
        except requests.exceptions.RequestException as exc:
            run_status = "partial"
            note_bits.append(f"calendar sync failed: {exc.__class__.__name__}")
    else:
        note_bits.append("calendar sync skipped")

    render_reports(config, items, sync_at)
    note_bits.append(f"items rendered={len(items)}")

    deploy_state = "skipped"
    if args.deploy_gh_pages:
        if args.skip_deploy:
            note_bits.append("GitHub Pages deploy skipped by --skip-deploy")
        elif args.dry_run:
            note_bits.append("GitHub Pages deploy skipped for dry run")
        else:
            deploy_state = deploy_public(project_dir, config)
            note_bits.append(f"deploy={deploy_state}")
            if deploy_state != "succeeded":
                run_status = "partial"
    else:
        note_bits.append("GitHub Pages deploy skipped; pass --deploy-gh-pages to publish")

    append_run_log(
        config,
        trigger=args.trigger,
        status="dry-run" if args.dry_run else run_status,
        changed=True,
        calendar_added=calendar_added,
        deploy_state=deploy_state,
        note=f"status={run_status}; " + "; ".join(note_bits),
    )
    print(json.dumps({
        "items": len(items),
        "calendar_added": calendar_added,
        "deploy_state": deploy_state,
        "dry_run": args.dry_run,
        "status": run_status,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
