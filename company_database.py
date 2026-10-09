"""SQLite master database for company discovery and website enrichment.

Accepts the CSV produced by ai_development_scraper.py as well as normalized
company CSV files. The database is local runtime output and should not be
committed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "output" / "company_database.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_key TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    website TEXT,
    clutch_profile_url TEXT,
    location TEXT,
    hourly_rate TEXT,
    rating TEXT,
    review_count TEXT,
    main_services TEXT,
    secondary_services TEXT,
    team_size TEXT,
    min_project_size TEXT,
    description TEXT,
    listing_source_url TEXT,
    listing_page_number TEXT,
    business_emails TEXT NOT NULL DEFAULT '',
    business_phones TEXT NOT NULL DEFAULT '',
    founder_owner_contacts TEXT NOT NULL DEFAULT '',
    contact_page_urls TEXT NOT NULL DEFAULT '',
    contact_source_urls TEXT NOT NULL DEFAULT '',
    enrichment_status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_companies_enrichment_status
ON companies(enrichment_status);
"""


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(clean(item) for item in value if clean(item))
    return str(value).strip()


def normalize_website(value: object) -> str:
    raw = clean(value)
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    # Keep only the origin as the stable company website identifier.
    return f"{parsed.scheme.lower()}://{host}".rstrip("/")


def company_key(row: dict) -> str:
    profile = clean(row.get("clutch_profile_url") or row.get("profile_link"))
    if profile:
        return "profile:" + profile.rstrip("/").casefold()

    website = normalize_website(
        row.get("website") or row.get("official_website")
    )
    if website:
        return "website:" + website.casefold()

    name = clean(row.get("company_name") or row.get("agency_name")).casefold()
    if not name:
        raise ValueError("Each row must have company_name or agency_name.")
    return "name:" + name


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def normalize_row(row: dict) -> dict:
    name = clean(row.get("company_name") or row.get("agency_name"))
    if not name:
        raise ValueError("Company name is empty.")

    city = clean(row.get("city"))
    country = clean(row.get("country"))
    location = clean(row.get("location")) or ", ".join(
        part for part in (city, country) if part
    )

    return {
        "company_key": company_key(row),
        "company_name": name,
        "website": normalize_website(
            row.get("website") or row.get("official_website")
        ),
        "clutch_profile_url": clean(
            row.get("clutch_profile_url") or row.get("profile_link")
        ),
        "location": location,
        "hourly_rate": clean(row.get("hourly_rate") or row.get("hourly_rate_raw")),
        "rating": clean(row.get("rating")),
        "review_count": clean(row.get("review_count")),
        "main_services": clean(row.get("main_services")),
        "secondary_services": clean(row.get("secondary_services")),
        "team_size": clean(row.get("team_size") or row.get("team_size_raw")),
        "min_project_size": clean(
            row.get("min_project_size") or row.get("min_project_size_raw")
        ),
        "description": clean(row.get("description")),
        "listing_source_url": clean(row.get("source_url")),
        "listing_page_number": clean(row.get("page_number")),
    }


def import_csv(csv_path: str, db_path: Path | str = DB_PATH) -> int:
    imported = 0
    now = datetime.now(timezone.utc).isoformat()

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not (
            {"company_name", "agency_name"} & set(reader.fieldnames)
        ):
            raise ValueError("CSV must contain company_name or agency_name.")

        with connect(db_path) as connection:
            for raw in reader:
                if not clean(raw.get("company_name") or raw.get("agency_name")):
                    continue
                row = normalize_row(raw)
                fields = list(row)
                values = [row[field] for field in fields]
                placeholders = ", ".join("?" for _ in fields)
                updates = ", ".join(
                    f"{field}=CASE WHEN excluded.{field} != '' "
                    f"THEN excluded.{field} ELSE companies.{field} END"
                    for field in fields
                    if field != "company_key"
                )
                connection.execute(
                    f"""
                    INSERT INTO companies ({", ".join(fields)}, created_at, updated_at)
                    VALUES ({placeholders}, ?, ?)
                    ON CONFLICT(company_key) DO UPDATE SET
                    {updates},
                    updated_at=excluded.updated_at
                    """,
                    (*values, now, now),
                )
                imported += 1

    return imported


def status(db_path: Path | str = DB_PATH) -> dict[str, int]:
    with connect(db_path) as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM companies"
        ).fetchone()[0]
        counts = {
            row["enrichment_status"]: row["count"]
            for row in connection.execute(
                "SELECT enrichment_status, COUNT(*) AS count "
                "FROM companies GROUP BY enrichment_status"
            )
        }
    return {"total": total, **counts}


def export_csv(output_path: str, db_path: Path | str = DB_PATH) -> int:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM companies ORDER BY company_name"
        ).fetchall()

    fields = list(rows[0].keys()) if rows else [
        "company_name", "website", "clutch_profile_url", "location",
        "hourly_rate", "rating", "review_count", "business_emails",
        "business_phones", "founder_owner_contacts", "contact_page_urls",
        "contact_source_urls", "enrichment_status",
    ]
    with target.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    importer = commands.add_parser("import-csv", help="Import/merge a company CSV")
    importer.add_argument("csv_path")
    importer.add_argument("--db", default=str(DB_PATH))

    status_parser = commands.add_parser("status", help="Show database progress")
    status_parser.add_argument("--db", default=str(DB_PATH))

    exporter = commands.add_parser("export-csv", help="Export all company records")
    exporter.add_argument("--output", default="output/companies_master.csv")
    exporter.add_argument("--db", default=str(DB_PATH))

    args = parser.parse_args()
    if args.command == "import-csv":
        print(f"Imported/merged {import_csv(args.csv_path, args.db)} rows.")
    elif args.command == "status":
        for label, count in status(args.db).items():
            print(f"{label}: {count}")
    elif args.command == "export-csv":
        print(f"Exported {export_csv(args.output, args.db)} rows to {args.output}")


if __name__ == "__main__":
    main()
