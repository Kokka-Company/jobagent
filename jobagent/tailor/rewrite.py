"""Rewrite the master resume's language toward a posting — truthfully.

The model may re-angle, re-order emphasis, and adopt the posting's vocabulary for
experience the candidate *genuinely has*. It must NOT invent skills. Anything the
posting wants that the resume can't legitimately support goes in ``gap_list`` so
the human can decide, rather than being silently fabricated.
"""
from __future__ import annotations

import json

from ..config import settings
from ..llm import complete_json
from ..models import KeywordSet, ResumeContent, TailorResult
from .validate import BANNED_PHRASES, drop_failing, validate

_SYSTEM = (
    "You are an expert resume editor. You strengthen a resume for a specific job by "
    "rephrasing the candidate's REAL experience using the posting's vocabulary. "
    "Absolute rule: never add a skill, tool, metric, or claim the source resume does "
    "not already support. If the job wants something the resume lacks, list it as a gap "
    "instead of inventing it. Keep each bullet one line, action-verb led, quantified "
    "where the source already quantifies. Never change or add a number. "
    f"Avoid these words: {', '.join(BANNED_PHRASES)}."
)


def _bullets_payload(resume: ResumeContent) -> list[dict]:
    out = []
    for role in resume.experience:
        for b in role.bullets:
            out.append({"id": b.id, "role": f"{role.title} @ {role.company}", "text": b.text})
    return out


def tailor(resume: ResumeContent, keywords: KeywordSet, job_title: str, company: str) -> TailorResult:
    """Rewrite, validate, retry once with the problems listed, then drop what still fails.

    The retry is a fresh call (not a follow-up turn) so the model isn't anchored on
    its own bad draft; the specific problems are passed in as things to avoid.
    """
    result = _rewrite(resume, keywords, job_title, company)
    issues = validate(result, resume, keywords)
    if issues:
        result = _rewrite(resume, keywords, job_title, company, avoid=issues)
        issues = validate(result, resume, keywords)
    return drop_failing(result, issues) if issues else result


def _rewrite(resume: ResumeContent, keywords: KeywordSet, job_title: str, company: str,
             avoid: dict[str, list[str]] | None = None) -> TailorResult:
    bullets = _bullets_payload(resume)
    kw = keywords.model_dump()
    avoid_txt = ""
    if avoid:
        avoid_txt = ("\n\nA previous draft was REJECTED by automated checks. Do not repeat:\n"
                     + "\n".join(f"  - {k}: {'; '.join(v)}" for k, v in avoid.items()))

    data = complete_json(
        "Tailor this resume to the target job. Return ONLY JSON with keys:\n"
        '  "tailored_summary": rewritten 1-2 sentence summary (truthful re-angle),\n'
        '  "tailored_bullets": object mapping bullet id -> rewritten text (include ONLY bullets you changed),\n'
        '  "gap_list": array of posting requirements the resume does NOT legitimately support,\n'
        '  "match_notes": one short paragraph on how the tailoring aligns to the posting.\n\n'
        f"TARGET: {job_title} at {company}\n\n"
        f"CURRENT SUMMARY:\n{resume.summary}\n\n"
        f"WHAT THE POSTING WANTS (keywords):\n{json.dumps(kw, indent=2)}\n\n"
        f"RESUME BULLETS (id, role, text):\n{json.dumps(bullets, indent=2)}"
        f"{avoid_txt}",
        model=settings.model_tailor,
        system=_SYSTEM,
        max_tokens=3000,
    )

    tailored_bullets = {
        str(k): str(v).strip()
        for k, v in (data.get("tailored_bullets") or {}).items()
        if str(v).strip()
    }
    return TailorResult(
        tailored_summary=str(data.get("tailored_summary", "")).strip(),
        tailored_bullets=tailored_bullets,
        changed_ids=list(tailored_bullets.keys()),
        gap_list=[str(x).strip() for x in (data.get("gap_list") or []) if str(x).strip()],
        match_notes=str(data.get("match_notes", "")).strip(),
    )


def apply_tailoring(resume: ResumeContent, result: TailorResult) -> ResumeContent:
    """Return a NEW ResumeContent with tailored text merged in (master untouched)."""
    merged = resume.model_copy(deep=True)
    if result.tailored_summary:
        merged.summary = result.tailored_summary
    for role in merged.experience:
        for b in role.bullets:
            if b.id in result.tailored_bullets:
                b.text = result.tailored_bullets[b.id]
    return merged
