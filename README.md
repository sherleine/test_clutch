# Clutch Agency Scraper

Python project seeded from the three source files provided in the email: `scraper.py`, `run.py`, and `excel_writer.py`.

The scraper is configured for Clutch's AI-consulting directory and exports company listing data into an Excel outreach tracker. The source code imports a separate `scoring.py` module and expects an optional workbook template named `eDOT_Clutch_Outreach_Tracker_v3.xlsx`; these were not included in the supplied ZIP, so the end-to-end workflow is not yet complete.

## Fields collected

Agency name, country, city, website, Clutch profile, main and secondary services, team size, hourly rate, minimum project size, rating, review count, description, source URL, and page number.

## Setup (Windows PowerShell)

```powershell
cd D:\clutch\test_clutch
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Current blockers / files still needed

1. `scoring.py` — provides `classify(row)`, which assigns scope, qualification score, priority, and supporting explanations.
2. `eDOT_Clutch_Outreach_Tracker_v3.xlsx` — optional template used to copy the Scoring Guide sheet into the output workbook.
3. The existing `.NET` scrape output is optional and only used for the cross-reference column.

## Running

Once `scoring.py` is supplied, start with a small test:

```powershell
python run.py --max-pages 1
```

After verifying extracted data and ensuring access is permitted, run without a page limit:

```powershell
python run.py
```

To regenerate the workbook from already saved rows:

```powershell
python run.py --finalize-only
```

Raw rows and checkpoints are written under `output/`. Do not commit scrape output or private workbook data to the repository.

## Access and responsible use

Follow Clutch's applicable terms and access rules. Use conservative request rates. If an access challenge is returned, stop the run rather than attempting to circumvent the challenge; use an approved data access method.
