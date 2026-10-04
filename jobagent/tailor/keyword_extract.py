"""Extract a structured KeywordSet from a job description (cheap model)."""
from __future__ import annotations

from ..config import settings
from ..llm import complete_json
from ..models import JobPosting, KeywordSet

_SYSTEM = (
    "You analyze job descriptions and extract the language a strong resume should "
    "mirror. Return the employer's OWN phrasings where possible. Never invent."
)


def extract_keywords(posting: JobPosting) -> KeywordSet:
    data = complete_json(
        "From the job description below, extract what the employer is asking for. "
        "Return ONLY JSON with these array keys:\n"
        '  "hard_skills"  - concrete technical/functional skills\n'
        '  "tools"        - named tools, platforms, languages\n'
        '  "soft_skills"  - communication/leadership style terms\n'
        '  "must_haves"   - explicit required qualifications\n'
        '  "nice_to_haves"- preferred/bonus qualifications\n'
        '  "exact_phrasings" - short verbatim phrases (3-6 words) worth mirroring\n\n'
        f"TITLE: {posting.title}\nCOMPANY: {posting.company}\n\n"
        f"DESCRIPTION:\n{posting.description[:12000]}",
        model=settings.model_parse,
        system=_SYSTEM,
        max_tokens=1500,
    )

    def arr(key: str) -> list[str]:
        v = data.get(key, [])
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    return KeywordSet(
        hard_skills=arr("hard_skills"),
        tools=arr("tools"),
        soft_skills=arr("soft_skills"),
        must_haves=arr("must_haves"),
        nice_to_haves=arr("nice_to_haves"),
        exact_phrasings=arr("exact_phrasings"),
    )
