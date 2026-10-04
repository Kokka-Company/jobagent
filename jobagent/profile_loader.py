"""Load the candidate's profile files into typed models."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .config import settings
from .models import ResumeContent


def load_resume(path: Optional[Path] = None) -> ResumeContent:
    path = path or (settings.profile_dir / "resume_content.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Resume content not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ResumeContent.model_validate(data)


def load_standard_answers(path: Optional[Path] = None) -> dict:
    path = path or (settings.profile_dir / "standard_answers.yaml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_search_config(path: Optional[Path] = None) -> dict:
    """Discovery targets, filters and companies (profile/search.yaml)."""
    path = path or (settings.profile_dir / "search.yaml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
