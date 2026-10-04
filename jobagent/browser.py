"""Shared Playwright launch configuration.

Centralizes how we start Chrome so the scraper (Module A fallback) and the
application filler (Module B) behave identically. Uses the system/extracted
Chrome via ``executable_path`` when known, else Playwright's bundled Chromium.
"""
from __future__ import annotations

from .config import settings

# --no-sandbox is required when running Chrome under many container/sandbox
# setups; harmless on a normal desktop.
DEFAULT_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def launch_kwargs(headless: bool = True) -> dict:
    kwargs: dict = {"headless": headless, "args": list(DEFAULT_ARGS)}
    if settings.chrome_path:
        kwargs["executable_path"] = settings.chrome_path
    return kwargs
