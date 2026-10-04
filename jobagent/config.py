"""Central configuration: paths, API keys, model IDs, feature flags.

All settings resolve from environment variables (loaded from a local .env), with
sensible defaults. Import ``settings`` anywhere in the package.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = the directory that contains this package's parent (…/jobagent/).
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

# Load .env from the project root if present (never fails if absent).
load_dotenv(PROJECT_ROOT / ".env")


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _detect_chrome() -> str:
    """Locate a Chrome/Chromium executable. Env override wins; then a no-root
    extraction under ~/.local/chrome; then standard system locations."""
    override = os.getenv("JOBAGENT_CHROME_PATH")
    if override and Path(override).exists():
        return override
    candidates = [
        Path.home() / ".local/chrome/opt/google/chrome/google-chrome",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""  # fall back to Playwright's bundled Chromium if installed


def _detect_claude() -> str:
    """Locate the Claude Code CLI (used by the ``cli`` LLM backend). Env override
    wins; then PATH; then the standard per-user install location."""
    override = os.getenv("JOBAGENT_CLAUDE_PATH")
    if override and Path(override).exists():
        return override
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local/bin/claude"
    return str(local) if local.exists() else ""


@dataclass(frozen=True)
class Settings:
    # --- Paths ---
    project_root: Path = PROJECT_ROOT
    profile_dir: Path = PACKAGE_DIR / "profile"
    data_dir: Path = PROJECT_ROOT / "data"
    generated_dir: Path = PROJECT_ROOT / "data" / "generated"
    db_path: Path = PROJECT_ROOT / "data" / "jobagent.db"

    # --- LLM backend ---
    # "cli": route completions through the Claude Code CLI (`claude -p`), reusing
    #        this machine's existing Claude auth — no API key needed (default).
    # "api": call the Anthropic Messages API directly with ANTHROPIC_API_KEY.
    llm_backend: str = field(
        default_factory=lambda: os.getenv("JOBAGENT_LLM_BACKEND", "cli").strip().lower()
    )
    claude_cli_path: str = field(default_factory=_detect_claude)
    claude_cli_timeout: int = field(
        default_factory=lambda: int(os.getenv("JOBAGENT_CLAUDE_TIMEOUT", "180"))
    )

    # --- Anthropic ---
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model_tailor: str = field(default_factory=lambda: os.getenv("JOBAGENT_MODEL_TAILOR", "claude-opus-4-8"))
    model_parse: str = field(default_factory=lambda: os.getenv("JOBAGENT_MODEL_PARSE", "claude-haiku-4-5-20251001"))
    # Fit evaluation runs once per discovered job, so it defaults to a mid-tier model.
    model_evaluate: str = field(default_factory=lambda: os.getenv("JOBAGENT_MODEL_EVALUATE", "claude-sonnet-5-5"))

    # --- Module C ---
    hunter_api_key: str = field(default_factory=lambda: os.getenv("HUNTER_API_KEY", ""))

    # --- Browser (Playwright) ---
    chrome_path: str = field(default_factory=_detect_chrome)

    # --- Application filler ---
    auto_submit: bool = field(default_factory=lambda: _flag("JOBAGENT_AUTO_SUBMIT", False))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)

    def require_anthropic(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key, "
                "or use the default CLI backend (JOBAGENT_LLM_BACKEND=cli)."
            )
        return self.anthropic_api_key

    def require_claude_cli(self) -> str:
        if not self.claude_cli_path:
            raise RuntimeError(
                "Claude Code CLI (`claude`) not found. Install it, ensure it is on PATH, "
                "set JOBAGENT_CLAUDE_PATH, or switch to the API backend "
                "(JOBAGENT_LLM_BACKEND=api with ANTHROPIC_API_KEY)."
            )
        return self.claude_cli_path


settings = Settings()
