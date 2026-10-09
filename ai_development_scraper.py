"""Scrape Clutch's AI development company directory into CSV and JSONL.

This independent entry point avoids dependencies on scoring.py and the outreach
workbook template used by the legacy tracker. Stop if an anti-bot challenge is
returned; do not attempt to bypass it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from scraper import (
    CloudflareChallengeError,
    DEFAULT_USER_AGENT,
    build_page_url,
    extract_company_rows,
    get_total_pages,
)

BASE_URL = (
    "https://clutch.co/developers/artificial-intelligence"
    "?hourly_rate=150-199&hourly_rate=100-149&hourly_rate=300"
    "&hourly_rate=200-300&hourly_rate=50-99"
)
PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output" / "ai_development"
JSONL_PATH = OUTPUT_DIR / "raw_rows.jsonl"
CSV_PATH = OUTPUT_DIR / "companies.csv"
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.json"
FIELDS = [
    "agency_name", "country", "city", "website", "profile_link",
    "main_services", "secondary_services", "team_size_raw", "hourly_rate_raw",
    "min_project_size_raw", "rating", "review_count", "description",
    "source_url", "page_number",
]


def fetch_page(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    if response.headers.get("Cf-Mitigated", "").lower() == "challenge" or "Just a moment" in response.text[:500]:
        raise CloudflareChallengeError(
            f"Clutch returned an access challenge for {url}. Stopping; use an approved access route."
        )
    response.raise_for_status()
    return response.text


def load_checkpoint() -> int:
    try:
        return int(json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8")).get("last_completed_page", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def save_checkpoint(page: int) -> None:
    CHECKPOINT_PATH.write_text(
        json.dumps({"last_completed_page": page}, indent=2), encoding="utf-8"
    )


def append_jsonl(rows: list[dict[str, Any]]) -> None:
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def export_csv(rows: list[dict[str, Any]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            normalized["main_services"] = "; ".join(normalized.get("main_services") or [])
            normalized["secondary_services"] = "; ".join(normalized.get("secondary_services") or [])
            writer.writerow(normalized)


def load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if JSONL_PATH.exists():
        with JSONL_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        print("Warning: skipping malformed JSONL line.", file=sys.stderr)
    # Deduplicate by profile URL; company name is the fallback.
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = (row.get("profile_link") or row.get("agency_name") or "").strip().casefold()
        if key:
            deduped[key] = row
    return list(deduped.values())


def scrape(max_pages: int | None, min_delay: float, max_delay: float, reset: bool) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if reset:
        for path in (JSONL_PATH, CHECKPOINT_PATH, CSV_PATH):
            path.unlink(missing_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    try:
        first_url = build_page_url(BASE_URL, 1)
        first_html = fetch_page(session, first_url)
    except CloudflareChallengeError as exc:
        raise SystemExit(str(exc)) from exc

    total_pages = get_total_pages(first_html, fallback=1)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)
    # Keep first page HTML so it doesn't need a second request.
    start_page = max(1, load_checkpoint() + 1)
    print(f"Target pages this run: {total_pages}; starting at page {start_page}")
    if start_page > total_pages:
        print("Checkpoint is already at/after the requested page limit.")
        export_csv(load_rows())
        return

    for page in range(start_page, total_pages + 1):
        url = build_page_url(BASE_URL, page)
        try:
            html = first_html if page == 1 else fetch_page(session, url)
        except CloudflareChallengeError as exc:
            save_checkpoint(page - 1)
            raise SystemExit(str(exc)) from exc
        except requests.RequestException as exc:
            save_checkpoint(page - 1)
            raise SystemExit(f"Request failed on page {page}: {exc}") from exc

        rows = extract_company_rows(html, url, page)
        if not rows:
            # Do not silently claim success when page markup may have changed.
            print(f"Warning: page {page} yielded zero company cards. Check markup/access before continuing.")
        append_jsonl(rows)
        save_checkpoint(page)
        print(f"Page {page}/{total_pages}: extracted {len(rows)} cards")

        if page < total_pages:
            time.sleep(min_delay if min_delay == max_delay else min_delay + (max_delay - min_delay) * 0.5)

    rows = load_rows()
    export_csv(rows)
    print(f"Done. Unique companies: {len(rows)}")
    print(f"CSV: {CSV_PATH}")
    print(f"JSONL: {JSONL_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=None, help="Limit page count for a smoke test")
    parser.add_argument("--min-delay", type=float, default=8.0, help="Minimum seconds between requests")
    parser.add_argument("--max-delay", type=float, default=15.0, help="Maximum seconds between requests")
    parser.add_argument("--reset", action="store_true", help="Delete this workflow's checkpoint and outputs first")
    args = parser.parse_args()
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        parser.error("Delays must satisfy 0 <= --min-delay <= --max-delay")
    scrape(args.max_pages, args.min_delay, args.max_delay, args.reset)


if __name__ == "__main__":
    main()
