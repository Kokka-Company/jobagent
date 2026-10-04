"""Poll every board in ``search.yaml`` and queue new, in-scope postings.

Each posting is recorded exactly once (by URL). Out-of-scope ones are stored as
``filtered`` with the reason, and equivalent re-posts as ``duplicate``, so a re-scan
only surfaces genuinely new roles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..profile_loader import load_search_config
from ..scrape.ats_api import list_board
from ..store import db
from .filters import screen_listing


@dataclass
class ScanResult:
    new: list = field(default_factory=list)          # JobPosting
    filtered: int = 0
    duplicates: int = 0
    already_seen: int = 0
    errors: dict[str, str] = field(default_factory=dict)  # company -> error


def scan(cfg: Optional[dict] = None, only: Optional[str] = None) -> ScanResult:
    cfg = cfg if cfg is not None else load_search_config()
    db.init_db()
    out = ScanResult()
    for c in cfg.get("companies") or []:
        name = c.get("name") or c.get("board", "")
        if only and only.lower() not in (name.lower(), str(c.get("board", "")).lower()):
            continue
        try:
            postings = list_board(c["ats"], c["board"], company=name)
        except Exception as exc:
            out.errors[name] = str(exc)[:200]
            continue
        for p in postings:
            key = db.dedup_key(p.company, p.title, p.location)
            seen = db.job_seen(p.url, key)
            if seen == "url":
                out.already_seen += 1
                continue
            reason = screen_listing(p, cfg)
            if reason:
                db.add_job(p, status="filtered", reason=reason, source=f"{c['ats']}:{c['board']}")
                out.filtered += 1
            elif seen == "dup":
                db.add_job(p, status="duplicate", reason="same company/title/location already queued",
                           source=f"{c['ats']}:{c['board']}")
                out.duplicates += 1
            else:
                db.add_job(p, status="new", source=f"{c['ats']}:{c['board']}")
                out.new.append(p)
    return out
