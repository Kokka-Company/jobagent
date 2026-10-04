"""ATS adapters, keyed by the name :func:`jobagent.apply.ats_detect.detect_ats` returns."""
from __future__ import annotations

from typing import Optional

from ..base import BaseAdapter
from .greenhouse import GreenhouseAdapter

_REGISTRY: dict[str, type[BaseAdapter]] = {
    "greenhouse": GreenhouseAdapter,
}


def get_adapter(ats: str) -> Optional[BaseAdapter]:
    """Instantiate the adapter for *ats*, or None if none is implemented yet."""
    cls = _REGISTRY.get(ats)
    return cls() if cls else None


def supported() -> list[str]:
    return sorted(_REGISTRY)
