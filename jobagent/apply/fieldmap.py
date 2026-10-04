"""Map a candidate's stored answers onto arbitrary application-form fields.

An :class:`AnswerBook` flattens ``standard_answers.yaml`` (+ a little from the
résumé) into canonical fields, each with alias keywords. Given a form field's
visible label, :meth:`AnswerBook.resolve` returns the best-matching answer so an
adapter can type or select it. Pure/offline — no browser, no network.

Matching is whole-word (so ``state`` never fires inside "statement" or "United
States") and a field may list ``excludes`` that veto a match ("company name" is
not the candidate's name). :func:`match_option` maps a stored answer onto a
select/radio's option texts with a polarity guard — it returns ``None`` rather
than guess, so an unmatched choice is left for the human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models import ResumeContent
from ..profile_loader import load_resume, load_standard_answers


# Fields whose answers carry legal/financial weight. They are only ever filled
# from an explicit profile value, and every fill is surfaced for human review.
SENSITIVE_KEYS = frozenset({
    "authorized_to_work", "requires_sponsorship", "visa_status", "salary_expectation",
    "gender", "race_ethnicity", "veteran_status", "disability_status",
})

# Checkbox labels that are legal attestations — never auto-ticked.
ATTESTATION_TERMS = (
    "i certify", "i attest", "i agree", "i acknowledge", "i confirm", "i consent",
    "terms", "privacy policy", "true and complete", "accurate and complete",
)


@dataclass(frozen=True)
class Answer:
    key: str              # canonical field name
    value: str            # display string ready to type / match against options
    is_choice: bool = False   # Yes/No or enumerated -> select an option, don't type

    @property
    def sensitive(self) -> bool:
        return self.key in SENSITIVE_KEYS


@dataclass
class _Field:
    key: str
    value: str
    aliases: list[str]
    is_choice: bool = False
    excludes: list[str] = field(default_factory=list)  # label words that veto this field


def _yesno(v) -> str:
    return "Yes" if bool(v) else "No"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def has_phrase(text: str, phrase: str) -> bool:
    """Whole-word/phrase containment, edge-aware for punctuation-led terms.

    ``\\b`` only anchors next to word characters, so a phrase that starts or ends
    with punctuation (".net", "c++") gets a different anchor on that side:
    ".net" matches "asp.net" but not ".network"; "java" never matches "javascript".
    """
    p = _norm(phrase)
    if not p:
        return False
    left = r"\b" if p[0].isalnum() else ""        # ".net" may follow "asp"
    right = r"\b" if p[-1].isalnum() else r"(?!\w)"
    return re.search(left + re.escape(p) + right, _norm(text)) is not None


_NEGATIONS = ("not", "no", "don't", "decline", "prefer not", "won't", "never", "false")
_YES_WORDS = ("yes", "i am", "i do", "i will", "i have", "agree", "true")


def _polarity(text: str) -> Optional[bool]:
    """True for an affirmative option, False for a negative one, None if neither."""
    t = _norm(text)
    if any(has_phrase(t, n) for n in _NEGATIONS):
        return False
    if any(has_phrase(t, y) for y in _YES_WORDS):
        return True
    return None


def match_option(answer: str, options: list[str]) -> Optional[int]:
    """Index of the option that expresses *answer*, or None when unsure.

    Exact text first, then whole-word containment, then — for Yes/No answers —
    polarity ("Yes, I am authorized" for Yes; never "I do not wish…" for Yes).
    Placeholder options ("Select…", "--") are ignored. Never guesses.
    """
    want = _norm(answer)
    if not want:
        return None
    cands = [(i, _norm(o)) for i, o in enumerate(options)
             if _norm(o) and not re.match(r"^(select|choose|please select|--|—)", _norm(o))]
    for i, o in cands:
        if o == want:
            return i
    contains = [i for i, o in cands if has_phrase(o, want)]
    if want in ("yes", "no"):
        target = want == "yes"
        contains = [i for i in contains if _polarity(options[i]) in (target, None)]
        if len(contains) == 1:
            return contains[0]
        polar = [i for i, _ in cands if _polarity(options[i]) is target]
        return polar[0] if len(polar) == 1 else None
    if len(contains) == 1:
        return contains[0]
    # "Decline to self-identify" vs "I don't wish to answer" — same intent.
    if "decline" in want or "prefer not" in want or "not wish" in want:
        dec = [i for i, o in cands if any(k in o for k in
               ("decline", "prefer not", "not wish", "don't wish", "choose not"))]
        return dec[0] if len(dec) == 1 else None
    return None


def is_attestation(label: str) -> bool:
    return any(has_phrase(label, t) for t in ATTESTATION_TERMS)


class AnswerBook:
    """Resolve form-field labels to stored answers, longest alias first."""

    def __init__(self, fields: list[_Field]):
        # Match specific aliases before generic ones (e.g. "first name" before "name").
        self._fields = fields
        self._by_alias: list[tuple[str, _Field]] = sorted(
            ((a, f) for f in fields for a in f.aliases),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def get(self, key: str) -> Optional[str]:
        for f in self._fields:
            if f.key == key:
                return f.value
        return None

    def resolve(self, label: str) -> Optional[Answer]:
        """Best answer for a field whose visible label/placeholder is *label*."""
        norm = _norm(label)
        if not norm:
            return None
        for alias, f in self._by_alias:
            if f.value == "" or not has_phrase(norm, alias):
                continue
            if any(has_phrase(norm, x) for x in f.excludes):
                continue
            return Answer(key=f.key, value=f.value, is_choice=f.is_choice)
        return None


# Label words that mean "name" refers to someone/something other than the candidate.
_NOT_CANDIDATE_NAME = ["company", "user", "username", "school", "university", "employer",
                       "manager", "reference", "referrer", "referral", "recruiter",
                       "preferred", "middle", "nickname", "project", "team"]


def build_answer_book(resume: Optional[ResumeContent] = None,
                      answers: Optional[dict] = None) -> AnswerBook:
    resume = resume or load_resume()
    answers = answers if answers is not None else load_standard_answers()

    personal = answers.get("personal", {}) or {}
    auth = answers.get("work_authorization", {}) or {}
    prefs = answers.get("preferences", {}) or {}
    eeo = answers.get("eeo", {}) or {}
    essays = answers.get("common_essays", {}) or {}

    # Prefer the explicit standard-answer value; fall back to the résumé.
    first = personal.get("first_name") or (resume.name.split()[0] if resume.name else "")
    last = personal.get("last_name") or (resume.name.split()[-1] if resume.name.split()[1:] else "")
    full = _norm(f"{first} {last}").title() or resume.name
    email = personal.get("email") or resume.email
    phone = personal.get("phone") or resume.phone
    linkedin = personal.get("linkedin") or resume.links.get("LinkedIn", "")
    website = personal.get("website") or resume.links.get("Website") or resume.links.get("GitHub", "")

    fields = [
        _Field("first_name", str(first), ["first name", "given name", "forename"]),
        _Field("last_name", str(last), ["last name", "family name", "surname"]),
        _Field("full_name", str(full), ["full name", "your name", "legal name", "name"],
               excludes=_NOT_CANDIDATE_NAME),
        _Field("email", str(email), ["email", "e-mail", "email address"],
               excludes=["reference", "referrer", "manager"]),
        _Field("phone", str(phone), ["phone", "mobile", "telephone", "cell", "phone number"],
               excludes=["reference", "referrer", "manager"]),
        _Field("linkedin", str(linkedin), ["linkedin"]),
        _Field("website", str(website), ["website", "portfolio", "personal site", "github", "personal url",
                "website url", "portfolio url"],
               excludes=["hear about", "referral", "referred", "source"]),
        _Field("address_line1", str(personal.get("address_line1", "")),
               ["address", "street address", "address line 1"],
               excludes=["email", "e-mail", "web address", "ip address"]),
        _Field("city", str(personal.get("city", "")), ["city", "town"]),
        _Field("state", str(personal.get("state", "")), ["state", "province", "state/province"],
               excludes=["united states", "statement"]),
        _Field("postal_code", str(personal.get("postal_code", "")), ["zip", "postal", "postcode"]),
        _Field("country", str(personal.get("country", "")), ["country"]),
        # Work authorization (choice / Yes-No)
        _Field("authorized_to_work", _yesno(auth.get("authorized_to_work")),
               ["authorized to work", "legally authorized", "work authorization",
                "right to work", "eligible to work"], is_choice=True),
        _Field("requires_sponsorship", _yesno(auth.get("requires_sponsorship")),
               ["sponsorship", "require sponsorship", "visa sponsorship", "need sponsorship"],
               is_choice=True),
        _Field("visa_status", str(auth.get("visa_status", "")),
               ["visa status", "immigration status", "work status", "citizenship"]),
        # Preferences
        _Field("salary_expectation", str(prefs.get("salary_expectation", "")),
               ["salary", "compensation expectation", "desired salary", "expected salary",
                "pay expectation"]),
        _Field("earliest_start_date", str(prefs.get("earliest_start_date", "")),
               ["start date", "available to start", "availability", "notice period",
                "when can you start"]),
        _Field("willing_to_relocate", _yesno(prefs.get("willing_to_relocate")),
               ["relocate", "relocation", "willing to move"], is_choice=True),
        _Field("remote_preference", str(prefs.get("remote_preference", "")),
               ["remote preference", "work preference", "work arrangement", "onsite or remote"],
               is_choice=True),
        # EEO (choice)
        _Field("gender", str(eeo.get("gender", "")), ["gender"], is_choice=True),
        _Field("race_ethnicity", str(eeo.get("race_ethnicity", "")),
               ["race", "ethnicity", "hispanic"], is_choice=True),
        _Field("veteran_status", str(eeo.get("veteran_status", "")),
               ["veteran", "protected veteran", "military"], is_choice=True),
        _Field("disability_status", str(eeo.get("disability_status", "")),
               ["disability", "disabled"], is_choice=True),
        # Essays (left blank in the YAML -> generated per-posting elsewhere)
        _Field("why_this_company", str(essays.get("why_this_company", "")),
               ["why do you want to work", "why this company", "why are you interested in",
                "interest in our company"]),
        _Field("why_this_role", str(essays.get("why_this_role", "")),
               ["why this role", "why this position", "why are you a good fit",
                "interest in this role"]),
    ]
    return AnswerBook(fields)
