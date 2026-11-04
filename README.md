# jobagent

Tailor one master résumé to any job posting (truthfully), track applications, and
— later — semi-automate the application forms and outreach. Feed it a **posting URL**
and your **master résumé content**; it scrapes the JD, mirrors its language into your
*genuine* experience, and renders a clean ATS-friendly PDF.

## Status

| Module | What it does | State |
|--------|--------------|-------|
| **0 — Discovery** | Poll Greenhouse/Lever/Ashby boards from `search.yaml` → title/location/age filters → dedup → queue | ✅ |
| **0 — Evaluation** | Hard stops → JD-only requirements → evidence match → weighted 1–5 score + apply/consider/skip | ✅ |
| **A — Résumé tailoring** | URL → JD (ATS API / JSON-LD / LLM) → truthful rewrite → **validated** → LaTeX → PDF + gap report | ✅ |
| **B — Application filler** | Playwright fills Greenhouse forms; dry-run default; blocks on captcha/attestations | 🟡 Greenhouse only |
| **C — Outreach** | Company email-pattern DB + Hunter.io enrichment + drafted networking emails | ⏳ Phase 3 |

## Setup

```bash
cd jobagent
python3 -m pip install --user -e .        # or: pip install --user <deps in pyproject>
cp .env.example .env                       # then add your ANTHROPIC_API_KEY
```

A `jobagent` launcher is installed at `~/.local/bin/jobagent` (ensure that's on your PATH).
You can always run `python3 -m jobagent` from the project directory instead.

**LaTeX engine:** `tectonic` (self-contained) is already installed at `~/.local/bin/tectonic`.
Alternatively any `pdflatex` on PATH works.

Verify everything:

```bash
jobagent doctor
```

## Your profile (edit once)

- `jobagent/profile/resume_content.yaml` — your résumé as structured data (each bullet has a
  stable `id`). **This is your master; tailoring never edits it in place** — it renders a tailored
  copy per job.
- `jobagent/profile/resume.tex.j2` — the LaTeX template (formatting). Swap in your own design;
  keep it single-column for ATS parsing.
- `jobagent/profile/standard_answers.yaml` — the recurring application questions (work auth,
  sponsorship, EEO, salary…) for Module B.

> Migrating from an existing `.tex`? Move the *content* (bullets, roles) into
> `resume_content.yaml` and the *formatting* into `resume.tex.j2`. That split is what lets
> tailoring edit data and re-render cleanly instead of hacking raw LaTeX.

## Usage

```bash
jobagent scan                 # poll the boards in profile/search.yaml, queue new in-scope roles
jobagent triage --limit 10    # score queued roles (hard stops cost no LLM call)
jobagent jobs                 # ranked shortlist (score ≥ 3.5); --show <url> for the full breakdown
jobagent evaluate <url>       # score any single posting
jobagent tailor <url>         # tailored résumé PDF for a role worth applying to
jobagent apply <url>          # dry-run fill in a visible browser (Greenhouse)
jobagent status               # tracked applications
```

### Discovery & evaluation

`profile/search.yaml` lists the companies to watch (`ats` + `board` slug from the job-board
URL), title/location/age filters, deal-breakers and your **targets** (the kinds of role you want).
Every posting `scan` sees is stored once — filtered ones keep their reason
(`sqlite3 data/jobagent.db "select title, reason from jobs where status='filtered'"`).

`evaluate`/`triage` score fit in stages, cheapest first:

1. **Hard stops** from the JD text — no sponsorship when you need it, clearance you don't hold,
   required years far above yours (years under "preferred" don't count). Hit → `skip`, no LLM call.
2. **Requirements from the JD alone** — the model doesn't see your résumé yet, so importance
   isn't bent toward what you have. A `critical`/`high` claim without a verbatim JD quote is demoted.
3. **Evidence match** — each requirement is `stated` (must cite a real bullet id or skill),
   `inferred`, or `none`; plus 1–5 dimensions: CV match, North Star (your targets), level, comp.
4. **Score in code** — weighted mean (40/30/15/15), capped at 3.4 if any critical requirement
   is unmet or the role matches none of your targets. ≥4.0 **apply** · ≥3.5 **consider** · else **skip**.

`tailor` writes to `data/generated/<Company>_<Title>/`:
- `resume.pdf` — the tailored résumé
- `resume.tex` — its source
- `report.json` — extracted keywords, which bullets changed, and the **gap list**

### Truthfulness is enforced, not just requested

After the rewrite, code checks every changed bullet: no number that wasn't in the original,
no JD skill/tool that appears nowhere in your master résumé, no clichés or assistant leakage.
Failures trigger one fresh retry with the problems listed; anything still failing is **reverted to
your original text** and listed under `reverted_by_validation` in `report.json`.

### The gap list matters

The rewrite step will **never invent skills**. Anything the posting wants that your résumé
doesn't legitimately support is reported as a *gap* rather than fabricated. Review it — mirror
the JD's language for what's genuinely yours; don't claim the rest.

## Testing

```bash
python3 -m pytest tests/ -q        # offline unit tests (no API key needed)
```

## Roadmap (from a survey of ApplyPilot, career-ops, Auto_job_applier_linkedIn & ~40 other repos)

- **Learned answer bank** — persist every new form question + your answer (with provenance) and
  reuse it; LLM-suggested answers for unknown fields require your confirmation.
- **Lever / Ashby adapters**, then Workday (custom listbox widgets, multi-page) — deterministic
  first, with a Claude + Playwright MCP fallback that stops before submit.
- **Feed the evaluation into tailoring** — emphasize bullets the evaluator cited as `stated`
  evidence; use the target archetype to frame the summary.
- **Cover letters** (≤250 words, verbatim proof points, banned-phrase list, "could this go to any
  company?" self-check) and **3-sentence outreach** per persona (recruiter / hiring manager / peer).
- **Inbox tracking** — classify replies; only auto-apply high-confidence rejections, never let a
  re-scan move an application backwards.
- **STAR+R story bank** for interview prep, built from evaluated gaps.

Deliberately *not* adopted: captcha-solving services, auto-creating ATS accounts, LinkedIn
automation (ToS / account-ban risk), and agents answering "Yes" to skills you don't have.

## Design notes

- **Models:** Opus (`JOBAGENT_MODEL_TAILOR`) for the rewrite; Haiku (`JOBAGENT_MODEL_PARSE`)
  for cheap scraping/extraction. Override in `.env`.
- **Scraping:** cheapest first — Greenhouse/Lever/Ashby public JSON APIs (exact, no LLM), then
  schema.org JSON-LD, then static/Playwright-rendered HTML + a Haiku extraction. Closed postings
  are detected and never tailored.
- **Form matching:** whole-word aliases with per-field vetoes ("company name" ≠ your name);
  choices are matched to option text with a Yes/No polarity guard and left blank rather than
  guessed; legal attestation checkboxes are never ticked; sensitive fills (work auth, salary, EEO)
  are listed for review.
- **Module B (planned):** deterministic field adapters for the big ATSs (Greenhouse/Lever/Ashby)
  + an LLM agentic fallback for long-tail fields. `--dry-run` fills without submitting;
  auto-submit pauses and notifies you on captchas/anti-bot walls (a bot can't clear those).

## License

Copyright (C) 2026 Kokka & Company

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU General Public License](LICENSE) for more details.
