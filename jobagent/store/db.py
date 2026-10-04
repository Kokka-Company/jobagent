"""SQLite persistence for applications and contacts.

Thin, dependency-free layer (stdlib ``sqlite3``). Call :func:`init_db` once; the
helpers upsert/read the small amount of state the tool tracks.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models import Application, ApplicationStatus, Contact, JobPosting

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url     TEXT NOT NULL UNIQUE,
    company     TEXT DEFAULT '',
    title       TEXT DEFAULT '',
    ats_type    TEXT DEFAULT 'unknown',
    status      TEXT DEFAULT 'draft',
    resume_pdf  TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    company        TEXT DEFAULT '',
    domain         TEXT DEFAULT '',
    title          TEXT DEFAULT '',
    inferred_email TEXT DEFAULT '',
    verified_email TEXT DEFAULT '',
    confidence     INTEGER DEFAULT 0,
    source         TEXT DEFAULT ''
);

-- Every posting discovery has seen, kept even when filtered out, so re-scans skip
-- it and you can audit why it was dropped. status: new | filtered | duplicate |
-- evaluated | closed. decision (after evaluate): apply | consider | skip.
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    dedup_key     TEXT NOT NULL,
    company       TEXT DEFAULT '',
    title         TEXT DEFAULT '',
    location      TEXT DEFAULT '',
    ats_type      TEXT DEFAULT 'unknown',
    posted_at     TEXT DEFAULT '',
    compensation  TEXT DEFAULT '',
    workplace     TEXT DEFAULT '',
    description   TEXT DEFAULT '',
    source        TEXT DEFAULT '',
    status        TEXT DEFAULT 'new',
    reason        TEXT DEFAULT '',
    score         REAL,
    decision      TEXT DEFAULT '',
    evaluation    TEXT DEFAULT '',    -- full evaluation JSON
    discovered_at TEXT NOT NULL,
    evaluated_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_dedup ON jobs(dedup_key);

CREATE TABLE IF NOT EXISTS email_patterns (
    domain  TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,     -- e.g. "{first}.{last}", "{f}{last}"
    source  TEXT DEFAULT ''
);
"""


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
def upsert_application(app: Application, db_path: Optional[Path] = None) -> int:
    now = datetime.utcnow().isoformat()
    with _connect(db_path) as conn:
        cur = conn.execute("SELECT id FROM applications WHERE job_url = ?", (app.job_url,))
        row = cur.fetchone()
        if row:
            conn.execute(
                """UPDATE applications SET company=?, title=?, ats_type=?, status=?,
                       resume_pdf=?, notes=?, updated_at=? WHERE job_url=?""",
                (app.company, app.title, app.ats_type, app.status.value,
                 app.resume_pdf, app.notes, now, app.job_url),
            )
            return int(row["id"])
        cur = conn.execute(
            """INSERT INTO applications
                   (job_url, company, title, ats_type, status, resume_pdf, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (app.job_url, app.company, app.title, app.ats_type, app.status.value,
             app.resume_pdf, app.notes, now, now),
        )
        return int(cur.lastrowid)


def list_applications(db_path: Optional[Path] = None) -> list[Application]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    return [
        Application(
            id=r["id"], job_url=r["job_url"], company=r["company"], title=r["title"],
            ats_type=r["ats_type"], status=ApplicationStatus(r["status"]),
            resume_pdf=r["resume_pdf"], notes=r["notes"],
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Discovered jobs
# --------------------------------------------------------------------------- #
def dedup_key(company: str, title: str, location: str = "") -> str:
    """Same role re-posted under a new URL (or on two boards) collapses to one key."""
    import re

    def n(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return f"{n(company)}|{n(title)}|{n(location.split(';')[0])}"


def job_seen(url: str, key: str, db_path: Optional[Path] = None) -> Optional[str]:
    """'url' if this exact URL is known, 'dup' if an equivalent role is, else None."""
    with _connect(db_path) as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE url=?", (url,)).fetchone():
            return "url"
        if conn.execute("SELECT 1 FROM jobs WHERE dedup_key=? AND status != 'filtered'",
                        (key,)).fetchone():
            return "dup"
    return None


def add_job(p: JobPosting, *, status: str = "new", reason: str = "", source: str = "",
            db_path: Optional[Path] = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO jobs (url, dedup_key, company, title, location, ats_type,
                   posted_at, compensation, workplace, description, source, status, reason,
                   discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p.url, dedup_key(p.company, p.title, p.location), p.company, p.title, p.location,
             p.ats_type, p.posted_at, p.compensation, p.workplace,
             p.description if status == "new" else "", source, status, reason,
             datetime.utcnow().isoformat()),
        )


def jobs_by_status(status: str, limit: int = 1000, db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY posted_at DESC LIMIT ?", (status, limit)
        ).fetchall()


def ranked_jobs(min_score: float = 0, limit: int = 50, db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE status='evaluated' AND score >= ? "
            "ORDER BY score DESC, posted_at DESC LIMIT ?", (min_score, limit)
        ).fetchall()


def save_evaluation(url: str, score: Optional[float], decision: str, evaluation: dict,
                    status: str = "evaluated", db_path: Optional[Path] = None) -> None:
    import json
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET score=?, decision=?, evaluation=?, status=?, evaluated_at=? WHERE url=?",
            (score, decision, json.dumps(evaluation), status, datetime.utcnow().isoformat(), url),
        )


# --------------------------------------------------------------------------- #
# Contacts & email patterns
# --------------------------------------------------------------------------- #
def add_contact(contact: Contact, db_path: Optional[Path] = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO contacts
                   (name, company, domain, title, inferred_email, verified_email, confidence, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (contact.name, contact.company, contact.domain, contact.title,
             contact.inferred_email, contact.verified_email, contact.confidence, contact.source),
        )
        return int(cur.lastrowid)


def get_pattern(domain: str, db_path: Optional[Path] = None) -> Optional[str]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT pattern FROM email_patterns WHERE domain=?", (domain,)).fetchone()
    return row["pattern"] if row else None


def set_pattern(domain: str, pattern: str, source: str = "", db_path: Optional[Path] = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO email_patterns (domain, pattern, source) VALUES (?, ?, ?) "
            "ON CONFLICT(domain) DO UPDATE SET pattern=excluded.pattern, source=excluded.source",
            (domain, pattern, source),
        )
