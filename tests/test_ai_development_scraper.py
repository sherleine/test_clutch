"""Basic offline tests for the AI directory scraper."""
import unittest

from scraper import build_page_url, extract_company_rows


class ScraperTests(unittest.TestCase):
    def test_page_url_adds_page_parameter(self):
        self.assertEqual(
            build_page_url("https://example.test/list?x=1", 2),
            "https://example.test/list?x=1&page=2",
        )

    def test_parser_extracts_provider_card(self):
        html = """
        <div class="provider-list-item">
          <h3 class="provider__title">Example AI</h3>
          <a class="directory_profile" href="/profile/example-ai"></a>
          <div class="location">Mumbai, India</div>
          <div class="hourly-rate">$100 - $149 / hr</div>
          <div class="employees-count">10 - 49</div>
          <div class="min-project-size">$10,000+</div>
          <div class="sg-rating__number">4.9</div>
          <div class="sg-rating__reviews">12 reviews</div>
          <div class="provider__services--provided">
            <span class="provider__services-list-item">50% AI Development</span>
          </div>
          <p class="provider__description">AI applications and software.</p>
        </div>
        """
        rows = extract_company_rows(
            html,
            "https://clutch.co/developers/artificial-intelligence?page=1",
            1,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agency_name"], "Example AI")
        self.assertEqual(rows[0]["profile_link"], "https://clutch.co/profile/example-ai")
        self.assertEqual(rows[0]["country"], "India")
        self.assertEqual(rows[0]["review_count"], 12)


if __name__ == "__main__":
    unittest.main()
