"""Deterministic truthfulness checks on tailored text — the prompt asks, this enforces.

A tailored bullet may re-angle the original; it may not:

* introduce a number that isn't in the original bullet (metrics are facts);
* name a JD skill/tool that appears nowhere in the master résumé (fabrication);
* contain résumé clichés or LLM leakage ("Here is the revised…").

The summary is checked against the whole résumé, since it legitimately draws on
every role. Pure functions — no LLM, no I/O.
"""
from __future__ import annotations

import re

from ..apply.fieldmap import has_phrase
from ..models import KeywordSet, ResumeContent, TailorResult

# Words that make a résumé read as generated. Shown to the model *and* enforced.
BANNED_PHRASES = (
    "spearheaded", "synergy", "synergies", "leveraged", "utilized", "passionate",
    "results-driven", "detail-oriented", "go-getter", "rockstar", "ninja", "guru",
    "cutting-edge", "best-in-class", "world-class", "thought leader",
    "seamlessly", "robust", "tapestry", "delve", "orchestrated", "pivotal",
)
LEAK_PHRASES = (
    "here is", "here's the", "revised version", "as an ai", "i apologize", "i cannot",
    "tailored bullet", "note:", "[", "]",
)
MAX_BULLET_CHARS = 230
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text or "")}


def resume_corpus(r: ResumeContent) -> str:
    parts = [r.headline, r.summary]
    parts += [s for group in r.skills.values() for s in group] + list(r.skills)
    for role in r.experience:
        parts += [role.company, role.title] + [b.text for b in role.bullets]
    for e in r.education:
        parts += [e.school, e.degree] + e.details
    return "\n".join(p for p in parts if p)


def _claimable_terms(keywords: KeywordSet) -> list[str]:
    return [t for t in keywords.hard_skills + keywords.tools if 2 <= len(t) <= 40]


def check_text(new: str, *, source: str, corpus: str, keywords: KeywordSet) -> list[str]:
    """Problems with one piece of tailored text (empty list = clean)."""
    problems = []
    low = new.lower()
    added_nums = _numbers(new) - _numbers(source)
    if added_nums:
        problems.append(f"new number(s) not in the original: {', '.join(sorted(added_nums))}")
    for term in _claimable_terms(keywords):
        if has_phrase(new, term) and not has_phrase(corpus, term):
            problems.append(f"claims '{term}', which the résumé never mentions")
    banned = [b for b in BANNED_PHRASES if has_phrase(low, b)]
    if banned:
        problems.append(f"cliché(s): {', '.join(banned)}")
    if any(l in low for l in LEAK_PHRASES):
        problems.append("contains assistant/meta text")
    return problems


def validate(result: TailorResult, master: ResumeContent, keywords: KeywordSet) -> dict[str, list[str]]:
    """Map of ``"summary"`` / bullet id -> problems, for every changed text that fails."""
    corpus = resume_corpus(master)
    originals = {b.id: b.text for role in master.experience for b in role.bullets}
    issues: dict[str, list[str]] = {}
    if result.tailored_summary:
        p = check_text(result.tailored_summary, source=corpus, corpus=corpus, keywords=keywords)
        if p:
            issues["summary"] = p
    for bid, text in result.tailored_bullets.items():
        if bid not in originals:
            issues[bid] = ["unknown bullet id"]
            continue
        p = check_text(text, source=originals[bid], corpus=corpus, keywords=keywords)
        if len(text) > MAX_BULLET_CHARS:
            p.append(f"too long ({len(text)} chars)")
        if p:
            issues[bid] = p
    return issues


def drop_failing(result: TailorResult, issues: dict[str, list[str]]) -> TailorResult:
    """Revert every failing change to the master text (keep what passed)."""
    fixed = result.model_copy(deep=True)
    if "summary" in issues:
        fixed.tailored_summary = ""
    for bid in issues:
        fixed.tailored_bullets.pop(bid, None)
    fixed.changed_ids = list(fixed.tailored_bullets)
    fixed.reverted = {k: v for k, v in issues.items()}
    return fixed
