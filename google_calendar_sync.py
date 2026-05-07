#!/usr/bin/env python3
"""Local Google Calendar sync using raw OAuth + Calendar REST API."""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 30


class HttpRequestError(Exception):
    """Raised when an HTTP request returns a non-2xx response."""


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = TIMEOUT,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    request_headers = dict(headers or {})
    body: bytes | None = None
    if json_body is not None:
        request_headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    elif data is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode("utf-8")

    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HttpRequestError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HttpRequestError(f"Network error for {url}: {exc.reason}") from exc

    if not payload:
        return {}
    return json.loads(payload.decode("utf-8"))


def load_config(config_path: Path) -> dict[str, Any]:
    return json.loads(config_path.read_text())


def iso_to_dt(value: str) -> datetime:
    if len(value) == 10:
        return datetime.fromisoformat(value + "T00:00:00")
    return datetime.fromisoformat(value)


@dataclass
class GoogleCalendarAuth:
    config: dict[str, Any]
    _redirect_port: int | None = None

    @property
    def client_secret_path(self) -> Path:
        return Path(self.config["google_calendar_api"]["client_secret_path"])

    @property
    def token_path(self) -> Path:
        return Path(self.config["google_calendar_api"]["token_path"])

    @property
    def scopes(self) -> list[str]:
        return list(self.config["google_calendar_api"]["scopes"])

    @property
    def redirect_uri(self) -> str:
        port = self._redirect_port or self.config["google_calendar_api"]["oauth_redirect_port"]
        return f"http://127.0.0.1:{port}/oauth2callback"

    def _choose_port(self) -> int:
        preferred = int(self.config["google_calendar_api"]["oauth_redirect_port"])
        for port in [preferred, preferred + 1, preferred + 2, preferred + 10, 0]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                return sock.getsockname()[1]
        raise RuntimeError("No available localhost port for OAuth callback")

    def read_client(self) -> dict[str, Any]:
        raw = json.loads(self.client_secret_path.read_text())
        return raw.get("installed") or raw.get("web") or raw

    def read_token(self) -> dict[str, Any]:
        return json.loads(self.token_path.read_text())

    def write_token(self, token: dict[str, Any]) -> None:
        self.token_path.write_text(json.dumps(token, indent=2) + "\n")

    def authorize(self) -> None:
        client = self.read_client()
        state = secrets.token_urlsafe(24)
        code_holder: dict[str, str] = {}
        self._redirect_port = self._choose_port()

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if parsed.path != "/oauth2callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                if params.get("state", [""])[0] != state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"State mismatch.")
                    return
                code_holder["code"] = params.get("code", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Google Calendar auth complete.</h1>You can close this tab.</body></html>")

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        auth_params = {
            "client_id": client["client_id"],
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(auth_params)
        server = HTTPServer(("127.0.0.1", self._redirect_port), CallbackHandler)
        print("Open this URL if the browser does not launch:")
        print(auth_url)
        webbrowser.open(auth_url)
        while "code" not in code_holder:
            server.handle_request()

        token = http_json(
            GOOGLE_TOKEN_URL,
            method="POST",
            data={
                "code": code_holder["code"],
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
        self.write_token(token)
        print(f"Saved token to {self.token_path}")

    def access_token(self) -> str:
        token = self.read_token()
        if int(token.get("expires_at", 0)) > int(time.time()) + 60:
            return token["access_token"]

        client = self.read_client()
        refreshed = http_json(
            GOOGLE_TOKEN_URL,
            method="POST",
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        token["access_token"] = refreshed["access_token"]
        token["expires_at"] = int(time.time()) + int(refreshed.get("expires_in", 0))
        self.write_token(token)
        return token["access_token"]


class GoogleCalendarClient:
    def __init__(self, auth: GoogleCalendarAuth):
        self.auth = auth

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.auth.access_token()}"}

    def search_events(self, calendar_id: str, query: str, time_min: str, time_max: str) -> list[dict[str, Any]]:
        payload = http_json(
            f"{GOOGLE_CALENDAR_API}/calendars/{urllib.parse.quote(calendar_id, safe='')}/events",
            headers=self._headers(),
            params={
                "q": query,
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "maxResults": 25,
                "orderBy": "startTime",
            },
        )
        return payload.get("items", [])

    def create_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return http_json(
            f"{GOOGLE_CALENDAR_API}/calendars/{urllib.parse.quote(calendar_id, safe='')}/events",
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
            json_body=body,
        )


def normalize_title(value: str) -> str:
    return " ".join(value.lower().split())


def event_matches(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_title = normalize_title(existing.get("summary", ""))
    if existing_title != normalize_title(candidate["title"]):
        return False
    existing_start = existing.get("start", {}).get("dateTime") or existing.get("start", {}).get("date")
    return existing_start == candidate["start"]


def build_google_body(candidate: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": candidate["title"],
        "description": candidate.get("description", ""),
        "visibility": candidate.get("visibility", "private"),
        "transparency": candidate.get("transparency", "transparent"),
    }
    if candidate.get("location"):
        body["location"] = candidate["location"]
    if len(candidate["start"]) == 10:
        body["start"] = {"date": candidate["start"]}
        body["end"] = {"date": candidate["end"]}
    else:
        body["start"] = {"dateTime": candidate["start"], "timeZone": candidate["timezone"]}
        body["end"] = {"dateTime": candidate["end"], "timeZone": candidate["timezone"]}
    return body


def sync_payload(config: dict[str, Any], payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    auth = GoogleCalendarAuth(config)
    client = GoogleCalendarClient(auth)
    created = 0
    skipped = 0
    results: list[dict[str, Any]] = []
    for event in payload["events"]:
        calendar_id = event.get("calendar_id") or config["calendar_ids"][event["calendar_key"]]
        query = event.get("dedupe_query") or event["title"]
        existing = client.search_events(calendar_id, query, event["search_time_min"], event["search_time_max"])
        if any(event_matches(item, event) for item in existing):
            skipped += 1
            print(f"SKIP {calendar_id} {event['title']} ({event['start']}) duplicate")
            results.append({
                "source_event_id": event.get("source_event_id"),
                "calendar_key": event["calendar_key"],
                "calendar_id": calendar_id,
                "status": "duplicate",
                "title": event["title"],
                "start": event["start"],
            })
            continue
        if dry_run:
            print(f"DRYRUN {calendar_id} {event['title']} ({event['start']})")
            results.append({
                "source_event_id": event.get("source_event_id"),
                "calendar_key": event["calendar_key"],
                "calendar_id": calendar_id,
                "status": "would_create",
                "title": event["title"],
                "start": event["start"],
            })
            continue
        created_event = client.create_event(calendar_id, build_google_body(event))
        created += 1
        print(f"CREATE {calendar_id} {created_event['summary']} {created_event['id']}")
        results.append({
            "source_event_id": event.get("source_event_id"),
            "calendar_key": event["calendar_key"],
            "calendar_id": calendar_id,
            "status": "created",
            "title": created_event["summary"],
            "start": event["start"],
            "event_id": created_event["id"],
        })
    summary = {"created": created, "skipped": skipped, "dry_run": dry_run, "results": results}
    print(json.dumps(summary, indent=2))
    return summary


def sync_events(config: dict[str, Any], input_path: Path, dry_run: bool) -> int:
    payload = json.loads(input_path.read_text())
    sync_payload(config, payload, dry_run)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="school_sync_config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("authorize")

    sync = sub.add_parser("sync")
    sync.add_argument("--input", required=True)
    sync.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    auth = GoogleCalendarAuth(config)
    if args.command == "authorize":
        auth.authorize()
        return 0
    if args.command == "sync":
        return sync_events(config, Path(args.input), args.dry_run)
    return 1


if __name__ == "__main__":
    sys.exit(main())
