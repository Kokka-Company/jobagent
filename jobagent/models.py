"""Pydantic data models shared across modules."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Resume content (the editable data behind the Jinja2 template)
# --------------------------------------------------------------------------- #
class Bullet(BaseModel):
    """A single achievement bullet. ``id`` is stable so tailoring can map changes back."""
    id: str
    text: str


class Role(BaseModel):
    company: str
    title: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    school: str
    degree: str
    location: str = ""
    start: str = ""
    end: str = ""
    details: list[str] = Field(default_factory=list)


class ResumeContent(BaseModel):
    """Structured resume content loaded from resume_content.yaml."""
    name: str
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict[str, str] = Field(default_factory=dict)  # e.g. {"LinkedIn": "...", "GitHub": "..."}
    summary: str = ""
    skills: dict[str, list[str]] = Field(default_factory=dict)  # category -> skills
    experience: list[Role] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Job posting & tailoring artifacts
# --------------------------------------------------------------------------- #
class JobPosting(BaseModel):
    url: str
    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""
    ats_type: str = "unknown"
    posted_at: str = ""        # ISO date when the source exposes it
    compensation: str = ""     # advertised range, verbatim, when the source exposes it
    workplace: str = ""        # remote | hybrid | onsite, when the source says
    external_id: str = ""      # the ATS's own job id


class KeywordSet(BaseModel):
    """Structured extraction of what the posting is asking for."""
    hard_skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    exact_phrasings: list[str] = Field(default_factory=list)


class TailorResult(BaseModel):
    """Output of the rewrite step. Preserves truthfulness via the gap list."""
    tailored_summary: str = ""
    tailored_bullets: dict[str, str] = Field(default_factory=dict)  # bullet id -> new text
    changed_ids: list[str] = Field(default_factory=list)
    gap_list: list[str] = Field(default_factory=list)  # JD keywords NOT legitimately claimable
    match_notes: str = ""
    reverted: dict[str, list[str]] = Field(default_factory=dict)  # id -> why it failed validation


# --------------------------------------------------------------------------- #
# Application tracking
# --------------------------------------------------------------------------- #
class ApplicationStatus(str, Enum):
    DRAFT = "draft"
    FILLED = "filled"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"  # captcha / manual step required
    ERROR = "error"


class Application(BaseModel):
    id: Optional[int] = None
    job_url: str
    company: str = ""
    title: str = ""
    ats_type: str = "unknown"
    status: ApplicationStatus = ApplicationStatus.DRAFT
    resume_pdf: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Contact(BaseModel):
    id: Optional[int] = None
    name: str
    company: str = ""
    domain: str = ""
    title: str = ""
    inferred_email: str = ""
    verified_email: str = ""
    confidence: int = 0
    source: str = ""
