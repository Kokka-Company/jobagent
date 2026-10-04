"""Drive one application end to end: detect ATS, fill, gate submit, record status.

Flow: resolve the tailored résumé PDF (from the tracker row a prior ``tailor``
run wrote) -> launch Chrome via the shared Playwright config -> detect the ATS
from URL+DOM -> pick an adapter -> fill -> check for a captcha -> submit only
when explicitly live *and* unblocked -> persist the outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models import Application, ApplicationStatus
from ..store import db
from .adapters import get_adapter, supported
from .ats_detect import detect_ats
from .base import FillContext, FillReport, detect_captcha
from .fieldmap import build_answer_book


@dataclass
class ApplyOutcome:
    ats: str
    status: ApplicationStatus
    report: FillReport
    message: str = ""


def _resume_pdf_for(url: str) -> tuple[Optional[Path], str, str]:
    """Return (pdf_path, company, title) from the tracker row for *url*, if any."""
    for app in db.list_applications():
        if app.job_url == url:
            p = Path(app.resume_pdf) if app.resume_pdf else None
            return (p if p and p.exists() else None, app.company, app.title)
    return None, "", ""


def apply(url: str, *, dry_run: bool = True, headless: bool = False,
          hold: bool = False) -> ApplyOutcome:
    """Fill (and optionally submit) the application at *url*.

    ``dry_run`` (default) fills but never submits. ``hold`` keeps the browser open
    until the caller releases it (useful to review a dry-run fill).
    """
    settings.ensure_dirs()
    db.init_db()

    resume_pdf, company, title = _resume_pdf_for(url)
    answers = build_answer_book()
    report = FillReport()

    try:
        from playwright.sync_api import sync_playwright

        from ..browser import launch_kwargs
    except Exception as exc:  # Playwright not installed
        return ApplyOutcome("unknown", ApplicationStatus.ERROR, report,
                            f"Playwright unavailable: {exc}")

    status = ApplicationStatus.DRAFT
    message = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs(headless=headless))
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # some ATSs keep long-poll connections open

            html = page.content()
            ats = detect_ats(url, html)
            report.ats = ats

            adapter = get_adapter(ats)
            if adapter is None:
                status = ApplicationStatus.ERROR
                message = (f"No adapter for ATS '{ats}'. Supported: {', '.join(supported())}."
                           if ats != "unknown"
                           else f"Could not identify the ATS. Supported: {', '.join(supported())}.")
            else:
                ctx = FillContext(answers=answers, resume_pdf=resume_pdf,
                                  company=company, title=title)
                adapter.fill(page, ctx, report)
                report.captcha_detected = detect_captcha(page)

                if report.captcha_detected:
                    status = ApplicationStatus.BLOCKED
                    message = "Captcha / anti-bot wall detected — filled but not submitted. Finish manually."
                elif any(i.startswith("attestation") for i in report.needs_review) and not dry_run:
                    status = ApplicationStatus.FILLED
                    message = "Filled; attestation checkbox needs your tick — not auto-submitted."
                elif dry_run:
                    status = ApplicationStatus.FILLED
                    message = "Dry run: filled, not submitted."
                else:
                    report.submitted = adapter.submit(page)
                    status = (ApplicationStatus.SUBMITTED if report.submitted
                              else ApplicationStatus.FILLED)
                    message = "Submitted." if report.submitted else "Filled, but no submit control was found."

            if hold and not headless:
                try:
                    input("\n[review the browser, then press Enter to close] ")
                except (EOFError, KeyboardInterrupt):
                    pass
        except Exception as exc:
            status = ApplicationStatus.ERROR
            report.error = str(exc)
            message = f"Error while applying: {exc}"
        finally:
            browser.close()

    # Persist outcome (merge onto whatever tailor recorded).
    db.upsert_application(Application(
        job_url=url, company=company, title=title, ats_type=report.ats,
        status=status, resume_pdf=str(resume_pdf) if resume_pdf else "",
        notes=(f"filled={len(report.filled)}; skipped={len(report.skipped)}; "
               f"resume={'yes' if report.uploaded_resume else 'no'}; "
               f"captcha={'yes' if report.captcha_detected else 'no'}"),
    ))
    return ApplyOutcome(report.ats, status, report, message)
