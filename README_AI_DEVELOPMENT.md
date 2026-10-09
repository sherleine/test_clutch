# Clutch AI Development Company Scraper

Scrapes public company cards from Clutch's Artificial Intelligence Development directory and exports rows to CSV/JSONL. Existing outreach-tracker files are preserved; this is an independent workflow.

Target URL:
`https://clutch.co/developers/artificial-intelligence?hourly_rate=150-199&hourly_rate=100-149&hourly_rate=300&hourly_rate=200-300&hourly_rate=50-99`

## Windows PowerShell setup

```powershell
cd D:\clutch\test_clutch
git pull
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you already have a working `.venv`, activate it and run `pip install -r requirements.txt`.

## Run a small test first

```powershell
python ai_development_scraper.py --max-pages 1
```

Output is written to `output/ai_development/`:
- `companies.csv`
- `raw_rows.jsonl`
- `checkpoint.json`

Then run the full directory scrape after checking the test output and confirming your use follows Clutch's terms/access rules:

```powershell
python ai_development_scraper.py
```

The scraper resumes from the last completed page. To intentionally start a fresh collection, run with `--reset`. Default delay is randomized between 8 and 15 seconds. If an access challenge is returned, the scraper stops instead of trying to bypass it.

## Fields

Company name, location/country, website (when exposed in the listing), profile URL, main services, focus areas, team size, hourly rate, minimum project size, rating, review count, description, source URL, and page number.

## Notes

- Selectors may need adjustment if Clutch changes its markup.
- Pagination is detected when current markup exposes it; if not, the scraper defaults to one page to avoid assuming an inaccurate total.
- This project only reads listing pages; it does not harvest private contact details.
