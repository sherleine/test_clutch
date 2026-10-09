"""Offline tests for company database import, deduplication and export."""
import csv
import tempfile
import unittest
from pathlib import Path

from company_database import connect, export_csv, import_csv, status


class CompanyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "test.sqlite3"
        self.input_path = self.root / "companies.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_csv(self, rows):
        fields = [
            "agency_name", "website", "profile_link", "city", "country",
            "hourly_rate_raw", "rating", "review_count",
        ]
        with self.input_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_imports_scraper_output_schema(self):
        self.write_csv([{
            "agency_name": "Example AI",
            "website": "https://www.example.org/about?ref=listing",
            "profile_link": "https://clutch.co/profile/example-ai",
            "city": "Mumbai",
            "country": "India",
            "hourly_rate_raw": "$100 - $149 / hr",
            "rating": "4.9",
            "review_count": "12",
        }])

        self.assertEqual(import_csv(str(self.input_path), self.db_path), 1)
        counts = status(self.db_path)
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["pending"], 1)

        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM companies"
            ).fetchone()

        self.assertEqual(row["company_name"], "Example AI")
        self.assertEqual(row["website"], "https://example.org")
        self.assertEqual(row["location"], "Mumbai, India")
        self.assertEqual(row["hourly_rate"], "$100 - $149 / hr")

    def test_duplicate_profile_is_upserted_not_duplicated(self):
        self.write_csv([
            {
                "agency_name": "Example AI",
                "website": "",
                "profile_link": "https://clutch.co/profile/example-ai",
                "city": "Mumbai",
                "country": "India",
                "hourly_rate_raw": "",
                "rating": "",
                "review_count": "",
            },
            {
                "agency_name": "Example AI Updated",
                "website": "https://example.org",
                "profile_link": "https://clutch.co/profile/example-ai/",
                "city": "Mumbai",
                "country": "India",
                "hourly_rate_raw": "$100-$149",
                "rating": "4.9",
                "review_count": "12",
            },
        ])

        import_csv(str(self.input_path), self.db_path)
        self.assertEqual(status(self.db_path)["total"], 1)

        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM companies"
            ).fetchone()

        self.assertEqual(row["company_name"], "Example AI Updated")
        self.assertEqual(row["website"], "https://example.org")

    def test_exports_master_csv(self):
        self.write_csv([{
            "agency_name": "Example AI",
            "website": "example.org",
            "profile_link": "",
            "city": "",
            "country": "",
            "hourly_rate_raw": "",
            "rating": "",
            "review_count": "",
        }])
        import_csv(str(self.input_path), self.db_path)

        output = self.root / "master.csv"
        self.assertEqual(export_csv(str(output), self.db_path), 1)
        with output.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["company_name"], "Example AI")
        self.assertIn("business_emails", rows[0])


if __name__ == "__main__":
    unittest.main()
