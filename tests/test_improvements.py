"""Offline tests for discovery, evaluation scoring, tailoring validation and form matching."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobagent.models import Bullet, JobPosting, KeywordSet, ResumeContent, Role, TailorResult


def _resume():
    return ResumeContent(
        name="Ada Lovelace", summary="Strategy analyst.",
        skills={"Tools": ["Excel", "SQL"]},
        experience=[Role(company="Engines", title="Analyst", bullets=[
            Bullet(id="a1", text="Built a model that informed a $10M decision."),
            Bullet(id="a2", text="Automated reporting in Python, cutting time 60%."),
        ])],
    )


# ----------------------------------------------------------------- form matching
def test_has_phrase_is_whole_word_and_punctuation_aware():
    from jobagent.apply.fieldmap import has_phrase
    assert has_phrase("Senior Java Engineer", "java")
    assert not has_phrase("JavaScript developer", "java")
    assert has_phrase("ASP.NET services", ".net")
    assert not has_phrase(".network admin", ".net")
    assert not has_phrase("Personal statement", "state")


def test_answer_book_no_false_positives():
    from jobagent.apply.fieldmap import build_answer_book
    book = build_answer_book(_resume(), {"personal": {"first_name": "Ada", "state": "CA",
                                                      "website": "ada.dev"}})
    for label in ("Personal statement", "Company name", "Username",
                  "Are you located in the United States?", "How did you hear about us? (URL)",
                  "Reference email"):
        assert book.resolve(label) is None, label
    assert book.resolve("State").value == "CA"
    assert book.resolve("Portfolio URL").value == "ada.dev"


def test_match_option_polarity_and_no_guessing():
    from jobagent.apply.fieldmap import match_option
    assert match_option("Yes", ["Select...", "Yes, I am authorized", "No, I am not"]) == 1
    assert match_option("No", ["--", "Yes", "No"]) == 2
    assert match_option("Yes", ["I do not wish to be contacted", "I agree to be contacted"]) == 1
    assert match_option("Male", ["Female", "Male"]) == 1
    assert match_option("Decline to self-identify", ["Male", "Female", "I don't wish to answer"]) == 2
    assert match_option("Hybrid", ["Remote", "Onsite"]) is None   # never guess


def test_attestations_detected():
    from jobagent.apply.fieldmap import is_attestation
    assert is_attestation("I certify that the information provided is true and complete")
    assert not is_attestation("Are you willing to relocate?")


# ----------------------------------------------------------------- discovery
def test_parse_ats_url():
    from jobagent.scrape.ats_api import parse_ats_url
    assert parse_ats_url("https://job-boards.greenhouse.io/acme/jobs/123") == ("greenhouse", "acme", "123")
    assert parse_ats_url("https://boards.greenhouse.io/embed/job_app?for=acme&token=9") == ("greenhouse", "acme", "9")
    assert parse_ats_url("https://jobs.lever.co/acme/abc-1/apply") == ("lever", "acme", "abc-1")
    assert parse_ats_url("https://jobs.eu.lever.co/acme/abc") == ("lever-eu", "acme", "abc")
    assert parse_ats_url("https://jobs.ashbyhq.com/acme/uuid") == ("ashby", "acme", "uuid")
    assert parse_ats_url("https://acme.com/careers/1") is None


def test_jsonld_posting():
    from jobagent.scrape.ats_api import jsonld_posting
    html = """<script type="application/ld+json">{"@graph":[{"@type":"Organization"},
      {"@type":"JobPosting","title":"Strategy Lead","datePosted":"2026-09-01T00:00",
       "hiringOrganization":{"name":"Acme"},
       "jobLocation":{"address":{"addressLocality":"Austin","addressRegion":"TX"}},
       "description":"<p>""" + "Own the planning cycle. " * 20 + """</p>"}]}</script>"""
    p = jsonld_posting("https://acme.com/j/1", html)
    assert (p.company, p.title, p.location, p.posted_at) == ("Acme", "Strategy Lead", "Austin, TX", "2026-09-01")
    assert "planning cycle" in p.description


_CFG = {
    "titles": {"include": ["strategy", "chief of staff"], "exclude": ["intern"]},
    "locations": {"allow": ["new york"], "remote_ok": True},
    "max_posting_age_days": 30,
    "hard_filters": {"sponsorship": "auto", "has_security_clearance": False,
                     "years_experience": 4, "years_slack": 2},
}


def _p(**kw):
    base = dict(url="u", company="Acme", title="Strategy Lead", location="New York, NY",
                posted_at="2026-09-20", description="")
    base.update(kw)
    return JobPosting(**base)


def test_screen_listing():
    from jobagent.discover.filters import screen_listing
    today = date(2026, 10, 3)
    assert screen_listing(_p(), _CFG, today) is None
    assert "title" in screen_listing(_p(title="Software Engineer"), _CFG, today)
    assert "excluded" in screen_listing(_p(title="Strategy Intern"), _CFG, today)
    assert "location" in screen_listing(_p(location="London"), _CFG, today)
    assert screen_listing(_p(location="Remote - US"), _CFG, today) is None
    assert screen_listing(_p(location=""), _CFG, today) is None          # missing data passes
    assert "age" in screen_listing(_p(posted_at="2026-07-01"), _CFG, today)


def test_hard_stops_and_required_years():
    from jobagent.discover.filters import hard_stops, required_years
    assert required_years("Requirements: 3+ years. Preferred qualifications: 10+ years") == 3
    assert required_years("Founded 40 years ago.") is None
    jd = "Requirements: 9+ years of experience. We are unable to sponsor visas. TS/SCI required."
    stops = hard_stops(_p(description=jd), _CFG, needs_sponsorship=True)
    assert len(stops) == 3
    assert not any("sponsor" in s for s in hard_stops(_p(description=jd), _CFG, needs_sponsorship=False))
    offered = "We are unable to sponsor some roles, but visa sponsorship is available here."
    assert hard_stops(_p(description=offered), _CFG, needs_sponsorship=True) == []


def test_dedup_and_job_store(tmp_path):
    from jobagent.store import db
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    assert db.dedup_key("Acme, Inc.", "Strategy Lead", "NYC; Remote") == "acme inc|strategy lead|nyc"
    p = _p(url="https://x/1", description="JD")
    db.add_job(p, db_path=dbp)
    assert db.job_seen("https://x/1", "k", db_path=dbp) == "url"
    assert db.job_seen("https://x/2", db.dedup_key(p.company, p.title, p.location), db_path=dbp) == "dup"
    db.save_evaluation("https://x/1", 4.2, "apply", {"a": 1}, db_path=dbp)
    rows = db.ranked_jobs(4.0, db_path=dbp)
    assert len(rows) == 1 and rows[0]["decision"] == "apply"


# ----------------------------------------------------------------- evaluation scoring
def test_score_evaluation_weights_caps_and_citations():
    from jobagent.evaluate.scorer import Evaluation, Requirement, score_evaluation
    reqs = [Requirement(id="r1", text="Financial modeling", importance="critical"),
            Requirement(id="r2", text="Board-level M&A", importance="critical"),
            Requirement(id="r3", text="SQL", importance="preferred")]
    raw = {"matches": [{"id": "r1", "evidence": "stated", "resume_refs": ["a1"]},
                       {"id": "r2", "evidence": "stated", "resume_refs": ["zz-fake"]},
                       {"id": "r3", "evidence": "stated", "resume_refs": []}],
           "target": "Corporate strategy",
           "dimensions": {"cv_match": 5, "north_star": 5, "level": 5, "comp": None}}
    ev = score_evaluation(Evaluation(url="u", requirements=reqs), raw, _resume())
    by = {r.id: r for r in ev.requirements}
    assert by["r1"].evidence == "stated" and by["r1"].resume_refs == ["a1"]
    assert by["r2"].evidence == "inferred"          # cited a bullet that doesn't exist
    assert by["r3"].evidence == "stated"            # backed by the skills list
    assert ev.score == 5.0 and ev.decision == "apply"

    raw["matches"][1]["evidence"] = "none"
    ev = score_evaluation(Evaluation(url="u", requirements=[r.model_copy() for r in reqs]), raw, _resume())
    assert ev.score == 3.4 and ev.decision == "skip" and ev.caps


def test_score_thresholds():
    from jobagent.evaluate.scorer import Evaluation, score_evaluation
    raw = {"target": "x", "dimensions": {"cv_match": 4, "north_star": 3, "level": 4, "comp": 4}}
    ev = score_evaluation(Evaluation(url="u"), raw, _resume())
    assert ev.score == 3.7 and ev.decision == "consider"


# ----------------------------------------------------------------- tailoring validation
def test_validate_catches_fabrication_and_reverts():
    from jobagent.tailor.validate import drop_failing, validate
    kw = KeywordSet(hard_skills=["Financial modeling"], tools=["Tableau", "Python"])
    res = TailorResult(
        tailored_summary="Strategy analyst who builds models.",
        tailored_bullets={
            "a1": "Built a financial model that informed a $10M capital decision.",   # ok
            "a2": "Automated Tableau reporting in Python, cutting time 75%.",         # 2 problems
        })
    issues = validate(res, _resume(), kw)
    assert set(issues) == {"a2"}
    assert any("75" in p for p in issues["a2"]) and any("Tableau" in p for p in issues["a2"])
    fixed = drop_failing(res, issues)
    assert fixed.changed_ids == ["a1"] and "a2" in fixed.reverted


def test_validate_flags_cliches_and_leaks():
    from jobagent.tailor.validate import validate
    res = TailorResult(tailored_bullets={"a1": "Here is the revised bullet: Spearheaded a $10M model."})
    probs = validate(res, _resume(), KeywordSet())["a1"]
    assert any("cliché" in p for p in probs) and any("meta" in p for p in probs)


def test_tailor_retries_then_reverts(monkeypatch):
    from jobagent.tailor import rewrite
    drafts = iter([
        {"tailored_bullets": {"a2": "Cut time 90% with Tableau."}, "gap_list": ["Tableau"]},
        {"tailored_bullets": {"a2": "Cut time 90%."}, "gap_list": ["Tableau"]},
    ])
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        return next(drafts)
    monkeypatch.setattr(rewrite, "complete_json", fake)
    out = rewrite.tailor(_resume(), KeywordSet(tools=["Tableau"]), "Analyst", "Acme")
    assert len(prompts) == 2 and "REJECTED" in prompts[1]
    assert out.changed_ids == [] and "a2" in out.reverted and out.gap_list == ["Tableau"]
