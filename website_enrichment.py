"""Enrich company records in SQLite from permitted public company websites.

This worker does not fetch Clutch. It processes companies already stored in
company_database.py, checks robots.txt conservatively, stays on each company's
domain, and stops when a site restricts access or presents a challenge.
"""
from __future__ import annotations

import argparse
import re
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from company_database import DB_PATH, connect

USER_AGENT = "CompanyResearchBot/1.0 (+https://github.com/sherleine/test_clutch)"
EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s().-]*)?"
    r"(?:\(?\d{2,5}\)?[\s().-]*)?\d{3,5}[\s().-]*\d{3,5}(?!\w)"
)
LEADERSHIP_RE = re.compile(
    r"\b(founder|co-founder|cofounder|owner|CEO|chief executive officer|"
    r"managing director|president|leadership|our team)\b", re.IGNORECASE
)
PAGE_TERMS = (
    "contact", "about", "team", "leadership", "founder", "management",
    "company", "people", "our-story",
)
CHALLENGE_MARKERS = (
    "just a moment...", "verify you are human", "checking your browser",
    "access denied",
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return urldefrag(value)[0].rstrip("/")


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_domain(url: str, root: str) -> bool:
    host, root_host = host_of(url), host_of(root)
    return bool(host and root_host and (
        host == root_host or host.endswith("." + root_host)
    ))


class WebsiteEnricher:
    def __init__(self, delay: float = 2.0, max_pages: int = 8):
        self.delay = delay
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        })
        self.robots_cache: dict[str, RobotFileParser | None] = {}

    def robots_parser(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = origin + "/robots.txt"

        if robots_url not in self.robots_cache:
            try:
                response = self.session.get(robots_url, timeout=15)
                parser = RobotFileParser()
                if response.status_code == 404:
                    parser.parse([])
                elif response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    self.robots_cache[robots_url] = None
                    return None
                self.robots_cache[robots_url] = parser
            except requests.RequestException:
                self.robots_cache[robots_url] = None
                return None

        return self.robots_cache[robots_url]

    def fetch(self, url: str) -> tuple[BeautifulSoup | None, str]:
        parser = self.robots_parser(url)
        if parser is None or not parser.can_fetch(USER_AGENT, url):
            return None, "blocked_by_robots_or_rules_unavailable"

        try:
            time.sleep(self.delay)
            response = self.session.get(
                url, timeout=20, allow_redirects=True
            )
            if response.status_code in (401, 403, 429):
                return None, f"access_restricted_{response.status_code}"
            response.raise_for_status()

            if not same_domain(response.url, url):
                return None, "redirected_off_domain"

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type:
                return None, "not_html"

            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            sample = (title + " " + soup.get_text(" ", strip=True)[:1200]).lower()
            if any(marker in sample for marker in CHALLENGE_MARKERS):
                return None, "access_challenge"
            return soup, "ok"
        except requests.RequestException as exc:
            return None, f"request_error:{type(exc).__name__}"

    def enrich(self, company: dict) -> dict:
        website = normalize_url(company.get("website") or "")
        result = {
            "business_emails": set(),
            "business_phones": set(),
            "founder_owner_contacts": set(),
            "contact_page_urls": set(),
            "contact_source_urls": set(),
            "status": "completed",
            "last_error": "",
        }

        if not website:
            result["status"] = "not_found"
            result["last_error"] = "missing_website"
            return result

        queue = deque([website])
        visited: set[str] = set()
        blocked_statuses = {
            "access_challenge", "access_restricted_401",
            "access_restricted_403", "access_restricted_429",
            "blocked_by_robots_or_rules_unavailable",
        }

        while queue and len(visited) < self.max_pages:
            url = queue.popleft().rstrip("/")
            if url in visited:
                continue
            visited.add(url)

            soup, fetch_status = self.fetch(url)
            if soup is None:
                if fetch_status in blocked_statuses:
                    result["status"] = "blocked"
                    result["last_error"] = fetch_status
                    break
                continue

            result["contact_source_urls"].add(url)
            url_or_text = (url + " " + soup.get_text(" ", strip=True)).lower()
            if any(term in url.lower() for term in PAGE_TERMS):
                result["contact_page_urls"].add(url)

            for tag in soup.select('a[href^="mailto:"]'):
                address = tag.get("href", "").split(":", 1)[-1].split("?", 1)[0].strip()
                if EMAIL_RE.fullmatch(address):
                    result["business_emails"].add(address.lower())

            for tag in soup.select('a[href^="tel:"]'):
                phone = clean(tag.get("href", "").split(":", 1)[-1])
                if phone:
                    result["business_phones"].add(phone)

            text = soup.get_text("\n", strip=True)
            result["business_emails"].update(
                address.lower() for address in EMAIL_RE.findall(text)
            )
            for match in PHONE_RE.findall(text):
                phone = clean(match)
                digits = re.sub(r"\D", "", phone)
                if 7 <= len(digits) <= 15:
                    result["business_phones"].add(phone)

            # Save source context around leadership titles; verify names manually.
            lines = [clean(line) for line in text.splitlines() if clean(line)]
            for index, line in enumerate(lines):
                if LEADERSHIP_RE.search(line):
                    context = " ".join(lines[max(0, index - 1):index + 2])
                    if len(context) <= 300:
                        result["founder_owner_contacts"].add(context)

            for tag in soup.select("a[href]"):
                href = (tag.get("href") or "").strip()
                if not href or href.startswith(
                    ("mailto:", "tel:", "javascript:", "#")
                ):
                    continue
                target = normalize_url(urljoin(url, href))
                if not target or not same_domain(target, website):
                    continue
                label = clean(tag.get_text(" ", strip=True) + " " + href).lower()
                if any(term in label for term in PAGE_TERMS):
                    if target not in visited and target not in queue:
                        queue.append(target)

        if result["status"] == "completed" and not (
            result["business_emails"] or result["business_phones"]
            or result["founder_owner_contacts"]
        ):
            result["status"] = "not_found"

        return result


def process_pending(
    db_path: str = str(DB_PATH),
    limit: int | None = None,
    delay: float = 2.0,
    max_pages: int = 8,
) -> None:
    if delay < 0 or max_pages < 1 or (limit is not None and limit < 1):
        raise ValueError("delay must be >= 0; max_pages and limit must be positive")

    with connect(db_path) as connection:
        query = (
            "SELECT * FROM companies WHERE enrichment_status='pending' "
            "ORDER BY id"
        )
        params: tuple = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        companies = [dict(row) for row in connection.execute(query, params)]

    enricher = WebsiteEnricher(delay=delay, max_pages=max_pages)
    total = len(companies)
    for index, company in enumerate(companies, start=1):
        print(f"[{index}/{total}] {company['company_name']}")
        try:
            result = enricher.enrich(company)
        except Exception as exc:
            result = {
                "business_emails": set(), "business_phones": set(),
                "founder_owner_contacts": set(), "contact_page_urls": set(),
                "contact_source_urls": set(), "status": "error",
                "last_error": type(exc).__name__,
            }

        now = datetime.now(timezone.utc).isoformat()
        with connect(db_path) as connection:
            connection.execute(
                """
                UPDATE companies SET
                    business_emails=?, business_phones=?,
                    founder_owner_contacts=?, contact_page_urls=?,
                    contact_source_urls=?, enrichment_status=?,
                    last_error=?, updated_at=?
                WHERE id=?
                """,
                (
                    "; ".join(sorted(result["business_emails"])),
                    "; ".join(sorted(result["business_phones"])),
                    "; ".join(sorted(result["founder_owner_contacts"])),
                    "; ".join(sorted(result["contact_page_urls"])),
                    "; ".join(sorted(result["contact_source_urls"])),
                    result["status"], result["last_error"], now, company["id"],
                ),
            )
        print(f"  status={result['status']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-pages", type=int, default=8)
    args = parser.parse_args()
    try:
        process_pending(args.db, args.limit, args.delay, args.max_pages)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
