from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Runtime configuration, overridable via environment variables."""

    host: str = os.environ.get("VIZIJ_RETICO_HOST", "127.0.0.1")
    # 8765 is taken by the local claude-sc gateway in this environment; use 8770.
    port: int = int(os.environ.get("VIZIJ_RETICO_PORT", "8770"))


CONFIG = Config()
