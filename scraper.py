"""Fetches Clutch.co directory listing pages and parses raw company fields.

Selectors are based on the supplied project code. Website markup may change;
test against a small sample and respect the site's terms and access controls.
"""
import random
import re
import time
import urllib.parse as urlparse
from typing import List, Optional

import cloudscraper
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
CANADA_PROVINCE_CODES = {"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK", "NT", "NU", "YT"}
UK_REGIONS = {"England", "Scotland", "Wales", "Northern Ireland"}


class CloudflareChallengeError(Exception):
    """Raised when an interactive anti-bot challenge is returned."""


def normalize_country(raw_token: str) -> str:
    token = raw_token.strip()
    if token.upper() in US_STATE_CODES:
        return "USA"
    if token.upper() in CANADA_PROVINCE_CODES:
        return "Canada"
    if token in UK_REGIONS:
        return "UK"
    return token


def normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def build_page_url(base_url: str, page_number: int) -> str:
    if page_number <= 1:
        return base_url
    if re.search(r"[?&]page=\d+", base_url):
        return re.sub(r"([?&]page=)\d+", rf"\g<1>{page_number}", base_url)
    return f"{base_url}{'&' if '?' in base_url else '?'}page={page_number}"


def get_total_pages(html: str, fallback: int = 1) -> int:
    soup = BeautifulSoup(html, "lxml")
    pagination = soup.select_one(".providers-pagination")
    if not pagination:
        return fallback
    numbers = [int(n) for n in re.findall(r"\d+", pagination.get_text(" ")) if n.isdigit()]
    return max(numbers) if numbers else fallback


def extract_website(node) -> str:
    link = node.select_one("a.website-link__item")
    if not link or not link.get("href"):
        return ""
    href = link["href"]
    query = urlparse.parse_qs(urlparse.urlparse(href).query)
    target = query.get("u", [""])[0]
    if not target or "ppc.clutch.co" in target:
        return ""
    parsed = urlparse.urlparse(target)
    clean_query = urlparse.parse_qs(parsed.query)
    for key in ("utm_source", "utm_medium", "utm_campaign"):
        clean_query.pop(key, None)
    return urlparse.urlunparse(parsed._replace(query=urlparse.urlencode(clean_query, doseq=True))).rstrip("?")


def extract_services(node, css_class: str) -> List[str]:
    block = node.select_one(f".provider__services--{css_class}")
    if not block:
        return []
    items = []
    for li in block.select(".provider__services-list-item"):
        text = normalize_text(li.get_text(" "))
        text = re.sub(r"^\d+%\s*", "", text)
        text = re.sub(r"\s*\+\d+$", "", text)
        if text:
            items.append(text)
    return items


def extract_company_rows(html: str, source_url: str, page_number: int) -> List[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = [
        card for card in soup.select(".provider-list-item")
        if not card.select_one(".provider--lm-provider")
    ]
    rows = []
    for card in cards:
        name_node = card.select_one(".provider__title")
        name = normalize_text(name_node.get_text(" ")) if name_node else ""
        if not name:
            continue
        profile_node = card.select_one("a.directory_profile")
        profile_href = profile_node.get("href", "").strip() if profile_node else ""
        if profile_href.startswith("/"):
            profile_href = "https://clutch.co" + profile_href.split("#")[0]

        location_node = card.select_one(".location")
        location_text = normalize_text(location_node.get_text(" ")) if location_node else ""
        if "," in location_text:
            city, _, country = location_text.rpartition(",")
            city, country = city.strip(), normalize_country(country)
        else:
            city, country = "", normalize_country(location_text)

        rating_node = card.select_one(".sg-rating__number")
        reviews_node = card.select_one(".sg-rating__reviews")
        review_match = re.search(r"\d+", reviews_node.get_text(" ")) if reviews_node else None
        rows.append({
            "agency_name": name,
            "country": country,
            "city": city,
            "website": extract_website(card),
            "profile_link": profile_href,
            "main_services": extract_services(card, "provided"),
            "secondary_services": extract_services(card, "focus-areas"),
            "team_size_raw": normalize_text(card.select_one(".employees-count").get_text(" ")) if card.select_one(".employees-count") else "",
            "hourly_rate_raw": normalize_text(card.select_one(".hourly-rate").get_text(" ")) if card.select_one(".hourly-rate") else "",
            "min_project_size_raw": normalize_text(card.select_one(".min-project-size").get_text(" ")) if card.select_one(".min-project-size") else "",
            "rating": normalize_text(rating_node.get_text(" ")) if rating_node else "",
            "review_count": int(review_match.group(0)) if review_match else None,
            "description": normalize_text(card.select_one(".provider__description").get_text(" ")) if card.select_one(".provider__description") else "",
            "source_url": source_url,
            "page_number": page_number,
        })
    return rows


class Scraper:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, min_delay: float = 8.0, max_delay: float = 15.0):
        self.session = cloudscraper.create_scraper(delay=5)
        self.session.headers.update({"User-Agent": user_agent})
        self.min_delay = min_delay
        self.max_delay = max_delay

    def fetch_page(self, url: str) -> str:
        response = self.session.get(url, timeout=30)
        if response.headers.get("Cf-Mitigated", "").lower() == "challenge" or "Just a moment" in response.text[:500]:
            raise CloudflareChallengeError(
                f"An anti-bot challenge was returned for {url}. Stop requests and use an approved access method."
            )
        response.raise_for_status()
        return response.text

    def polite_wait(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def scrape_page(self, base_url: str, page_number: int) -> List[dict]:
        page_url = build_page_url(base_url, page_number)
        return extract_company_rows(self.fetch_page(page_url), page_url, page_number)
