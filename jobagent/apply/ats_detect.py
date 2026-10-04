"""Identify which Applicant Tracking System (ATS) hosts a posting.

Detection is URL-first (cheap, reliable for the big hosted boards) with an
optional DOM pass for career-page *embeds* (e.g. a company site that iframes a
Greenhouse form). Returns one of the keys in :data:`KNOWN` or ``"unknown"``.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# name -> (url host/path regexes, embedded-in-page HTML regexes)
_SIGNALS: dict[str, tuple[list[str], list[str]]] = {
    "greenhouse": (
        [r"greenhouse\.io", r"\bgrnh\.se\b", r"boards\.greenhouse", r"job-boards\.greenhouse"],
        [r"greenhouse\.io/embed", r"id=['\"]grnhse_app['\"]", r"job_application\[", r"boards\.greenhouse\.io"],
    ),
    "lever": (
        [r"lever\.co", r"jobs\.lever\.co"],
        [r"jobs\.lever\.co", r"postings\.lever\.co", r"data-qa=['\"]application-form['\"]"],
    ),
    "ashby": (
        [r"ashbyhq\.com", r"jobs\.ashbyhq\.com"],
        [r"ashbyhq", r"_ashby_application"],
    ),
    "workday": (
        [r"myworkdayjobs\.com", r"\.workday\.com"],
        [r"myworkdayjobs\.com", r"data-automation-id="],
    ),
}

KNOWN = tuple(_SIGNALS.keys())


def _search_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def detect_ats(url: str, html: str | None = None) -> str:
    """Return the ATS key for *url* (optionally refined by page *html*).

    URL host+path wins; if that is inconclusive and *html* is given, fall back to
    embed signals in the markup. ``"unknown"`` when nothing matches.
    """
    parsed = urlparse(url if "://" in url else f"//{url}")
    hostpath = f"{parsed.netloc}{parsed.path}"
    for name, (url_pats, _) in _SIGNALS.items():
        if _search_any(url_pats, hostpath):
            return name
    if html:
        for name, (_, html_pats) in _SIGNALS.items():
            if _search_any(html_pats, html):
                return name
    return "unknown"
