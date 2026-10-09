"""Run the Clutch AI-consulting listing scrape and export a workbook.

Examples:
  python run.py --max-pages 1
  python run.py
  python run.py --finalize-only
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

from scraper import Scraper, build_page_url, get_total_pages, CloudflareChallengeError
from scoring import classify
from excel_writer import write_workbook

BASE_URL = (
    "https://clutch.co/consulting/ai"
    "?hourly_rate=300&hourly_rate=100-149&hourly_rate=200-300"
    "&hourly_rate=50-99&hourly_rate=150-199"
    "&related_services=field_pp_sl_artificial_intellige"
)
PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
RAW_ROWS_PATH = OUTPUT_DIR / "raw_rows.jsonl"
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.json"
TEMPLATE_PATH = PROJECT_DIR / "eDOT_Clutch_Outreach_Tracker_v3.xlsx"
FINAL_OUTPUT_PATH = OUTPUT_DIR / "eDOT_Clutch_Outreach_Tracker_AI_Consulting_Scraped.xlsx"
DOTNET_ROWS_PATH = OUTPUT_DIR / "dotnet" / "raw_rows.jsonl"


def load_dotnet_company_names() -> set:
    if not DOTNET_ROWS_PATH.exists():
        return set()
    names = set()
    with DOTNET_ROWS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                name = json.loads(line.strip()).get("agency_name", "").strip()
                if name:
                    names.add(name)
            except (json.JSONDecodeError, AttributeError):
                continue
    return names


def load_checkpoint() -> int:
    if not CHECKPOINT_PATH.exists():
        return 0
    try:
        return int(json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8")).get("last_completed_page", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def save_checkpoint(page: int) -> None:
    CHECKPOINT_PATH.write_text(json.dumps({"last_completed_page": page}), encoding="utf-8")


def append_raw_rows(rows: list) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with RAW_ROWS_PATH.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_raw_rows() -> list:
    if not RAW_ROWS_PATH.exists():
        return []
    rows = []
    with RAW_ROWS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def scrape(max_pages: int = None, max_retries: int = 3) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scraper = Scraper()
    try:
        first_page_html = scraper.fetch_page(build_page_url(BASE_URL, 1))
    except CloudflareChallengeError as exc:
        print(f"Access challenge: {exc}\nStop requests and use an approved access route.")
        sys.exit(1)

    total_pages = get_total_pages(first_page_html)
    if max_pages:
        total_pages = min(total_pages, max_pages)
    print(f"Target: {total_pages} pages")
    start_page = load_checkpoint() + 1
    if start_page > 1:
        print(f"Resuming from page {start_page}")

    for page_number in range(start_page, total_pages + 1):
        for attempt in range(1, max_retries + 1):
            try:
                if page_number == 1:
                    from scraper import extract_company_rows
                    rows = extract_company_rows(first_page_html, build_page_url(BASE_URL, 1), 1)
                else:
                    rows = scraper.scrape_page(BASE_URL, page_number)
                break
            except CloudflareChallengeError as exc:
                save_checkpoint(page_number - 1)
                print(f"Access challenge at page {page_number}: {exc}")
                sys.exit(1)
            except requests.RequestException as exc:
                print(f"Page {page_number}, attempt {attempt}/{max_retries} failed: {exc}")
                if attempt == max_retries:
                    save_checkpoint(page_number - 1)
                    sys.exit(1)
                time.sleep(5 * attempt)

        append_raw_rows(rows)
        save_checkpoint(page_number)
        print(f"Page {page_number}/{total_pages}: {len(rows)} companies")
        scraper.polite_wait()
    print("Scrape complete.")


def dedupe_rows(raw_rows: list) -> list:
    seen, deduped = set(), []
    for row in raw_rows:
        key = row.get("profile_link") or row.get("agency_name")
        if not key or key not in seen:
            if key:
                seen.add(key)
            deduped.append(row)
    return deduped


def finalize() -> None:
    raw_rows = dedupe_rows(load_raw_rows())
    if not raw_rows:
        raise SystemExit("No raw rows found. Run the scrape step first.")
    print(f"Classifying {len(raw_rows)} scraped companies...")
    classified = [(row, classify(row)) for row in raw_rows]
    dotnet_names = load_dotnet_company_names()
    cross_refs = {"Also in .NET Tracker?": dotnet_names} if dotnet_names else None
    write_workbook(classified, str(TEMPLATE_PATH), str(FINAL_OUTPUT_PATH), cross_refs=cross_refs)
    tracker_count = sum(1 for _, result in classified if result.get("scope") == "tracker")
    print(f"Saved {FINAL_OUTPUT_PATH} — {tracker_count} in Agency Tracker, {len(classified) - tracker_count} out of scope")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=None, help="Limit page count for a small test run")
    parser.add_argument("--finalize-only", action="store_true", help="Rebuild workbook using saved raw rows")
    args = parser.parse_args()
    if not args.finalize_only:
        scrape(max_pages=args.max_pages)
    finalize()


if __name__ == "__main__":
    main()
