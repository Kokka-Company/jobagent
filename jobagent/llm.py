"""Single-turn LLM completions behind one ``complete()`` interface.

Two interchangeable backends, selected by ``settings.llm_backend``:

* ``"cli"`` (default) — shells out to the Claude Code CLI (``claude -p``), reusing
  this machine's existing Claude auth. No ANTHROPIC_API_KEY required. Tools are
  disabled and turns capped so it behaves as a pure one-shot text transform.
* ``"api"`` — calls the Anthropic Messages API directly with ANTHROPIC_API_KEY.

Everything else in the package calls ``complete`` / ``complete_json`` and is
agnostic to which backend runs.
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from .config import settings

# ------------------------------------------------------------------ API backend
_client = None  # lazily-constructed anthropic.Anthropic


def _api_client():
    global _client
    if _client is None:
        from anthropic import Anthropic  # imported lazily so the CLI backend needs no SDK

        _client = Anthropic(api_key=settings.require_anthropic())
    return _client


def _complete_api(prompt: str, *, model: str, system: str, max_tokens: int,
                  temperature: float) -> str:
    msg = _api_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system or "You are a precise assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in msg.content if block.type == "text").strip()


# ------------------------------------------------------------------ CLI backend
def _complete_cli(prompt: str, *, model: str, system: str, max_tokens: int,
                  temperature: float) -> str:
    """Run one non-interactive `claude -p` turn and return its text result.

    ``max_tokens``/``temperature`` are accepted for interface parity but not
    forwarded — the CLI does not expose them per-call.
    """
    cmd = [
        settings.require_claude_cli(),
        "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--max-turns", "1",
        # Keep it a pure text transform: no tools, no MCP, no wandering.
        "--disallowed-tools", "*",
    ]
    if system:
        cmd += ["--append-system-prompt", system]
    try:
        proc = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            timeout=settings.claude_cli_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude CLI timed out after {settings.claude_cli_timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude CLI returned non-JSON output: {proc.stdout[:500]!r}") from exc
    if payload.get("is_error"):
        raise RuntimeError(f"claude CLI reported an error: {payload.get('result', payload)!r}")
    return str(payload.get("result", "")).strip()


# ------------------------------------------------------------------ public API
def complete(prompt: str, *, model: str, system: str = "", max_tokens: int = 2000,
             temperature: float = 0.2) -> str:
    """Return the text of a single-turn completion via the configured backend."""
    backend = settings.llm_backend
    if backend == "cli":
        return _complete_cli(prompt, model=model, system=system,
                             max_tokens=max_tokens, temperature=temperature)
    if backend == "api":
        return _complete_api(prompt, model=model, system=system,
                             max_tokens=max_tokens, temperature=temperature)
    raise RuntimeError(
        f"Unknown JOBAGENT_LLM_BACKEND={backend!r}. Use 'cli' (default) or 'api'."
    )


def complete_json(prompt: str, *, model: str, system: str = "", max_tokens: int = 2000) -> dict:
    """Complete and parse a JSON object, tolerating stray prose or ```json fences."""
    raw = complete(prompt, model=model, system=system, max_tokens=max_tokens, temperature=0)
    return _extract_json(raw)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)
