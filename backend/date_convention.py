"""Shared parsing of the wildly mixed date strings in extracted records.

Records reaching this pipeline print dates in every shape: "05 Jan 2026",
"02-Jan-2020, 03:26 PM", "04-07-2019", "09/11/2025". The slash-separated day
and month digits are ambiguous, and which reading a module picks silently
changes clinical chronology: trend direction, which visits are "consecutive",
which documents share a date, and which treatment windows overlap.

The convention is therefore inferred from the record itself (see
`risk_timeline.py`, where this logic originated): if any date in the record
has a first component above 12 ("14/10/2023"), the record is day-first and
every ambigous date in it is read that way. The default when nothing
disambiguates is day-first, the majority convention outside the US (this
deployment is Sri Lanka-first, where dd/mm/yyyy is the norm).

Before this module existed, each feature parsed independently with
dateutil's month-first default, so the SAME record could be ordered one way
for the timeline and the opposite way for treatment windows. Every module
that reads clinical document dates goes through the helpers here so the
whole product agrees on the same day.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional, Sequence

from dateutil import parser as dateutil_parser


# YYYY-MM-DD (ISO) is unambiguous, but dateutil still applies `dayfirst` to
# it and reads "2025-11-09" as 11 September. ISO-looking strings therefore
# take a dedicated path that never applies the record's day/month convention.
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})")

_SLASH_DATE_RE = re.compile(r"\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*\d{2,4}")


def is_iso_date(text: Any) -> bool:
    """True when the string starts with an unambiguous YYYY-MM-DD date."""
    return isinstance(text, str) and _ISO_DATE_RE.match(text) is not None


def infer_dayfirst(date_strings: Sequence[Any]) -> bool:
    """
    Whether this record writes dates day-first, inferred from the record.

    A single unambiguous date settles it for all the ambiguous ones:
    "14/10/2023" can only be day-first, so "09/11/2025" in the same record is
    9 November, not 11 September. Guessing this wrong shifts a treatment
    window by months and silently changes which readings come "later".
    """
    for raw in date_strings:
        if not isinstance(raw, str):
            continue
        match = _SLASH_DATE_RE.match(raw)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 and second <= 12:
            return True
        if second > 12 and first <= 12:
            return False
    return True  # day-first is the majority convention outside the US


def parse_mixed_datetime(raw: Any, dayfirst: bool = True) -> Optional[datetime]:
    """Parse one clinical date/datetime string, or None when unreadable.

    ISO-8601 year-first strings ("2025-11-09", "2026-01-05T13:40:00Z") are
    always read year-first; everything else uses dateutil's fuzzy parser with
    the record's day-first/month-first convention. Time components present in
    the string are preserved; timezone offsets are left attached (callers
    that sort normalize them explicitly).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        if _ISO_DATE_RE.match(text):
            return dateutil_parser.parse(text, fuzzy=True, yearfirst=True, dayfirst=False)
        return dateutil_parser.parse(text, fuzzy=True, dayfirst=dayfirst)
    except (ValueError, OverflowError, TypeError):
        return None


_DATE_PLACEHOLDER_RE = re.compile(r"[xX?*_]|\byyyy\b", re.IGNORECASE)
_PARTIAL_DATE_RE = re.compile(r"^\s*(?:\d{4}|\d{4}[-/.]\d{1,2})\s*$")
_NON_DATE_MARKERS = {"unknown", "null", "none", "n/a", "na", "not available", "undated"}


def sanitize_clinical_date(raw: Any) -> Optional[str]:
    """Admission gate for model-extracted clinical dates.

    Keeps complete dates in their source representation (including full
    locale-specific dates), but rejects placeholders, partial dates, malformed
    values and implausible years before they enter the durable record. Ambiguous
    full numeric dates are retained because the record-wide convention resolver
    interprets them consistently downstream.
    """
    if raw is None:
        return None
    if isinstance(raw, (date, datetime)):
        return raw.date().isoformat() if isinstance(raw, datetime) else raw.isoformat()
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or text.lower() in _NON_DATE_MARKERS:
        return None
    if _DATE_PLACEHOLDER_RE.search(text) or _PARTIAL_DATE_RE.match(text):
        return None
    # A complete all-numeric date is still unsafe when both day/month fields
    # are <=12: there is no evidence whether 03/11 means March 11 or 3 November.
    # The shared parser remains available for legacy records, but new AI output
    # is admitted only when this ordering is unambiguous.
    numeric = _SLASH_DATE_RE.fullmatch(text)
    if numeric:
        first, second = int(numeric.group(1)), int(numeric.group(2))
        if first <= 12 and second <= 12:
            return None
    parsed = parse_mixed_datetime(text)
    if parsed is None or not 1900 <= parsed.year <= 2100:
        return None
    # Require evidence of day, month and year in the source, not values that
    # dateutil could fill from today's date.
    digit_groups = re.findall(r"\d+", text)
    has_month_word = bool(re.search(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        text, re.IGNORECASE,
    ))
    if len(digit_groups) < (2 if has_month_word else 3):
        return None
    return text


def parse_mixed_date(raw: Any, dayfirst: bool = True) -> Optional[date]:
    """Calendar-date variant of parse_mixed_datetime (drops time/tz)."""
    parsed = parse_mixed_datetime(raw, dayfirst=dayfirst)
    return parsed.date() if parsed is not None else None
