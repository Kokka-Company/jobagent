"""Structured job data straight from ATS public JSON APIs and JSON-LD — no LLM.

Greenhouse, Lever and Ashby publish every company's open roles through public,
unauthenticated board APIs. When a posting URL belongs to one of them we read the
canonical JSON (exact title, location, full description, posted date, comp) instead
of scraping HTML and asking a model to clean it. :func:`list_board` powers
discovery; :func:`fetch_posting` powers ``tailor``/``evaluate`` for a single URL.

For any other site, :func:`jsonld_posting` reads the schema.org ``JobPosting`` that
most career pages embed for Google Jobs. All three tiers return ``None`` when they
don't apply, so callers fall through to the HTML + LLM path.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from ..models import JobPosting

_TIMEOUT = 20
_HEADERS = {"User-Agent": "jobagent/0.1 (personal job-search tool)"}


class PostingClosed(RuntimeError):
    """The posting no longer exists (404 on the ATS API / closed-page markers)."""


# Phrases career pages show once a role is filled or pulled.
CLOSED_MARKERS = (
    "no longer accepting applications", "this job is no longer available",
    "position has been filled", "job you are looking for is no longer",
    "this posting has closed", "job has expired", "no longer open",
    "page you are looking for doesn't exist", "job not found",
)


def looks_closed(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in CLOSED_MARKERS)


def html_to_text(raw: str) -> str:
    """ATS descriptions are HTML (Greenhouse double-escapes it). Return clean text."""
    if not raw:
        return ""
    soup = BeautifulSoup(htmllib.unescape(raw), "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("• ")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _get(url: str, **kw) -> httpx.Response:
    return httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True, **kw)


# --------------------------------------------------------------------------- #
# URL -> (ats, board slug, job id)
# --------------------------------------------------------------------------- #
def parse_ats_url(url: str) -> Optional[tuple[str, str, str]]:
    """Recognize hosted-board posting URLs. Returns (ats, board, job_id) or None."""
    u = urlparse(url if "://" in url else f"https://{url}")
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if "greenhouse.io" in host:
        q = parse_qs(u.query)
        if len(parts) >= 3 and parts[1] == "jobs":
            return "greenhouse", parts[0], parts[2]
        if "for" in q and "token" in q:  # embed: boards.greenhouse.io/embed/job_app?for=x&token=123
            return "greenhouse", q["for"][0], q["token"][0]
    if "lever.co" in host and len(parts) >= 2:
        return ("lever-eu" if ".eu." in host else "lever"), parts[0], parts[1]
    if "ashbyhq.com" in host and len(parts) >= 2:
        return "ashby", parts[0], parts[1]
    return None


# --------------------------------------------------------------------------- #
# Per-ATS normalizers
# --------------------------------------------------------------------------- #
def _gh_board_name(board: str) -> str:
    try:
        return _get(f"https://boards-api.greenhouse.io/v1/boards/{board}").json().get("name", "")
    except Exception:
        return ""


def _from_greenhouse(j: dict, board: str, company: str = "") -> JobPosting:
    return JobPosting(
        url=j.get("absolute_url") or f"https://job-boards.greenhouse.io/{board}/jobs/{j.get('id')}",
        company=j.get("company_name") or company or board,
        title=(j.get("title") or "").strip(),
        location=((j.get("location") or {}).get("name") or "").strip(),
        description=html_to_text(j.get("content", "")),
        ats_type="greenhouse",
        posted_at=(j.get("first_published") or j.get("updated_at") or "")[:10],
        external_id=str(j.get("id", "")),
    )


def _from_lever(j: dict, board: str) -> JobPosting:
    cat = j.get("categories") or {}
    parts = [j.get("descriptionPlain") or html_to_text(j.get("description", ""))]
    for lst in j.get("lists") or []:
        parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}")
    parts.append(j.get("additionalPlain") or "")
    created = j.get("createdAt")
    sal = j.get("salaryRange") or {}
    return JobPosting(
        url=j.get("hostedUrl") or "",
        company=board,
        title=(j.get("text") or "").strip(),
        location=(cat.get("location") or "").strip(),
        description="\n\n".join(p for p in parts if p).strip(),
        ats_type="lever",
        posted_at=_epoch_ms_to_date(created) if created else "",
        compensation=(f"{sal.get('currency', '')} {sal.get('min', '')}–{sal.get('max', '')}"
                      f" {sal.get('interval', '')}".strip() if sal else ""),
        workplace=(j.get("workplaceType") or "").lower(),
        external_id=str(j.get("id", "")),
    )


def _from_ashby(j: dict, board: str) -> JobPosting:
    comp = j.get("compensation") or {}
    return JobPosting(
        url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}/{j.get('id')}",
        company=board,
        title=(j.get("title") or "").strip(),
        location=(j.get("location") or "").strip(),
        description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
        ats_type="ashby",
        posted_at=(j.get("publishedAt") or "")[:10],
        compensation=comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary") or "",
        workplace=("remote" if j.get("isRemote") else (j.get("workplaceType") or "")).lower(),
        external_id=str(j.get("id", "")),
    )


def _epoch_ms_to_date(ms) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def list_board(ats: str, board: str, company: str = "") -> list[JobPosting]:
    """All open roles on one company's board, descriptions included."""
    if ats == "greenhouse":
        r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"})
        r.raise_for_status()
        name = company or _gh_board_name(board)
        return [_from_greenhouse(j, board, name) for j in r.json().get("jobs", [])]
    if ats in ("lever", "lever-eu"):
        host = "api.eu.lever.co" if ats == "lever-eu" else "api.lever.co"
        r = _get(f"https://{host}/v0/postings/{board}", params={"mode": "json"})
        r.raise_for_status()
        return [_with_company(_from_lever(j, board), company) for j in r.json()]
    if ats == "ashby":
        r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{board}",
                 params={"includeCompensation": "true"})
        r.raise_for_status()
        return [_with_company(_from_ashby(j, board), company)
                for j in r.json().get("jobs", []) if j.get("isListed", True)]
    raise ValueError(f"Unsupported board type {ats!r} (use greenhouse, lever, lever-eu, ashby)")


def _with_company(p: JobPosting, company: str) -> JobPosting:
    if company:
        p.company = company
    return p


def fetch_posting(url: str) -> Optional[JobPosting]:
    """Fetch one posting via its ATS API. None if *url* isn't a recognized board.

    Raises :class:`PostingClosed` when the ATS reports the job gone.
    """
    parsed = parse_ats_url(url)
    if not parsed:
        return None
    ats, board, job_id = parsed
    try:
        if ats == "greenhouse":
            r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
            if r.status_code == 404:
                raise PostingClosed(f"Greenhouse job {board}/{job_id} not found")
            r.raise_for_status()
            p = _from_greenhouse(r.json(), board, _gh_board_name(board))
        elif ats in ("lever", "lever-eu"):
            host = "api.eu.lever.co" if ats == "lever-eu" else "api.lever.co"
            r = _get(f"https://{host}/v0/postings/{board}/{job_id}")
            if r.status_code == 404:
                raise PostingClosed(f"Lever job {board}/{job_id} not found")
            r.raise_for_status()
            p = _from_lever(r.json(), board)
        else:  # ashby: no single-job endpoint; find it on the board
            jobs = list_board("ashby", board)
            p = next((j for j in jobs if j.external_id == job_id), None)
            if p is None:
                raise PostingClosed(f"Ashby job {board}/{job_id} not on the board")
    except PostingClosed:
        raise
    except Exception:
        return None  # API hiccup -> let the caller fall back to HTML scraping
    p.url = url  # keep the URL the user gave us as the tracker key
    return p if p.description else None


def jsonld_posting(url: str, html: str) -> Optional[JobPosting]:
    """Read a schema.org JobPosting from the page's JSON-LD, if present."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for node in _iter_nodes(data):
            if _is_type(node, "JobPosting"):
                return _from_jsonld(url, node)
    return None


def _iter_nodes(data):
    if isinstance(data, list):
        for d in data:
            yield from _iter_nodes(d)
    elif isinstance(data, dict):
        yield data
        for d in data.get("@graph", []) or []:
            yield from _iter_nodes(d)


def _is_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    return t == name or (isinstance(t, list) and name in t)


def _from_jsonld(url: str, n: dict) -> Optional[JobPosting]:
    org = n.get("hiringOrganization") or {}
    locs = n.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    loc_names = []
    for loc in locs:
        a = (loc or {}).get("address") or {}
        if isinstance(a, dict):
            loc_names.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"),
                                                    a.get("addressCountry") if isinstance(a.get("addressCountry"), str)
                                                    else None) if x))
    desc = html_to_text(n.get("description", ""))
    if len(desc) < 200:
        return None  # a stub — not worth trusting over the full page
    return JobPosting(
        url=url,
        company=(org.get("name") if isinstance(org, dict) else str(org)) or "",
        title=(n.get("title") or "").strip(),
        location="; ".join(l for l in loc_names if l),
        description=desc,
        posted_at=str(n.get("datePosted") or "")[:10],
        workplace="remote" if n.get("jobLocationType") == "TELECOMMUTE" else "",
    )
