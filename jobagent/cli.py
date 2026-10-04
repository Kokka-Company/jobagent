"""jobagent command-line interface."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .config import settings
from .store import db

app = typer.Typer(add_completion=False, help="Tailor resumes and (semi-)automate job applications.")
console = Console()


@app.command()
def tailor(url: str = typer.Argument(..., help="Job posting URL")):
    """Scrape a posting, tailor your resume truthfully, and render a PDF."""
    from .tailor.pipeline import run_tailor

    from .scrape.ats_api import PostingClosed

    with console.status("[bold]Scraping, tailoring, rendering…", spinner="dots"):
        try:
            out = run_tailor(url)
        except PostingClosed as exc:
            console.print(f"[red]Not tailoring — posting is closed:[/] {exc}")
            raise typer.Exit(1)

    console.print(f"\n[bold green]✓ Tailored resume[/] for [bold]{out.posting.title}[/] @ {out.posting.company}")
    console.print(f"  PDF:  {out.pdf_path}")
    console.print(f"  TeX:  {out.tex_path}")
    console.print(f"  Report: {out.out_dir / 'report.json'}")

    if out.result.changed_ids:
        console.print(f"\n[bold]Rephrased bullets:[/] {', '.join(out.result.changed_ids)}")
    if out.result.reverted:
        console.print("\n[bold red]Kept original text[/] (tailored version failed truthfulness checks):")
        for k, why in out.result.reverted.items():
            console.print(f"  • {k}: {'; '.join(why)}")
    if out.result.gap_list:
        console.print("\n[bold yellow]⚠ Gaps the posting wants that your resume does NOT support:[/]")
        for g in out.result.gap_list:
            console.print(f"  • {g}")
        console.print("[dim]Review these — do not claim them unless genuinely true.[/]")
    if out.result.match_notes:
        console.print(f"\n[dim]{out.result.match_notes}[/]")


@app.command()
def apply(
    url: str = typer.Argument(..., help="Job posting / application URL"),
    dry_run: bool = typer.Option(True, "--dry-run/--live",
                                 help="Fill but never submit (default) vs. allow submit."),
    headless: bool = typer.Option(False, "--headless/--headful",
                                  help="Headful (default) lets you watch and clear captchas."),
    hold: bool = typer.Option(None, "--hold/--no-hold",
                              help="Keep the browser open to review before closing (default: on for dry runs)."),
):
    """Open the application in a browser and fill it from your stored answers.

    Run `jobagent tailor <url>` first so a tailored résumé PDF is on file for upload.
    Default is a non-submitting dry run in a visible browser.
    """
    from .apply.runner import apply as run_apply

    if hold is None:
        hold = dry_run  # review dry-run fills by default; don't block live submits
    if not dry_run:
        typer.confirm(
            f"LIVE submit to {url} — this will send a real application. Continue?",
            abort=True,
        )

    with console.status("[bold]Launching browser & filling…", spinner="dots"):
        outcome = run_apply(url, dry_run=dry_run, headless=headless, hold=hold)

    color = {
        "submitted": "green", "filled": "cyan", "blocked": "yellow",
        "error": "red", "draft": "white",
    }.get(outcome.status.value, "white")
    console.print(f"\n[bold {color}]{outcome.status.value.upper()}[/] · ATS: [bold]{outcome.ats}[/]")
    console.print(f"  {outcome.message}")
    r = outcome.report
    if r.filled:
        console.print(f"  [green]Filled[/] {len(r.filled)}: {', '.join(r.filled)}")
    console.print(f"  Résumé uploaded: {'[green]yes[/]' if r.uploaded_resume else '[yellow]no[/]'}")
    if r.needs_review:
        console.print(f"  [bold magenta]Review before submitting ({len(r.needs_review)}):[/]")
        for item in r.needs_review:
            console.print(f"    • {item}")
    if r.skipped:
        console.print(f"  [yellow]Unanswered fields ({len(r.skipped)}):[/] {', '.join(r.skipped[:12])}"
                      + (" …" if len(r.skipped) > 12 else ""))
    raise typer.Exit(code=0 if outcome.status.value in ("filled", "submitted") else 1)


def _evaluate_and_store(posting, resume, cfg, needs_sponsorship):
    from .evaluate.scorer import evaluate
    db.add_job(posting, status="new", source="manual")
    ev = evaluate(posting, resume, cfg, needs_sponsorship)
    db.save_evaluation(posting.url, ev.score, ev.decision, ev.model_dump())
    return ev


def _needs_sponsorship() -> bool:
    from .profile_loader import load_standard_answers
    return bool((load_standard_answers().get("work_authorization") or {}).get("requires_sponsorship"))


def _print_evaluation(ev) -> None:
    color = {"apply": "green", "consider": "yellow", "skip": "red"}[ev.decision]
    score = f"{ev.score:.1f}/5" if ev.score is not None else "—"
    console.print(f"\n[bold]{ev.title}[/] @ {ev.company}")
    console.print(f"  [bold {color}]{ev.decision.upper()}[/]  score {score}"
                  + (f"  · target: {ev.target}" if ev.target else ""))
    for s in ev.hard_stops:
        console.print(f"  [red]✗ hard stop:[/] {s}")
    if ev.role_summary:
        console.print(f"  [dim]{ev.role_summary}[/]")
    if ev.dimensions:
        console.print("  " + "  ".join(f"{k}={v if v is not None else '—'}" for k, v in ev.dimensions.items()))
    for c in ev.caps:
        console.print(f"  [yellow]capped:[/] {c}")
    if ev.requirements:
        t = Table("Req", "Importance", "Evidence", "Résumé", box=None, padding=(0, 1))
        mark = {"stated": "[green]stated[/]", "inferred": "[yellow]inferred[/]", "none": "[red]none[/]"}
        for r in ev.requirements:
            t.add_row(r.text[:60], r.importance, mark.get(r.evidence, r.evidence), ", ".join(r.resume_refs))
        console.print(t)
    for label, items in (("Strengths", ev.strengths), ("Gaps", ev.gaps), ("Red flags", ev.red_flags)):
        if items:
            console.print(f"  [bold]{label}:[/] " + " · ".join(items))
    if ev.rationale:
        console.print(f"  {ev.rationale}")


@app.command()
def evaluate(url: str = typer.Argument(..., help="Job posting URL")):
    """Score fit for one posting: hard stops, requirement-by-requirement evidence, 1–5 score."""
    from .profile_loader import load_resume, load_search_config
    from .scrape.ats_api import PostingClosed
    from .scrape.jd_scraper import scrape

    db.init_db()
    with console.status("[bold]Fetching & evaluating…", spinner="dots"):
        try:
            posting = scrape(url)
        except PostingClosed as exc:
            console.print(f"[red]Closed:[/] {exc}")
            raise typer.Exit(1)
        ev = _evaluate_and_store(posting, load_resume(), load_search_config(), _needs_sponsorship())
    _print_evaluation(ev)


@app.command()
def scan(company: str = typer.Option(None, "--company", "-c", help="Only scan this company/board")):
    """Poll the job boards in profile/search.yaml and queue new in-scope postings."""
    from .discover.scan import scan as run_scan

    with console.status("[bold]Scanning job boards…", spinner="dots"):
        res = run_scan(only=company)
    console.print(f"[bold green]{len(res.new)} new[/] · {res.filtered} filtered · "
                  f"{res.duplicates} duplicates · {res.already_seen} already seen")
    for name, err in res.errors.items():
        console.print(f"  [red]{name}:[/] {err}")
    if res.new:
        t = Table("Company", "Title", "Location", "Posted", "Pay")
        for p in res.new[:40]:
            t.add_row(p.company, p.title[:50], p.location[:30], p.posted_at, p.compensation[:24])
        console.print(t)
        console.print("[dim]Next: `jobagent triage` to score them.[/]")


@app.command()
def triage(limit: int = typer.Option(10, help="Max postings to evaluate this run (each costs LLM calls)")):
    """Evaluate queued postings from `scan`, newest first; hard stops cost no LLM call."""
    from .evaluate.scorer import evaluate as run_eval
    from .models import JobPosting
    from .profile_loader import load_resume, load_search_config

    db.init_db()
    rows = db.jobs_by_status("new", limit=limit)
    if not rows:
        console.print("[dim]Nothing queued. Run `jobagent scan` first.[/]")
        return
    resume, cfg, spons = load_resume(), load_search_config(), _needs_sponsorship()
    for i, r in enumerate(rows, 1):
        p = JobPosting(url=r["url"], company=r["company"], title=r["title"], location=r["location"],
                       description=r["description"], ats_type=r["ats_type"],
                       posted_at=r["posted_at"], compensation=r["compensation"], workplace=r["workplace"])
        with console.status(f"[{i}/{len(rows)}] {p.company} — {p.title}", spinner="dots"):
            try:
                ev = run_eval(p, resume, cfg, spons)
            except Exception as exc:
                console.print(f"  [red]error[/] {p.company} — {p.title}: {exc}")
                continue
        db.save_evaluation(p.url, ev.score, ev.decision, ev.model_dump())
        color = {"apply": "green", "consider": "yellow", "skip": "red"}[ev.decision]
        score = f"{ev.score:.1f}" if ev.score is not None else " — "
        why = ev.hard_stops[0] if ev.hard_stops else (ev.caps[0] if ev.caps else ev.target)
        console.print(f"  [{color}]{score} {ev.decision:<8}[/] {p.company} — {p.title[:55]}  [dim]{why}[/]")
    console.print("[dim]See the shortlist with `jobagent jobs`.[/]")


@app.command()
def jobs(min_score: float = typer.Option(3.5, help="Hide postings scoring below this"),
         show: str = typer.Option(None, help="Print the full evaluation for this URL")):
    """Ranked shortlist of evaluated postings."""
    import json as _json
    from .evaluate.scorer import Evaluation

    db.init_db()
    if show:
        for r in db.ranked_jobs(0, 10000):
            if r["url"] == show:
                _print_evaluation(Evaluation(**_json.loads(r["evaluation"])))
                return
        console.print("[red]No evaluation stored for that URL.[/]")
        raise typer.Exit(1)
    rows = db.ranked_jobs(min_score)
    if not rows:
        console.print("[dim]No evaluated postings at or above that score yet.[/]")
        return
    t = Table("Score", "Decision", "Company", "Title", "Posted", "URL")
    for r in rows:
        t.add_row(f"{r['score']:.1f}", r["decision"], r["company"], r["title"][:45], r["posted_at"], r["url"])
    console.print(t)
    console.print("[dim]Next: `jobagent tailor <url>` for the ones worth applying to.[/]")


@app.command()
def status():
    """List tracked applications."""
    db.init_db()
    rows = db.list_applications()
    if not rows:
        console.print("[dim]No applications tracked yet. Run `jobagent tailor <url>`.[/]")
        return
    table = Table("Company", "Title", "Status", "ATS", "Updated")
    for a in rows:
        table.add_row(a.company or "—", a.title or "—", a.status.value, a.ats_type,
                      a.updated_at.strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@app.command()
def doctor():
    """Check environment: LLM backend, LaTeX engine, Playwright browser."""
    import shutil

    ok = True
    console.print(f"LLM backend: [bold]{settings.llm_backend}[/]")
    if settings.llm_backend == "cli":
        if settings.claude_cli_path:
            console.print(f"  Claude CLI: [green]{settings.claude_cli_path}[/]")
        else:
            console.print("  Claude CLI: [red]not found[/] (install `claude`, set JOBAGENT_CLAUDE_PATH, "
                          "or set JOBAGENT_LLM_BACKEND=api)")
            ok = False
    elif settings.llm_backend == "api":
        console.print(f"  ANTHROPIC_API_KEY: {'[green]set[/]' if settings.anthropic_api_key else '[red]missing[/]'}")
        if not settings.anthropic_api_key:
            ok = False
    else:
        console.print(f"  [red]Unknown backend[/] — use 'cli' or 'api'.")
        ok = False
    engine = shutil.which("tectonic") or shutil.which("pdflatex")
    console.print(f"LaTeX engine: {'[green]' + engine + '[/]' if engine else '[red]none (install tectonic)[/]'}")
    ok = ok and bool(engine)
    try:
        import playwright  # noqa: F401
        console.print("Playwright: [green]installed[/]")
    except ImportError:
        console.print("Playwright: [yellow]not installed[/] (needed for JS-rendered postings & Module B)")
    if settings.chrome_path:
        console.print(f"Chrome: [green]{settings.chrome_path}[/]")
    else:
        console.print("Chrome: [yellow]not found[/] (set JOBAGENT_CHROME_PATH or `playwright install chromium`)")
    console.print(f"\nData dir: {settings.data_dir}")
    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    app()
