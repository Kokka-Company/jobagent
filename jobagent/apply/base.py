"""Shared types and helpers for application-form adapters.

An adapter knows how to drive one ATS's form. It receives a live Playwright
``page`` plus a :class:`FillContext` (the answer book + résumé PDF path) and
returns a :class:`FillReport`. Adapters never submit on their own — the runner
owns the submit/dry-run gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .fieldmap import AnswerBook

if TYPE_CHECKING:  # avoid importing Playwright unless a browser is actually used
    from playwright.sync_api import Page


# Markers that a human/anti-bot wall is present — we must not try to submit.
_CAPTCHA_SIGNALS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "div.g-recaptcha",
    "div.h-captcha",
    "iframe[title*='challenge']",
    "#cf-challenge-running",
]


@dataclass
class FillContext:
    answers: AnswerBook
    resume_pdf: Optional[Path] = None
    company: str = ""
    title: str = ""


@dataclass
class FillReport:
    ats: str = "unknown"
    filled: dict[str, str] = field(default_factory=dict)   # field key -> value applied
    skipped: list[str] = field(default_factory=list)       # labels we saw but could not answer
    needs_review: list[str] = field(default_factory=list)  # sensitive fills / attestations for a human
    uploaded_resume: bool = False
    captcha_detected: bool = False
    submitted: bool = False
    error: str = ""

    def note_filled(self, key: str, value: str) -> None:
        self.filled[key] = value


def detect_captcha(page: "Page") -> bool:
    for sel in _CAPTCHA_SIGNALS:
        try:
            if page.query_selector(sel) is not None:
                return True
        except Exception:
            continue
    return False


class BaseAdapter:
    """Interface every ATS adapter implements."""

    name: str = "base"

    def fill(self, page: "Page", ctx: FillContext, report: FillReport) -> None:
        """Fill as many fields as possible. Must not click the final submit."""
        raise NotImplementedError

    def submit(self, page: "Page") -> bool:
        """Click the form's submit control. Return True if a submit was issued."""
        raise NotImplementedError
