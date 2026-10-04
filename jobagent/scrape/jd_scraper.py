"""Turn a job-posting URL into a structured :class:`JobPosting`.

Cheapest-first cascade:

1. Hosted ATS boards (Greenhouse/Lever/Ashby) -> their public JSON API. Exact, no LLM.
2. Any page embedding a schema.org ``JobPosting`` (JSON-LD) -> parsed directly, no LLM.
3. Otherwise static fetch (httpx + BeautifulSoup), Playwright render if the page is
   JS-heavy, then a small Claude pass extracts the fields.

Closed postings raise :class:`~.ats_api.PostingClosed` so we never tailor for a dead role.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..llm import complete_json
from ..apply.ats_detect import detect_ats
from ..models import JobPosting
from .ats_api import PostingClosed, fetch_posting, jsonld_posting, looks_closed

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_MIN_TEXT = 600  # below this we assume the page needs JS rendering


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    # collapse blank runs
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    return "\n".join(lines)


def _fetch_static(url: str) -> tuple[str, str]:
    """Return (raw html, final url)."""
    resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text, str(resp.url)


def _fetch_rendered(url: str) -> str:
    """Render with Playwright. Imported lazily so Module A works without a browser
    install when pages are static."""
    from playwright.sync_api import sync_playwright

    from ..browser import launch_kwargs

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs(headless=True))
        page = browser.new_page(user_agent=_HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle", timeout=45000)
        html = page.content()
        browser.close()
    return html


def scrape(url: str) -> JobPosting:
    # Tier 1: ATS JSON API (raises PostingClosed for dead roles).
    posting = fetch_posting(url)
    if posting:
        return posting

    html, final_url = "", url
    try:
        html, final_url = _fetch_static(url)
    except Exception:
        pass
    if "error=true" in final_url:  # Greenhouse redirects closed jobs to ?error=true
        raise PostingClosed(f"Posting closed (redirected to {final_url})")

    # Tier 2: JSON-LD JobPosting embedded for Google Jobs.
    posting = jsonld_posting(url, html)
    if posting:
        posting.ats_type = detect_ats(url, html)
        return posting

    # Tier 3: rendered text + LLM extraction.
    text = _visible_text(html) if html else ""
    if len(text) < _MIN_TEXT:
        try:
            html = _fetch_rendered(url)
            text = _visible_text(html)
            posting = jsonld_posting(url, html)
            if posting:
                posting.ats_type = detect_ats(url, html)
                return posting
        except Exception as exc:  # keep whatever static text we had
            if not text:
                raise RuntimeError(f"Could not fetch posting: {exc}") from exc
    if looks_closed(text[:3000]):
        raise PostingClosed("Posting page says the role is closed")

    text = text[:16000]  # keep the prompt bounded
    domain = urlparse(url).netloc

    data = complete_json(
        f"Extract structured fields from this job posting. Return ONLY JSON with keys "
        f'"company", "title", "location", "description". "description" should be the '
        f"full responsibilities + requirements text, lightly cleaned.\n\n"
        f"URL host: {domain}\n\nPAGE TEXT:\n{text}",
        model=settings.model_parse,
        system="You extract job-posting fields verbatim. Do not invent details.",
        max_tokens=3000,
    )
    return JobPosting(
        url=url,
        company=data.get("company", "").strip(),
        title=data.get("title", "").strip(),
        location=data.get("location", "").strip(),
        description=data.get("description", "").strip() or text,
        ats_type=detect_ats(url, html),
    )
