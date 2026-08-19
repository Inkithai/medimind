"""Workspace display-name policy.

A workspace is anonymous (``anon_<hex>``) by default; the user can give it a
friendly, *globally unique* name so it is recognisable in the UI and on the
health-passport header. Uniqueness is enforced case-insensitively (see the
``workspace_names.name_key`` unique index in supabase_schema.sql); this module
owns the normalisation/validation half so the API and its tests share one
definition of "a valid, comparable name".
"""

from __future__ import annotations

import re

# 1-40 chars, first char alphanumeric, then letters/digits and a small set of
# safe separators. Kept deliberately permissive (names like "Amma's records")
# but rejects control characters, leading/trailing spaces (after trimming) and
# anything that could be confused with the anonymous id.
MAX_LENGTH = 40
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'\u2019-]{0,%d}$" % (MAX_LENGTH - 1))


def normalize_workspace_name(raw: object) -> str | None:
    """Trim + collapse whitespace and validate. Returns the clean name or None."""
    if raw is None:
        return None
    cleaned = " ".join(str(raw).split())
    if not cleaned:
        return None
    if len(cleaned) > MAX_LENGTH or not _NAME_RE.match(cleaned):
        return None
    return cleaned


def name_key(name: str) -> str:
    """The case/space-insensitive comparison key enforced by the unique index."""
    return " ".join(str(name).split()).strip().lower()


def is_valid_workspace_name(raw: object) -> bool:
    return normalize_workspace_name(raw) is not None
