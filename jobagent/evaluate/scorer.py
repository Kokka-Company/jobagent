"""Score how well a posting fits the candidate — reproducibly and without flattery.

Pipeline (cheapest gate first):

1. **Hard stops** (:func:`~jobagent.discover.filters.hard_stops`) — deal-breakers
   stated in the JD. Any hit -> ``skip`` without spending an LLM call.
2. **Requirements, JD only** (cheap model). Each requirement gets an importance and
   a verbatim quote. The model never sees the résumé here, so importance can't be
   bent toward what the candidate happens to have. A quote we can't find in the JD
   caps that requirement at ``meaningful``.
3. **Match** (evaluate model). Each requirement is marked ``stated`` (cite a bullet
   id), ``inferred`` or ``none``, plus 1–5 dimension scores. A ``stated`` claim
   citing no real bullet is downgraded to ``inferred``.
4. **Score in code**: weighted mean of the dimensions, then caps — an unmet
   *critical* requirement or a role matching none of your targets cannot score
   above 3.4. Decision: ≥4.0 apply · ≥3.5 consider · else skip.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings
from ..discover.filters import hard_stops
from ..llm import complete_json
from ..models import JobPosting, ResumeContent

IMPORTANCE = ("critical", "high", "meaningful", "preferred")
WEIGHTS = {"cv_match": 0.40, "north_star": 0.30, "level": 0.15, "comp": 0.15}
CAP_UNMET_CRITICAL = 3.4
APPLY_AT, CONSIDER_AT = 4.0, 3.5


class Requirement(BaseModel):
    id: str
    text: str
    importance: str = "meaningful"
    quote: str = ""
    evidence: str = "none"                 # stated | inferred | none
    resume_refs: list[str] = Field(default_factory=list)
    note: str = ""


class Evaluation(BaseModel):
    url: str
    company: str = ""
    title: str = ""
    score: Optional[float] = None          # 1–5, None when hard-stopped
    decision: str = "skip"                 # apply | consider | skip
    hard_stops: list[str] = Field(default_factory=list)
    caps: list[str] = Field(default_factory=list)
    dimensions: dict[str, Optional[float]] = Field(default_factory=dict)
    target: str = ""
    role_summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    rationale: str = ""


# --------------------------------------------------------------------------- #
# Pass 1: requirements from the JD alone
# --------------------------------------------------------------------------- #
_REQ_SYSTEM = ("You read job descriptions precisely. You quote, you don't paraphrase "
               "importance, and you never invent requirements.")


def extract_requirements(p: JobPosting) -> tuple[list[Requirement], str]:
    data = complete_json(
        "List what this employer requires, most important first (max 14). Return ONLY JSON:\n"
        '{"role_summary": "<one sentence: what this person will actually do>",\n'
        ' "requirements": [{"text": "<requirement, ≤12 words>",\n'
        '   "importance": "critical|high|meaningful|preferred",\n'
        '   "quote": "<verbatim span from the JD that states it, ≤25 words>"}]}\n\n'
        "importance: critical = explicitly mandatory ('must', 'required', minimum years, "
        "degree/licence gates); high = listed among core qualifications; meaningful = "
        "emphasized in responsibilities but not stated as a requirement; preferred = "
        "'nice to have', 'bonus', 'preferred', 'ideally'.\n\n"
        f"TITLE: {p.title}\nCOMPANY: {p.company}\nLOCATION: {p.location}\n\n"
        f"DESCRIPTION:\n{p.description[:14000]}",
        model=settings.model_parse, system=_REQ_SYSTEM, max_tokens=2500,
    )
    jd = _squash(p.description)
    reqs = []
    for i, r in enumerate(data.get("requirements") or [], 1):
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        imp = str(r.get("importance", "meaningful")).lower()
        imp = imp if imp in IMPORTANCE else "meaningful"
        quote = str(r.get("quote", "")).strip()
        # Evidence gate: an importance claim we can't trace to the JD is demoted.
        if imp in ("critical", "high") and (not quote or _squash(quote) not in jd):
            imp = "meaningful"
        reqs.append(Requirement(id=f"r{i}", text=str(r["text"]).strip(), importance=imp, quote=quote))
    return reqs, str(data.get("role_summary", "")).strip()


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# --------------------------------------------------------------------------- #
# Pass 2: match against the résumé and targets
# --------------------------------------------------------------------------- #
_MATCH_SYSTEM = (
    "You are a blunt, calibrated recruiter evaluating fit for the CANDIDATE's benefit. "
    "Over-rating wastes their time on applications that won't convert. Only cite "
    "evidence that is actually in the résumé."
)


def _resume_payload(r: ResumeContent) -> dict:
    return {
        "headline": r.headline, "summary": r.summary, "skills": r.skills,
        "experience": [{"company": x.company, "title": x.title, "dates": f"{x.start}–{x.end}",
                        "bullets": [{"id": b.id, "text": b.text} for b in x.bullets]}
                       for x in r.experience],
        "education": [{"school": e.school, "degree": e.degree, "dates": f"{e.start}–{e.end}"}
                      for e in r.education],
    }


def match(p: JobPosting, reqs: list[Requirement], resume: ResumeContent, cfg: dict) -> dict:
    targets = [{"name": t.get("name"), "signals": t.get("signals", [])}
               for t in cfg.get("targets") or []]
    comp_floor = (cfg.get("compensation") or {})
    return complete_json(
        "Evaluate this candidate against the posting. Return ONLY JSON:\n"
        '{"matches": [{"id": "r1", "evidence": "stated|inferred|none",\n'
        '              "resume_refs": ["<bullet id>"], "note": "<≤15 words>"}],\n'
        ' "target": "<name of the best-matching candidate target, or \\"none\\">",\n'
        ' "dimensions": {"cv_match": 1-5, "north_star": 1-5, "level": 1-5, "comp": 1-5 or null},\n'
        ' "strengths": ["<≤3 strongest selling points for THIS role>"],\n'
        ' "gaps": ["<requirements they would probe or reject on>"],\n'
        ' "red_flags": ["<posting concerns: vague scope, mismatched level, churn signals…>"],\n'
        ' "rationale": "<2-3 sentences, direct>"}\n\n'
        "Evidence: stated = a résumé bullet or skill directly shows it (cite bullet ids); "
        "inferred = plausible from adjacent experience but not shown; none = no support.\n"
        "Dimensions (5 = exceptional, 3 = adequate, 1 = poor):\n"
        "  cv_match   – coverage of critical/high requirements by stated evidence.\n"
        "  north_star – fit with the candidate's targets below; matches none of them -> 1.\n"
        "  level      – seniority/scope vs. the candidate's trajectory (over- or under-level both score low).\n"
        "  comp       – posted pay vs. the floor; null if no pay is posted.\n\n"
        f"CANDIDATE TARGETS (best first): {json.dumps(targets)}\n"
        f"COMP FLOOR: {json.dumps(comp_floor)}\n\n"
        f"POSTING: {p.title} at {p.company} ({p.location}); posted pay: {p.compensation or 'not stated'}\n"
        f"REQUIREMENTS:\n{json.dumps([r.model_dump(include={'id','text','importance'}) for r in reqs], indent=1)}\n\n"
        f"RÉSUMÉ:\n{json.dumps(_resume_payload(resume), indent=1)}",
        model=settings.model_evaluate, system=_MATCH_SYSTEM, max_tokens=3000,
    )


# --------------------------------------------------------------------------- #
# Scoring (pure — unit tested)
# --------------------------------------------------------------------------- #
def _dim(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return min(5.0, max(1.0, f))


def score_evaluation(ev: Evaluation, raw: dict, resume: ResumeContent) -> Evaluation:
    """Merge the match JSON into *ev*, verify citations, compute score/decision."""
    bullet_ids = {b.id for role in resume.experience for b in role.bullets}
    by_id = {m.get("id"): m for m in raw.get("matches") or [] if isinstance(m, dict)}
    for r in ev.requirements:
        m = by_id.get(r.id, {})
        ev_kind = str(m.get("evidence", "none")).lower()
        refs = [x for x in (m.get("resume_refs") or []) if x in bullet_ids]
        if ev_kind == "stated" and not refs and not _in_skills(r.text, resume):
            ev_kind = "inferred"  # a "stated" claim must point at something real
        r.evidence = ev_kind if ev_kind in ("stated", "inferred", "none") else "none"
        r.resume_refs, r.note = refs, str(m.get("note", ""))[:160]

    dims = {k: _dim((raw.get("dimensions") or {}).get(k)) for k in WEIGHTS}
    ev.dimensions = dims
    ev.target = str(raw.get("target") or "none")
    ev.strengths = [str(x) for x in raw.get("strengths") or []][:5]
    ev.gaps = [str(x) for x in raw.get("gaps") or []][:8]
    ev.red_flags = [str(x) for x in raw.get("red_flags") or []][:5]
    ev.rationale = str(raw.get("rationale", "")).strip()

    present = {k: v for k, v in dims.items() if v is not None}
    if not present:
        ev.score, ev.decision = None, "skip"
        ev.caps.append("evaluation returned no dimension scores")
        return ev
    wsum = sum(WEIGHTS[k] for k in present)
    score = sum(WEIGHTS[k] * v for k, v in present.items()) / wsum

    unmet = [r.text for r in ev.requirements if r.importance == "critical" and r.evidence == "none"]
    if unmet:
        ev.caps.append(f"unmet critical requirement(s): {'; '.join(unmet[:3])}")
        score = min(score, CAP_UNMET_CRITICAL)
    if ev.target.lower() == "none" and (dims.get("north_star") or 5) <= 1.5:
        ev.caps.append("matches none of your targets")
        score = min(score, CAP_UNMET_CRITICAL)

    ev.score = round(score, 2)
    ev.decision = "apply" if score >= APPLY_AT else "consider" if score >= CONSIDER_AT else "skip"
    return ev


def _in_skills(text: str, resume: ResumeContent) -> bool:
    from ..apply.fieldmap import has_phrase
    skills = [s for group in resume.skills.values() for s in group]
    return any(has_phrase(text, s) for s in skills)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def evaluate(p: JobPosting, resume: ResumeContent, cfg: dict, needs_sponsorship: bool) -> Evaluation:
    ev = Evaluation(url=p.url, company=p.company, title=p.title)
    ev.hard_stops = hard_stops(p, cfg, needs_sponsorship)
    if ev.hard_stops:
        ev.decision = "skip"
        return ev
    ev.requirements, ev.role_summary = extract_requirements(p)
    raw = match(p, ev.requirements, resume, cfg)
    return score_evaluation(ev, raw, resume)
