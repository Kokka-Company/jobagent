"""Offline tests for the pure logic (no network / no API key needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobagent.models import Application, ApplicationStatus, Bullet, ResumeContent, Role, TailorResult
from jobagent.tailor.render import latex_escape, render_tex, slugify
from jobagent.tailor.rewrite import apply_tailoring


def _resume():
    return ResumeContent(
        name="Ada Lovelace",
        summary="Original summary.",
        experience=[
            Role(company="Analytical Engines", title="Analyst", start="2020", end="2022",
                 bullets=[Bullet(id="a1", text="Original bullet one."),
                          Bullet(id="a2", text="Original bullet two.")]),
        ],
    )


def test_latex_escape():
    assert latex_escape("R&D 50% #1 a_b") == r"R\&D 50\% \#1 a\_b"
    assert latex_escape(None) == ""


def test_apply_tailoring_is_nondestructive():
    master = _resume()
    result = TailorResult(tailored_summary="New summary.",
                          tailored_bullets={"a1": "Rephrased bullet one."},
                          changed_ids=["a1"])
    merged = apply_tailoring(master, result)
    # master untouched
    assert master.summary == "Original summary."
    assert master.experience[0].bullets[0].text == "Original bullet one."
    # merged has the tailored text
    assert merged.summary == "New summary."
    assert merged.experience[0].bullets[0].text == "Rephrased bullet one."
    assert merged.experience[0].bullets[1].text == "Original bullet two."  # unchanged bullet preserved


def test_render_includes_tailored_text():
    tex = render_tex(_resume())
    assert r"\documentclass" in tex
    assert "Ada Lovelace" in tex
    assert "Original bullet one." in tex


def test_slugify():
    assert slugify("McKinsey & Co", "Senior Analyst") == "McKinsey_Co_Senior_Analyst"


def test_extract_json_tolerates_fences_and_prose():
    from jobagent.llm import _extract_json
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('sure, here:\n{"b": 2} done') == {"b": 2}


def _patch_settings(monkeypatch, **overrides):
    """Swap llm.settings for a frozen copy with overrides (Settings is frozen)."""
    import dataclasses
    from jobagent import llm
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, **overrides))


def test_cli_backend_builds_command_and_parses_result(monkeypatch):
    """CLI backend shells out to `claude -p` and returns the `result` field."""
    import subprocess
    from jobagent import llm

    calls = {}

    class _Proc:
        returncode = 0
        stdout = '{"result": "{\\"company\\": \\"Acme\\"}", "is_error": false}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _Proc()

    _patch_settings(monkeypatch, llm_backend="cli", claude_cli_path="/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", fake_run)

    out = llm.complete_json("extract", model="claude-haiku-4-5-20251001", system="be precise")
    assert out == {"company": "Acme"}
    # non-interactive, single-turn, tools disabled, JSON output, model + system forwarded
    cmd = calls["cmd"]
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd and "--max-turns" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--disallowed-tools") + 1] == "*"
    assert cmd[cmd.index("--append-system-prompt") + 1] == "be precise"


def test_cli_backend_surfaces_errors(monkeypatch):
    import subprocess
    from jobagent import llm

    class _Proc:
        returncode = 0
        stdout = '{"result": "boom", "is_error": true}'
        stderr = ""

    _patch_settings(monkeypatch, llm_backend="cli", claude_cli_path="/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Proc())

    with pytest.raises(RuntimeError):
        llm.complete("hi", model="m")


def test_unknown_backend_raises(monkeypatch):
    from jobagent import llm
    _patch_settings(monkeypatch, llm_backend="bogus")
    with pytest.raises(RuntimeError):
        llm.complete("hi", model="m")


def test_detect_ats_by_url():
    from jobagent.apply.ats_detect import detect_ats
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/9") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc-123") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/role") == "ashby"
    assert detect_ats("https://acme.wd1.myworkdayjobs.com/careers/job/x") == "workday"
    assert detect_ats("https://acme.com/careers/role-42") == "unknown"


def test_detect_ats_by_embed_html():
    from jobagent.apply.ats_detect import detect_ats
    html = '<div id="grnhse_app"></div><script src="https://boards.greenhouse.io/embed/job_board/js"></script>'
    assert detect_ats("https://careers.acme.com/role", html) == "greenhouse"


def test_answer_book_resolves_specific_before_generic():
    from jobagent.apply.fieldmap import build_answer_book
    from jobagent.models import ResumeContent

    resume = ResumeContent(name="Ada Lovelace", email="ada@x.io", phone="+1 555 0100")
    answers = {
        "personal": {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@x.io",
                     "linkedin": "linkedin.com/in/ada"},
        "work_authorization": {"authorized_to_work": True, "requires_sponsorship": False},
        "preferences": {"willing_to_relocate": True},
        "eeo": {"gender": "Decline to self-identify"},
    }
    book = build_answer_book(resume, answers)

    # "First Name" must beat the generic "name" alias
    assert book.resolve("First Name").key == "first_name"
    assert book.resolve("Last Name *").key == "last_name"
    assert book.resolve("Full name").key == "full_name"
    assert book.resolve("Email Address").value == "ada@x.io"
    # Yes/No choice fields carry is_choice and a normalized Yes/No value
    spons = book.resolve("Do you now or will you require visa sponsorship?")
    assert spons.key == "requires_sponsorship" and spons.value == "No" and spons.is_choice
    auth = book.resolve("Are you legally authorized to work in the US?")
    assert auth.value == "Yes"
    assert book.resolve("Are you willing to relocate?").value == "Yes"
    # Unknown / blank fields resolve to None
    assert book.resolve("What is your favorite color?") is None
    assert book.resolve("") is None


def test_adapter_registry():
    from jobagent.apply.adapters import get_adapter, supported
    assert "greenhouse" in supported()
    assert get_adapter("greenhouse").name == "greenhouse"
    assert get_adapter("workday") is None


def test_db_roundtrip(tmp_path):
    from jobagent.store import db
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    app_id = db.upsert_application(
        Application(job_url="http://x/1", company="Acme", title="PM",
                    status=ApplicationStatus.DRAFT), db_path=dbp)
    assert app_id > 0
    # upsert again with same url updates, not duplicates
    db.upsert_application(
        Application(job_url="http://x/1", company="Acme", title="PM",
                    status=ApplicationStatus.SUBMITTED), db_path=dbp)
    rows = db.list_applications(dbp)
    assert len(rows) == 1
    assert rows[0].status == ApplicationStatus.SUBMITTED
