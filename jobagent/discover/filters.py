"""Cheap deterministic filters — run before any LLM call.

Two layers:

* :func:`screen_listing` — title / location / age, on board metadata alone.
* :func:`hard_stops` — deal-breakers stated in the JD text (no sponsorship when
  you need it, clearance you don't hold, far more years than you have).

Every rejection returns a human-readable reason that is stored with the job, so a
filtered role is auditable rather than silently dropped.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from ..apply.fieldmap import has_phrase
from ..models import JobPosting

_REMOTE = ("remote", "anywhere", "distributed", "work from home")

CLEARANCE_TERMS = ("security clearance", "secret clearance", "ts/sci", "top secret",
                   "polygraph", "active clearance", "clearance required")
NO_SPONSORSHIP = ("unable to sponsor", "not able to sponsor", "cannot sponsor", "can't sponsor",
                  "will not sponsor", "won't sponsor", "do not sponsor", "does not sponsor",
                  "no sponsorship", "not provide sponsorship", "not offer sponsorship",
                  "sponsorship is not available", "without sponsorship",
                  "must be authorized to work in the united states without")
SPONSORSHIP_OFFERED = ("sponsorship available", "will sponsor", "visa sponsorship is available",
                       "we sponsor", "sponsorship provided", "able to sponsor")
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?\+?\s*years?", re.I)


def is_remote(p: JobPosting) -> bool:
    return p.workplace == "remote" or any(has_phrase(p.location, r) for r in _REMOTE)


def screen_listing(p: JobPosting, cfg: dict, today: Optional[date] = None) -> Optional[str]:
    """Reason the listing is out of scope, or None to keep it."""
    titles = cfg.get("titles") or {}
    inc, exc = titles.get("include") or [], titles.get("exclude") or []
    if inc and not any(has_phrase(p.title, t) for t in inc):
        return "title: no include term"
    bad = next((t for t in exc if has_phrase(p.title, t)), None)
    if bad:
        return f"title: excluded '{bad}'"

    locs = cfg.get("locations") or {}
    blocked = next((b for b in locs.get("block") or [] if has_phrase(p.location, b)), None)
    if blocked:
        return f"location: blocked '{blocked}'"
    allow = locs.get("allow") or []
    remote_ok = locs.get("remote_ok", True)
    if p.location and allow and not any(has_phrase(p.location, a) for a in allow):
        if not (remote_ok and is_remote(p)):
            return f"location: '{p.location[:40]}' not in allow list"

    max_age = int(cfg.get("max_posting_age_days") or 0)
    if max_age and p.posted_at:
        try:
            posted = datetime.fromisoformat(p.posted_at[:10]).date()
            age = ((today or date.today()) - posted).days
            if age > max_age:
                return f"age: posted {age} days ago"
        except ValueError:
            pass
    return None


_PREFERRED = re.compile(r"prefer|nice to have|nice-to-have|bonus|ideally|a plus|plus if", re.I)
_REQUIRED = re.compile(r"require|minimum|basic qualifications|must|what you need|you have|we.re looking for", re.I)


def required_years(text: str) -> Optional[int]:
    """Largest plausible *required* 'N+ years' in the JD.

    Ignores values >15 (company age, etc.) and any mention that sits under a
    preferred / nice-to-have heading — those are not deal-breakers.
    """
    text = text or ""
    vals = []
    for m in _YEARS.finditer(text):
        v = int(m.group(1))
        if not 0 < v <= 15:
            continue
        before = text[max(0, m.start() - 400):m.start()]
        last_pref = max((x.end() for x in _PREFERRED.finditer(before)), default=-1)
        last_req = max((x.end() for x in _REQUIRED.finditer(before)), default=-1)
        if last_pref > last_req:
            continue
        vals.append(v)
    return max(vals) if vals else None


def hard_stops(p: JobPosting, cfg: dict, needs_sponsorship: bool) -> list[str]:
    """Deal-breakers stated in the description. Empty list = none found."""
    hf = cfg.get("hard_filters") or {}
    text = p.description.lower()
    stops: list[str] = []

    spons = hf.get("sponsorship", "auto")
    if (spons is True or (spons == "auto" and needs_sponsorship)):
        offered = any(has_phrase(text, s) for s in SPONSORSHIP_OFFERED)
        refused = next((s for s in NO_SPONSORSHIP if has_phrase(text, s)), None)
        if refused and not offered:
            stops.append(f"no visa sponsorship ('{refused}')")

    if not hf.get("has_security_clearance", False):
        term = next((t for t in CLEARANCE_TERMS if has_phrase(text, t)), None)
        if term:
            stops.append(f"requires clearance ('{term}')")

    mine = hf.get("years_experience")
    if mine is not None:
        req = required_years(p.description)
        if req is not None and req > int(mine) + int(hf.get("years_slack", 2)):
            stops.append(f"asks for {req}+ years (you have {mine})")
    return stops
