# Clutch AI Development Company Research Pipeline

This repository has two separate stages:

1. **Company discovery/import:** use a company list obtained through an access method authorized for your intended use. The existing Clutch listing scraper stops when it encounters an access challenge; do not try to bypass that challenge.
2. **Website enrichment:** research permitted public pages on each company's own website and save published business contact details with source URLs.

Target directory filters for the discovery stage:
https://clutch.co/developers/artificial-intelligence?hourly_rate=150-199&hourly_rate=100-149&hourly_rate=300&hourly_rate=200-300&hourly_rate=50-99

## Windows PowerShell setup

```powershell
cd "D:\test clutch\clutch-ai-scraper"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If a virtual environment does not exist yet, create it with python -m venv .venv and activate it first.

## Pipeline files

- ai_development_scraper.py — existing Clutch listing scraper. It stops on an access challenge; use only when the source/access method is authorized.
- company_database.py — imports, deduplicates and stores company records in SQLite.
- website_enrichment.py — processes pending company records, checks robots.txt conservatively, stays on the company's domain, and records published business contact details and source URLs.
- input/companies.example.csv — CSV header template.
- tests/test_company_database.py — offline tests for importing the current scraper's CSV shape, deduplication and export.

Runtime data is written under output/, which is ignored by Git. Do not commit collected company contact data or local database files.

## 1. Prepare a company CSV

Create input/companies.csv using the example template. The importer accepts either company_name or agency_name, and either website or official_website. It also understands fields produced by the existing scraper, such as profile_link, hourly_rate_raw, min_project_size_raw, main_services and secondary_services.

The company name is required. A Clutch profile URL is the preferred deduplication key; the website is the fallback. Rows with neither use the normalized company name.

## 2. Import and inspect the master database

For a company CSV obtained from an authorized source:

```powershell
python company_database.py import-csv input/companies.csv
python company_database.py status
```

To import the existing scraper's CSV, if you already have data collected through an authorized route:

```powershell
python company_database.py import-csv output/ai_development/companies.csv
```

Repeated imports merge records rather than creating duplicate rows. Existing contact enrichment fields and status are preserved.

## 3. Enrich public company websites

Start with a small batch:

```powershell
python website_enrichment.py --limit 5 --delay 2 --max-pages 8
```

Then inspect database progress:

```powershell
python company_database.py status
```

The worker visits the homepage and relevant same-domain links whose text/URL suggests Contact, About, Team, Leadership, Founder or similar pages. It extracts publicly displayed email addresses and phone numbers and saves the source URLs. Leadership results are contextual snippets, not guaranteed verified names; review them before relying on them.

The worker:
- checks robots.txt conservatively and skips sites when access rules cannot be confirmed;
- stops on HTTP 401/403/429 and challenge pages rather than attempting to bypass them;
- stays on the company's domain;
- stores each company's result in SQLite so completed/blocked records are not reprocessed on normal runs.

Only published business contact details are collected. Do not use the tool to collect private or non-public personal information. Confirm that your use of each website and the resulting data complies with its terms and applicable law.

## 4. Export the final CSV

```powershell
python company_database.py export-csv --output output/enriched_companies.csv
```

The export includes directory fields, contact details, enrichment status, and the source URLs used for contact research.

## 5. Run offline tests

```powershell
python -m unittest discover -s tests -v
```

The tests do not access Clutch or any company websites.

## Notes and limitations

- The Clutch listing page currently returns an access challenge to direct Python requests in the tested environment. The listing scraper cannot guarantee complete results until an appropriate access method is available.
- The website enrichment worker uses HTML parsing, not a full JavaScript browser agent. It may miss details rendered only by JavaScript, protected pages, images, or unusual layouts.
- Founder/owner information is collected as nearby text around leadership terms and must be manually verified.
- Pagination selectors and website markup can change.
