"""End-to-end Module A pipeline: URL -> tailored resume PDF + report."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..models import ApplicationStatus, Application, JobPosting, TailorResult
from ..profile_loader import load_resume
from ..scrape.jd_scraper import scrape
from ..store import db
from .keyword_extract import extract_keywords
from .render import compile_pdf, render_tex, slugify
from .rewrite import apply_tailoring, tailor


@dataclass
class TailorOutput:
    posting: JobPosting
    result: TailorResult
    out_dir: Path
    tex_path: Path
    pdf_path: Path


def run_tailor(url: str) -> TailorOutput:
    settings.ensure_dirs()
    db.init_db()

    posting = scrape(url)
    resume = load_resume()
    keywords = extract_keywords(posting)
    result = tailor(resume, keywords, posting.title, posting.company)
    tailored = apply_tailoring(resume, result)

    tex = render_tex(tailored)
    out_dir = settings.generated_dir / slugify(posting.company, posting.title)
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / "resume.tex"
    tex_path.write_text(tex, encoding="utf-8")
    pdf_path = compile_pdf(tex, out_dir / "resume.pdf")

    # Persist a report + tracker row.
    (out_dir / "report.json").write_text(
        json.dumps(
            {
                "url": url,
                "company": posting.company,
                "title": posting.title,
                "keywords": keywords.model_dump(),
                "changed_bullets": result.changed_ids,
                "gap_list": result.gap_list,
                "reverted_by_validation": result.reverted,
                "match_notes": result.match_notes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    db.upsert_application(
        Application(
            job_url=url, company=posting.company, title=posting.title,
            ats_type=posting.ats_type, status=ApplicationStatus.DRAFT,
            resume_pdf=str(pdf_path),
            notes=f"gaps={len(result.gap_list)}; changed={len(result.changed_ids)}",
        )
    )
    return TailorOutput(posting, result, out_dir, tex_path, pdf_path)
