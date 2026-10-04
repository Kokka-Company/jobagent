"""Render ResumeContent -> LaTeX -> PDF.

Uses Jinja2 with LaTeX-safe delimiters (so ``{}`` / ``%`` in LaTeX don't collide),
then compiles with whichever engine is available: ``tectonic`` (preferred,
self-contained) or ``pdflatex``.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import jinja2

from ..config import settings
from ..models import ResumeContent

# LaTeX special characters -> escaped forms.
_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value) -> str:
    if value is None:
        return ""
    s = str(value)
    # escape backslash first via a placeholder to avoid double-processing
    s = s.replace("\\", "")
    for ch, rep in _LATEX_SPECIAL.items():
        if ch == "\\":
            continue
        s = s.replace(ch, rep)
    return s.replace("", r"\textbackslash{}")


def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        block_start_string="((*", block_end_string="*))",
        variable_start_string="(((", variable_end_string=")))",
        comment_start_string="((=", comment_end_string="=))",
        trim_blocks=True, lstrip_blocks=True, autoescape=False,
        loader=jinja2.FileSystemLoader(str(settings.profile_dir)),
    )
    env.filters["e"] = latex_escape
    return env


def _contact_line(resume: ResumeContent) -> str:
    parts = [resume.email, resume.phone, resume.location]
    parts += [f"{k}: {v}" for k, v in resume.links.items()]
    return r" $\cdot$ ".join(latex_escape(p) for p in parts if p)


def render_tex(resume: ResumeContent) -> str:
    """Render the .tex source. All injected content is LaTeX-escaped here."""
    template = _env().get_template("resume.tex.j2")

    esc = resume.model_copy(deep=True)
    esc.name = latex_escape(resume.name)
    esc.headline = latex_escape(resume.headline)
    esc.summary = latex_escape(resume.summary)
    esc.skills = {latex_escape(k): [latex_escape(i) for i in v] for k, v in resume.skills.items()}
    for role in esc.experience:
        role.company, role.title = latex_escape(role.company), latex_escape(role.title)
        role.location = latex_escape(role.location)
        role.start, role.end = latex_escape(role.start), latex_escape(role.end)
        for b in role.bullets:
            b.text = latex_escape(b.text)
    for ed in esc.education:
        ed.school, ed.degree = latex_escape(ed.school), latex_escape(ed.degree)
        ed.location = latex_escape(ed.location)
        ed.start, ed.end = latex_escape(ed.start), latex_escape(ed.end)
        ed.details = [latex_escape(d) for d in ed.details]

    return template.render(
        name=esc.name, headline=esc.headline, summary=esc.summary,
        skills=esc.skills, experience=esc.experience, education=esc.education,
        contact_line=_contact_line(resume),
    )


def _engine() -> tuple[str, list[str]]:
    if shutil.which("tectonic"):
        return "tectonic", ["tectonic", "--outdir", "{outdir}", "{tex}"]
    if shutil.which("pdflatex"):
        return "pdflatex", ["pdflatex", "-interaction=nonstopmode", "-output-directory", "{outdir}", "{tex}"]
    raise RuntimeError(
        "No LaTeX engine found. Install 'tectonic' (recommended) or a TeX distribution "
        "providing 'pdflatex'."
    )


def compile_pdf(tex_source: str, out_pdf: Path) -> Path:
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    engine, cmd_tmpl = _engine()

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = Path(tmp) / "resume.tex"
        tex_path.write_text(tex_source, encoding="utf-8")
        cmd = [c.format(outdir=tmp, tex=str(tex_path)) for c in cmd_tmpl]
        runs = 1 if engine == "tectonic" else 2  # pdflatex needs two passes
        for _ in range(runs):
            proc = subprocess.run(cmd, capture_output=True, text=True)
        produced = Path(tmp) / "resume.pdf"
        if not produced.exists():
            tail = "\n".join(proc.stdout.splitlines()[-25:])
            raise RuntimeError(f"LaTeX compile failed ({engine}):\n{tail}")
        shutil.copy(produced, out_pdf)
    return out_pdf


def slugify(*parts: str) -> str:
    s = "_".join(p for p in parts if p)
    s = re.sub(r"[^\w\-]+", "_", s).strip("_")
    return s[:80] or "job"
