"""
openFDA reference adapter — FDA Structured Product Labels (SPL)
================================================================
Fills the reference-graph slot that evidence_grading.py documents as empty.

THE GAP
-------
``evidence_grading.py`` grades every safety finding as ``deterministic``
(computed from the patient's own records), ``reference_graph`` (backed by an
ingested reference source), or ``model_knowledge`` (the language model's own
recall, capped at 0.6). Its docstring states plainly that MediMind ships no
reference graph for drug labels today, so every interaction / allergy finding
the model asserts from memory grades as unverified and gets capped.

openFDA's ``/drug/label.json`` endpoint serves the FDA's Structured Product
Labels — the SAME text a US pharmacist would consult — including the
``drug_interactions``, ``contraindications``, ``boxed_warning`` and
``warnings_and_cautions`` sections. This module makes that text citable, so a
finding like "Fluconazole inhibits CYP2C9, raising montelukast levels" can
carry a real citation when the fluconazole label actually names montelukast,
instead of being capped as model recall.

DISCIPLINE (what this module will NOT do)
-----------------------------------------
* A label mention CORROBORATES a finding — it never CREATES one. This module
  returns a citation only when a label for one of the finding's drugs names
  ANOTHER drug in the finding, inside an interaction-relevant section. It
  never synthesizes new rules into drug_interactions.py, and it never turns
  free label text into a finding the pipeline didn't already produce.
* ABSENCE IS NOT EVIDENCE OF SAFETY. openFDA is US-market data; a Sri Lankan
  brand that isn't there is simply not matched, and a finding without a
  citation stays graded exactly as it was (model_knowledge). A miss must
  never render as "no interaction found in FDA data" — this module returns
  ``None`` on a miss, never a reassuring negative.
* The quote is always VERBATIM. The citation carries the label's own sentence
  so a reader can check the context; nothing is paraphrased into a stronger
  claim than the label makes.

MECHANICS
---------
* Adapter, not inline calls — mirrors care/providers/osm.py: ``urllib.request``
  (no new dependency), a thread-safe TTL cache, per-request timeout, and a
  retryable error type. Every failure is fail-open: a fetch problem degrades
  the grade (finding stays model_knowledge), it never blocks an upload.
* Cache-first grading. ``openfda_claim_reference`` reads ONLY from the
  in-process cache — it never performs network I/O during the grading loop.
  The cache is warmed by ``prefetch_labels`` (called from the record/upload
  path, and callable from a scheduler to move the cost off the request path
  entirely). Labels change slowly, so the default TTL is 30 days.
* Keyed by ingredient. A workspace has a handful of distinct ingredients, so
  the cache is keyed by normalized INN, not by finding.

Env:
    OPENFDA_API_KEY        free openFDA key (https://open.fda.gov/apis/). The
                           module stays dormant without one, to avoid burning
                           the shared anonymous quota (~1,000 requests/day).
    OPENFDA_BASE_URL       default https://api.fda.gov
    OPENFDA_HTTP_TIMEOUT   per-request timeout seconds (default 5)
    OPENFDA_LABEL_CACHE_TTL seconds to keep a label cached (default 30 days)
    OPENFDA_RECALL_CACHE_TTL seconds to keep recall records cached (7 days)
    OPENFDA_NDC_CACHE_TTL  seconds to keep NDC entries cached (30 days)
    OPENFDA_MAX_LABELS_PER_RECORD  cap on ingredients fetched per record
    OPENFDA_PREFETCH_WORKERS       concurrent fetches during a warm (default 4)
    OPENFDA_RECALL_LIMIT   recall records fetched per ingredient (default 10)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("openfda_reference")

OPENFDA_BASE_URL = os.environ.get("OPENFDA_BASE_URL", "https://api.fda.gov").rstrip("/")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("OPENFDA_HTTP_TIMEOUT", "5"))
CACHE_TTL_SECONDS = float(os.environ.get("OPENFDA_LABEL_CACHE_TTL", str(30 * 24 * 3600)))
MAX_LABELS_PER_RECORD = int(os.environ.get("OPENFDA_MAX_LABELS_PER_RECORD", "40"))
PREFETCH_WORKERS = max(1, int(os.environ.get("OPENFDA_PREFETCH_WORKERS", "4")))

# SPL sections that make a claim about another drug. Order matters: a
# drug_interactions hit is the strongest corroboration, so it is searched
# first. contraindications / boxed_warning / warnings_and_cautions are
# included because the same "this drug interacts with X" claim frequently
# lives there instead.
LABEL_SECTIONS = (
    "drug_interactions",
    "contraindications",
    "boxed_warning",
    "warnings_and_cautions",
)

# The two openFDA fields most likely to hold the English INN. Searched in
# order; a clean (HTTP 200) empty answer on the first field falls through to
# the second, and only a transport failure stops the lookup.
_SEARCH_FIELDS = ("openfda.generic_name", "openfda.substance_name")

# Transient statuses worth one retry. Other 4xx responses mean the query
# itself was rejected, so retrying them just burns quota.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

USER_AGENT = os.environ.get(
    "OPENFDA_USER_AGENT",
    "MediMind/1.0 (openFDA label reference; https://github.com/Inkithai/medimind)",
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# Word-boundary match for an INN that may itself contain hyphens/spaces.
# Lookarounds on alphanumerics (rather than \b) keep "sodium oxybate" from
# matching inside "oxybatesomething" while still matching as a token. Kept as
# a format string so the escaped name can be interpolated per lookup.
_NAME_BOUNDARY = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])"


class OpenFdaUnavailableError(RuntimeError):
    """The openFDA endpoint failed (network, rate-limit, timeout).

    ``retryable`` marks transient failures (429/5xx/timeouts) as opposed to
    permanent ones (bad request). Everything in this module treats the error
    fail-open: it logs and moves on, and the finding simply goes uncited.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class _TTLCache:
    """Small thread-safe in-process cache, same shape as the OSM adapter's.

    Labels are slow-moving documents, so identical lookups must not be
    re-queried — for quota reasons and for latency. ttl <= 0 disables caching
    (used by tests to get a fresh cache per call).
    """

    def __init__(self, ttl_seconds: float, max_entries: int = 2048) -> None:
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._store: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        if self.ttl_seconds <= 0:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._store) >= self.max_entries:
                self._evict()
            self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._store.items() if expires_at <= now]
        for key in expired:
            self._store.pop(key, None)
        while len(self._store) >= self.max_entries:
            self._store.pop(next(iter(self._store)))


_LABEL_CACHE = _TTLCache(CACHE_TTL_SECONDS)
_MISSING = object()  # cached "no label on openFDA", distinct from "not looked up"


def _env_flag_disabled() -> bool:
    return os.environ.get("OPENFDA_ENABLED", "").strip().lower() in {"0", "false", "no", "off"}


def _api_key() -> str:
    return (os.environ.get("OPENFDA_API_KEY") or "").strip()


def _first(values: Any) -> str:
    """First non-empty string element of a list-or-scalar openFDA field."""
    if isinstance(values, list):
        for value in values:
            if str(value).strip():
                return str(value).strip()
        return ""
    return str(values or "").strip()


def is_configured() -> bool:
    """True when openFDA lookups are allowed. Without a key the module stays
    dormant rather than burn the shared anonymous quota, and findings keep
    grading exactly as before (model_knowledge)."""
    if _env_flag_disabled():
        return False
    key = _api_key()
    return bool(key) and not key.lower().startswith("your")


def _base_ingredient(name: Any) -> str:
    """Normalize a drug name the same way the rest of the pipeline does, so a
    label cached under 'warfarin' matches a finding naming 'Warfarin sodium'.
    Lazy import mirrors reference_library.py and avoids import-order issues."""
    from document_dedup import _base_ingredient as _bi

    return _bi(str(name or ""))


def _search_url(ingredient: str, field: str) -> str:
    """openFDA search URL for one ingredient. The quotes around the value are
    part of openFDA's exact-phrase syntax; urlencode percent-encodes them."""
    params = {"search": f'{field}:"{ingredient}"', "limit": "1"}
    key = _api_key()
    if key:
        params["api_key"] = key
    return OPENFDA_BASE_URL + "/drug/label.json?" + urllib.parse.urlencode(params)


def _get_json(url: str) -> Any:
    """Single HTTP attempt. Transport failures surface as
    OpenFdaUnavailableError so callers can distinguish them from a clean
    'no results' answer (which must be cacheable as a definitive miss)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise OpenFdaUnavailableError(
            f"openFDA returned HTTP {exc.code}.", retryable=exc.code in _RETRYABLE_STATUS
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OpenFdaUnavailableError(f"openFDA unreachable: {exc}", retryable=True) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenFdaUnavailableError(
            "openFDA returned an unreadable response.", retryable=True
        ) from exc


def _format_openfda_date(raw: Any) -> Optional[str]:
    """openFDA dates (effective_time, recall_initiation_date, ...) are
    YYYYMMDD; render them ISO for display."""
    if raw is None:
        return None
    text = str(raw).strip()
    match = re.match(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return text[:10] or None


def _shape_label(result: Dict[str, Any], ingredient: str) -> Dict[str, Any]:
    """Reduce one openFDA label result to the small dict the pipeline needs:
    source identity plus the interaction-relevant sections, verbatim."""
    openfda = result.get("openfda") if isinstance(result.get("openfda"), dict) else {}
    generic = openfda.get("generic_name") or []
    set_id = result.get("set_id")
    sections: Dict[str, str] = {}
    for section in LABEL_SECTIONS:
        raw = result.get(section)
        if isinstance(raw, list):
            text = "\n".join(str(item) for item in raw if isinstance(item, str))
        elif isinstance(raw, str):
            text = raw
        else:
            text = ""
        if text.strip():
            sections[section] = text.strip()
    url = ""
    if set_id:
        url = (
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid="
            + urllib.parse.quote(str(set_id))
        )
    return {
        "source": "FDA Structured Product Label (SPL)",
        "publisher": "U.S. Food and Drug Administration (FDA) via openFDA",
        "display_name": str(generic[0]) if generic else str(ingredient),
        "generic_name": [str(g) for g in generic],
        "set_id": set_id,
        "effective_time": _format_openfda_date(result.get("effective_time")),
        "version": result.get("version"),
        "url": url,
        "sections": sections,
    }


def _fetch_label(ingredient: str) -> Optional[Dict[str, Any]]:
    """Fetch and shape the label for one ingredient.

    Returns the shaped label on a match, ``None`` for a clean no-match, and
    raises OpenFdaUnavailableError only when every field failed at the
    transport level (so callers can avoid caching a network outage as a
    definitive "no label exists").
    """
    had_clean = False
    last_error: Optional[OpenFdaUnavailableError] = None
    for field in _SEARCH_FIELDS:
        for attempt in range(2):
            try:
                payload = _get_json(_search_url(ingredient, field))
            except OpenFdaUnavailableError as exc:
                last_error = exc
                if not exc.retryable or attempt == 1:
                    break
                time.sleep(0.2)
                continue
            had_clean = True
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list) and results and isinstance(results[0], dict):
                return _shape_label(results[0], ingredient)
            break  # clean answer (even an empty one) — try the next field
    if last_error is not None and not had_clean:
        logger.warning("openFDA label lookup failed for '%s': %s", ingredient, last_error)
        raise last_error
    return None


def lookup_label_references(
    ingredients: List[str], fetch_missing: bool = True
) -> Dict[str, Dict[str, Any]]:
    """Bulk label lookup, keyed by lowercased base ingredient.

    Reads the cache first; with ``fetch_missing`` (the default) uncached
    ingredients are fetched concurrently (bounded by MAX_LABELS_PER_RECORD
    and PREFETCH_WORKERS). A definitive miss is cached too, so an ingredient
    that genuinely has no US label is not re-queried on every upload. Callers
    that must not perform network I/O (the grading loop) pass
    ``fetch_missing=False`` and get only what is already cached.
    """
    if not is_configured():
        return {}
    normalized = sorted({_base_ingredient(i) for i in ingredients if i and str(i).strip()})
    normalized = [n for n in normalized if n][:MAX_LABELS_PER_RECORD]

    found: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for name in normalized:
        cached = _LABEL_CACHE.get(name)
        if cached is _MISSING:
            continue
        if isinstance(cached, dict):
            found[name] = cached
        else:
            missing.append(name)

    if not missing or not fetch_missing:
        return found

    def _resolve(name: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        try:
            label = _fetch_label(name)
        except OpenFdaUnavailableError:
            # A transport failure is NOT a definitive miss — leave it uncached
            # so the next record retries, and this finding just stays uncited.
            return name, None
        if label is None:
            _LABEL_CACHE.set(name, _MISSING)
        else:
            _LABEL_CACHE.set(name, label)
        return name, label

    workers = min(PREFETCH_WORKERS, len(missing))
    if workers <= 1:
        for name in missing:
            _name, label = _resolve(name)
            if label is not None:
                found[_name] = label
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="openfda") as pool:
            for name, label in pool.map(_resolve, missing):
                if label is not None:
                    found[name] = label

    if found:
        logger.info(
            "openFDA label lookup: %d/%d ingredient(s) matched",
            len(found),
            len(normalized),
        )
    return found


def prefetch_labels(ingredients: List[str]) -> Dict[str, Dict[str, Any]]:
    """Warm the label cache for a set of ingredients.

    Called from the record/upload path before the safety cross-check so the
    grading loop reads a warm cache, and equally callable from a scheduler
    (with the workspace's known ingredient set) to move the fetch cost off
    the request path entirely. Fail-open: returns whatever it could fetch.
    """
    return lookup_label_references(ingredients, fetch_missing=True)


def _sentences_mentioning(text: str, name: str) -> List[str]:
    """Verbatim sentences of `text` that name `name`, up to three. The quote
    is what a reader sees in the citation, so it must be the label's own
    wording, not a paraphrase."""
    pattern = re.compile(_NAME_BOUNDARY % re.escape(name))
    found: List[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        stripped = sentence.strip()
        if not stripped:
            continue
        if pattern.search(stripped.casefold()):
            found.append(stripped[:400])
            if len(found) >= 3:
                break
    return found


def label_mentions_ingredient(label: Dict[str, Any], other: str) -> List[Dict[str, str]]:
    """Every interaction-relevant section of `label` that names `other`,
    as {section, quote} pairs. A label that never names the drug returns [] —
    the corroboration is simply absent, which says nothing about safety."""
    name = _base_ingredient(other)
    if not name:
        return []
    hits: List[Dict[str, str]] = []
    for section in LABEL_SECTIONS:
        text = (label.get("sections") or {}).get(section)
        if not text:
            continue
        for quote in _sentences_mentioning(text, name):
            hits.append({"section": section, "quote": quote})
    return hits


def openfda_claim_reference(
    finding: Dict[str, Any], labels: Optional[Dict[str, Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """The ``claim_reference`` hook for evidence grading.

    Returns a citation when the FDA label for one of the finding's drugs
    names ANOTHER drug in the finding, inside an interaction-relevant
    section — and ``None`` in every other case, including a miss, so the
    finding keeps whatever grade it would have had. Deliberately pairwise,
    like reference_library.samhsa_claim_reference: citing a label for
    something it does not say would be worse than not citing one.

    ``labels`` is optional for tests/callers that already hold a fetched set;
    when omitted the lookup is cache-only (no network during grading).
    """
    if labels is None and not is_configured():
        return None

    names = [str(n) for n in (finding.get("medications_involved") or []) if str(n).strip()]
    if finding.get("medication"):
        names.append(str(finding["medication"]))
    ingredients = sorted({_base_ingredient(n) for n in names if _base_ingredient(n)})
    if len(ingredients) < 2:
        return None

    if labels is None:
        labels = lookup_label_references(ingredients, fetch_missing=False)

    for labelled_drug in ingredients:
        label = labels.get(labelled_drug)
        if not isinstance(label, dict):
            continue
        for mentioned in ingredients:
            if mentioned == labelled_drug:
                continue
            hits = label_mentions_ingredient(label, mentioned)
            if not hits:
                continue
            hit = hits[0]
            display = label.get("display_name") or labelled_drug
            section_label = hit["section"].replace("_", " ")
            note = (
                f"The FDA-approved label for {display} names {mentioned} in its "
                f"{section_label} section. The quoted label text is shown verbatim; "
                "it corroborates this finding and is not a substitute for a "
                "pharmacist's review."
            )
            return {
                "source": label["source"],
                "publisher": label["publisher"],
                "set_id": label.get("set_id"),
                "effective_time": label.get("effective_time"),
                "version": label.get("version"),
                "url": label.get("url"),
                "section": hit["section"],
                "quote": hit["quote"],
                "drug_label": display,
                "mentions": mentioned,
                "note": note,
            }
    return None


# ---------------------------------------------------------------------------
# Recall checking — /drug/enforcement.json
# ---------------------------------------------------------------------------
# Same fail-open, cache-first discipline as labels. Enforcement records are
# US-market; a medicine missing from them is silently left unmatched, and a
# recall match is framed as "reported in the US market — confirm your supply
# with a pharmacist", never as a certainty that the patient's own product was
# affected.

RECALL_CACHE_TTL_SECONDS = float(os.environ.get("OPENFDA_RECALL_CACHE_TTL", str(7 * 24 * 3600)))
RECALL_LIMIT = max(1, int(os.environ.get("OPENFDA_RECALL_LIMIT", "10")))

_RECALL_CACHE = _TTLCache(RECALL_CACHE_TTL_SECONDS)
_RECALL_MISSING = object()


def _recall_search_url(ingredient: str) -> str:
    params = {
        "search": f'openfda.generic_name:"{ingredient}"',
        "sort": "recall_initiation_date:desc",
        "limit": str(RECALL_LIMIT),
    }
    key = _api_key()
    if key:
        params["api_key"] = key
    return OPENFDA_BASE_URL + "/drug/enforcement.json?" + urllib.parse.urlencode(params)


def _shape_recall(result: Dict[str, Any]) -> Dict[str, Any]:
    openfda = result.get("openfda") if isinstance(result.get("openfda"), dict) else {}
    reason = result.get("reason_for_recall")
    if isinstance(reason, list):
        reason_text = "\n".join(str(item) for item in reason if isinstance(item, str))
    else:
        reason_text = str(reason or "")
    classification = str(result.get("classification") or "").strip()
    status = str(result.get("status") or "").strip()
    return {
        "source": "FDA Enforcement Report (openFDA drug/enforcement)",
        "publisher": "U.S. Food and Drug Administration (FDA) via openFDA",
        "recall_number": str(result.get("recall_number") or "").strip(),
        "classification": classification,
        "classification_rank": {
            "class i": 0,
            "class ii": 1,
            "class iii": 2,
        }.get(classification.lower(), 3),
        "status": status,
        "ongoing": status.lower() == "ongoing",
        "recall_initiation_date": _format_openfda_date(result.get("recall_initiation_date")),
        "reason_for_recall": reason_text,
        "product_description": str(result.get("product_description") or "").strip(),
        "voluntary_mandated": str(result.get("voluntary_mandated") or "").strip(),
        "state": str(result.get("state") or "").strip(),
        "generic_name": [str(g) for g in (openfda.get("generic_name") or [])],
    }


def _fetch_recalls(ingredient: str) -> List[Dict[str, Any]]:
    """Fetch recall records for one ingredient, newest first. Raises
    OpenFdaUnavailableError only on transport failure, so a clean no-match
    (empty results) is cacheable as a definitive miss."""
    payload = _get_json(_recall_search_url(ingredient))
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    shaped = [_shape_recall(r) for r in results if isinstance(r, dict)]
    # Most actionable first. Sort is stable, so the two passes compose: newest
    # first, THEN ongoing recalls (and within those, FDA class order) to the
    # front without disturbing the date order inside each group.
    shaped.sort(key=lambda r: r["recall_initiation_date"] or "", reverse=True)
    shaped.sort(key=lambda r: (not r["ongoing"], r["classification_rank"]))
    return shaped


def lookup_recall_references(
    ingredients: List[str], fetch_missing: bool = True
) -> Dict[str, List[Dict[str, Any]]]:
    """Bulk recall lookup keyed by lowercased base ingredient.

    Reads the cache first; with ``fetch_missing`` (default) uncached
    ingredients are fetched. A definitive miss is cached too. The grading /
    safety-check path passes ``fetch_missing=False`` so it never performs
    network I/O — the record path warms the cache first.
    """
    if not is_configured():
        return {}
    normalized = sorted({_base_ingredient(i) for i in ingredients if i and str(i).strip()})
    normalized = [n for n in normalized if n][:MAX_LABELS_PER_RECORD]

    found: Dict[str, List[Dict[str, Any]]] = {}
    missing: List[str] = []
    for name in normalized:
        cached = _RECALL_CACHE.get(name)
        if cached is _RECALL_MISSING:
            continue
        if isinstance(cached, list):
            found[name] = cached
        else:
            missing.append(name)

    if not missing or not fetch_missing:
        return found

    for name in missing:
        try:
            recalls = _fetch_recalls(name)
        except OpenFdaUnavailableError:
            # Transport failure is not a definitive miss — leave uncached.
            continue
        if recalls:
            _RECALL_CACHE.set(name, recalls)
            found[name] = recalls
        else:
            _RECALL_CACHE.set(name, _RECALL_MISSING)

    if found:
        logger.info(
            "openFDA recall lookup: %d/%d ingredient(s) have enforcement records",
            len(found),
            len(normalized),
        )
    return found


def prefetch_recalls(ingredients: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Warm the recall cache for a set of ingredients (record path / scheduler)."""
    return lookup_recall_references(ingredients, fetch_missing=True)


# ---------------------------------------------------------------------------
# Brand -> INN resolution — /drug/ndc.json
# ---------------------------------------------------------------------------
# The NDC directory maps a brand name to its generic_name deterministically,
# where the extractor otherwise relies on model recall (which the extraction
# prompt correctly caps below 0.9). Used by brand_resolver.py to fill empty
# ingredient lists so a Latin-script brand still takes part in cross-checking.

NDC_CACHE_TTL_SECONDS = float(os.environ.get("OPENFDA_NDC_CACHE_TTL", str(30 * 24 * 3600)))

_NDC_CACHE = _TTLCache(NDC_CACHE_TTL_SECONDS)
_NDC_MISSING = object()


def _ndc_search_url(brand: str) -> str:
    params = {"search": f'brand_name:"{brand}"', "limit": "1"}
    key = _api_key()
    if key:
        params["api_key"] = key
    return OPENFDA_BASE_URL + "/drug/ndc.json?" + urllib.parse.urlencode(params)


def _shape_ndc(result: Dict[str, Any]) -> Dict[str, Any]:
    openfda = result.get("openfda") if isinstance(result.get("openfda"), dict) else {}
    active = [
        str(item.get("name") or "").strip()
        for item in (result.get("active_ingredients") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    return {
        "source": "FDA National Drug Code (NDC) directory via openFDA",
        "publisher": "U.S. Food and Drug Administration (FDA) via openFDA",
        "brand_name": _first(openfda.get("brand_name"))
        or str(result.get("brand_name") or "").strip(),
        "generic_name": _first(openfda.get("generic_name"))
        or str(result.get("generic_name") or "").strip(),
        "product_ndc": str(result.get("product_ndc") or "").strip(),
        "labeler_name": _first(openfda.get("manufacturer_name"))
        or str(result.get("labeler_name") or "").strip(),
        "active_ingredients": active,
        "marketing_status": str(
            openfda.get("marketing_status") or result.get("marketing_status") or ""
        ).strip(),
    }


def _fetch_ndc(brand: str) -> Optional[Dict[str, Any]]:
    """Fetch the NDC entry for one brand name. Returns None for a clean
    no-match and raises OpenFdaUnavailableError on transport failure."""
    payload = _get_json(_ndc_search_url(brand))
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return _shape_ndc(results[0])
    return None


def lookup_generic_names(
    brands: List[str], fetch_missing: bool = True
) -> Dict[str, Dict[str, Any]]:
    """Bulk brand -> generic lookup, keyed by lowercased brand name.

    Same cache discipline as labels/recalls. The resolver path calls this
    during upload (network allowed); it must not run during grading.
    """
    if not is_configured():
        return {}
    normalized = sorted({str(b).strip().lower() for b in brands if str(b).strip()})
    normalized = [n for n in normalized if n][:MAX_LABELS_PER_RECORD]

    found: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for name in normalized:
        cached = _NDC_CACHE.get(name)
        if cached is _NDC_MISSING:
            continue
        if isinstance(cached, dict):
            found[name] = cached
        else:
            missing.append(name)

    if not missing or not fetch_missing:
        return found

    for name in missing:
        try:
            entry = _fetch_ndc(name)
        except OpenFdaUnavailableError:
            continue
        if entry is None:
            _NDC_CACHE.set(name, _NDC_MISSING)
        else:
            _NDC_CACHE.set(name, entry)
            found[name] = entry

    if found:
        logger.info(
            "openFDA NDC lookup: %d/%d brand name(s) resolved to a generic",
            len(found),
            len(normalized),
        )
    return found


def prefetch_ndc(brands: List[str]) -> Dict[str, Dict[str, Any]]:
    """Warm the NDC cache for a set of brand names (upload path)."""
    return lookup_generic_names(brands, fetch_missing=True)


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Offline, self-contained checks that do not need a key or network.
    label = {
        "source": "FDA Structured Product Label (SPL)",
        "publisher": "test",
        "display_name": "Fluconazole",
        "set_id": "abc",
        "effective_time": "2026-01-14",
        "version": "12",
        "url": "https://example.com/label",
        "sections": {
            "drug_interactions": (
                "Fluconazole is a strong CYP2C9 inhibitor. Concomitant use of "
                "montelukast with fluconazole may increase montelukast exposure. "
                "Monitor the patient closely."
            )
        },
    }

    assert label_mentions_ingredient(label, "montelukast")[0]["section"] == "drug_interactions"
    assert label_mentions_ingredient(label, "warfarin") == []

    cite = openfda_claim_reference(
        {"medications_involved": ["Fluconazole", "Montelukast"]},
        labels={"fluconazole": label, "montelukast": {}},
    )
    assert cite is not None, cite
    assert cite["mentions"] == "montelukast", cite
    assert cite["effective_time"] == "2026-01-14"
    assert "montelukast" in cite["quote"]
    assert cite["note"]

    # A drug the label never names is NOT cited — and the pair is not
    # fabricated into one either.
    assert (
        openfda_claim_reference(
            {"medications_involved": ["Fluconazole", "Warfarin"]},
            labels={"fluconazole": label, "warfarin": {}},
        )
        is None
    )
    # A single drug cannot corroborate a pairwise claim.
    assert (
        openfda_claim_reference({"medication": "Fluconazole"}, labels={"fluconazole": label})
        is None
    )

    # --- Recall shaping: classification rank + ISO date + ongoing sort ------
    recall = _shape_recall(
        {
            "recall_number": "D-1234-2024",
            "classification": "Class II",
            "status": "Ongoing",
            "recall_initiation_date": "20240105",
            "reason_for_recall": ["Microbial contamination", "See firm press release"],
            "openfda": {"generic_name": ["LOSARTAN POTASSIUM"]},
        }
    )
    assert recall["classification_rank"] == 1
    assert recall["recall_initiation_date"] == "2024-01-05"
    assert recall["ongoing"] is True
    assert "Microbial contamination" in recall["reason_for_recall"]

    # --- NDC shaping: brand -> generic + active ingredients -----------------
    ndc = _shape_ndc(
        {
            "product_ndc": "12345-678-90",
            "brand_name": "PANADOL",
            "generic_name": "ACETAMINOPHEN",
            "openfda": {
                "brand_name": ["PANADOL"],
                "generic_name": ["ACETAMINOPHEN"],
                "manufacturer_name": ["Test Labeler"],
                "marketing_status": "prescription",
            },
            "active_ingredients": [{"name": "ACETAMINOPHEN", "strength": "500 mg/1"}],
        }
    )
    assert ndc["generic_name"] == "ACETAMINOPHEN"
    assert ndc["product_ndc"] == "12345-678-90"
    assert ndc["active_ingredients"] == ["ACETAMINOPHEN"]

    print("openFDA label / recall / NDC reference self-checks passed.")
