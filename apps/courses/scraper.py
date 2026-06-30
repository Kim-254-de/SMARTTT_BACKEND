"""
Portal scraper for students.tharaka.ac.ke

Usage:
    from apps.courses.scraper import scrape_student_units
    units = scrape_student_units("TUN/CS/001/2023", "password123")
    # returns list of {"unit_code": "COSC 328", "unit_name": "MOBILE APPLICATIONS DEVELOPMENT"}
    # raises ScraperError on login failure or network issue
    # credentials are NEVER stored — only the extracted unit list is returned
"""
from __future__ import annotations

import time
import requests
from bs4 import BeautifulSoup

PORTAL_URL = "https://students.tharaka.ac.ke/"
UNITS_URL = "https://students.tharaka.ac.ke/pages/SemesterUnitsRegistration"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}


class ScraperError(Exception):
    pass


def _get_aspnet_tokens(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def val(name: str) -> str:
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag else ""

    return {
        "__VIEWSTATE": val("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": val("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": val("__EVENTVALIDATION"),
        "__LASTFOCUS": "",
        "__EVENTTARGET": "ctl00$MainContent$lbtnLogin",
        "__EVENTARGUMENT": "",
    }


def scrape_student_units(portal_username: str, portal_password: str) -> list[dict]:
    """
    Log into the student portal, scrape the registered units table,
    and return a list of unit dicts. Credentials are used in-memory only.

    Raises ScraperError on login failure or scraping error.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Step 1: GET login page to collect ASP.NET tokens ──────────────────────
    try:
        resp = session.get(PORTAL_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Could not reach student portal: {exc}") from exc

    tokens = _get_aspnet_tokens(resp.text)

    # ── Step 2: POST credentials ───────────────────────────────────────────────
    time.sleep(1)  # brief delay — avoid instant bot detection
    payload = {
        **tokens,
        "ctl00$MainContent$txtusername": portal_username,
        "ctl00$MainContent$txtpass": portal_password,
    }
    try:
        resp = session.post(
            PORTAL_URL,
            data=payload,
            headers={"Referer": PORTAL_URL, "Origin": "https://students.tharaka.ac.ke",
                     "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Login request failed: {exc}") from exc

    if "Warning!, login failed" in resp.text:
        raise ScraperError("Invalid portal credentials. Please check your admission number and password.")

    if "Dashboard" not in resp.url and "dashboard" not in resp.text.lower():
        raise ScraperError("Login appeared to succeed but did not reach the dashboard.")

    # ── Step 3: GET the registered units page ─────────────────────────────────
    time.sleep(1)
    try:
        resp = session.get(UNITS_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Could not load units page: {exc}") from exc

    if "login" in resp.url.lower():
        raise ScraperError("Session expired before reaching the units page.")

    # ── Step 4: Parse the REGISTERED UNITS table ──────────────────────────────
    soup = BeautifulSoup(resp.text, "html.parser")
    units = []

    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        header_text = header.get_text(strip=True).upper()
        # Target the "REGISTERED UNITS" table — identified by "UNIT TITLE" in header
        if "UNIT TITLE" not in header_text:
            continue
        for row in table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) >= 2 and cols[0] and len(cols[0]) <= 20:
                units.append({
                    "unit_code": cols[0].strip(),
                    "unit_name": cols[1].strip(),
                })
        break  # we only need the first matching table

    return units
