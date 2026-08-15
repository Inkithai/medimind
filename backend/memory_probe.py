"""
Process memory probe (RSS) used to make container OOM kills diagnosable.

MediMind runs on small containers (e.g. Render's 512 MB free web service).
When the process is killed by the platform there is no Python traceback —
the log simply stops. The only way to see *where* memory grew is to emit
resident-set-size (RSS) samples around the known-heavy stages (embedding
model load, chunk embedding, vector upsert).

This module is deliberately dependency-free:
  * Linux: reads /proc/self/statm (cheap, no psutil required).
  * Other platforms: falls back to resource.getrusage(ru_maxrss).
  * If neither works, rss_mb() returns None and logging degrades to a
    no-op suffix instead of raising.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

_PAGE_SIZE = 4096
try:  # pragma: no cover - platform dependent
    _PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
except (AttributeError, ValueError, OSError):  # pragma: no cover
    pass


def rss_mb() -> Optional[float]:
    """Current resident set size in MB, or None when unavailable."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as handle:
            fields = handle.read().split()
        return round(int(fields[1]) * _PAGE_SIZE / (1024 * 1024), 1)
    except Exception:
        pass
    try:  # pragma: no cover - non-Linux fallback
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux reports kilobytes.
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(peak / divisor, 1)
    except Exception:  # pragma: no cover
        return None


def log_rss(logger: logging.Logger, stage: str, **fields: Any) -> Optional[float]:
    """Log one RSS sample for `stage` and return the measured value.

    Never raises: memory instrumentation must not be able to break the
    pipeline it is instrumenting.
    """
    try:
        current = rss_mb()
        extra = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info(
            "memory: stage=%s rss_mb=%s%s",
            stage,
            "unknown" if current is None else current,
            f" {extra}" if extra else "",
        )
        return current
    except Exception:  # pragma: no cover - defensive
        return None
