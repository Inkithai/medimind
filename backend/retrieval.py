"""
Retrieval-Augmented Q&A Layer (Phase 1)
=========================================
Sits on top of the ALREADY-EXTRACTED structured JSON produced by
medical_extractor.py — specifically the per-patient timeline returned by
build_patient_timeline(). It does NOT re-read raw documents.

Pipeline:
    patient timeline -> chunks (one per medication / lab result / clinical
    note / allergy list) -> embed each chunk's text -> store in a
    per-patient local Chroma collection -> at query time, embed the
    question, retrieve the top_k most similar chunks, and ask a chat
    model to answer strictly from that retrieved context.

Embedding provider: chat/extraction run on the active LLM_PROVIDER (groq/gemini),
but neither Groq nor Gemini offers an embeddings API. So embeddings use, in order of preference:
    1. OpenAI text-embedding-3-small, if OPENAI_API_KEY is set.
    2. Chroma's built-in local ONNX MiniLM model (all-MiniLM-L6-v2) —
       runs in-process, no API key or network calls (after a one-time
       weights download on first use).
NOTE: the two backends produce different-dimensional vectors, so after
switching backends delete ./chroma_db and re-index (or clear `chunks` table if VECTOR_STORE=supabase).

Install:
    pip install chromadb --break-system-packages

Env:
    export LLM_PROVIDER=gemini           (or groq; same provider used by medical_extractor.py)
    export GEMINI_API_KEY="AIza..."      (or GROQ_API_KEY="gsk_..." for groq)
    export OPENAI_API_KEY="sk-..."       (optional — see embedding provider above)
    export VECTOR_STORE=chroma           (or supabase — no volume, uses Supabase `chunks` table)
    export CHROMA_DIR=./chroma_db        (only for VECTOR_STORE=chroma)
"""

import os
import re
import json
import hashlib
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI, OpenAIError

from medical_extractor import client, MODEL, _completion_resilient, _chat_completion
import vector_store  # abstraction over Chroma (local) and Supabase (no volume)

logger = logging.getLogger("retrieval")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = MODEL  # reuse the same chat model configured in medical_extractor.py

# At or below this answer confidence the deterministic safety guard always
# recommends a professional. Shared with evidence_grading's model-knowledge
# cap so "low confidence" means one thing across the product.
LOW_CONFIDENCE_THRESHOLD = 0.6

# Questions about risk / interactions / allergies / dosage changes ALWAYS get
# recommend_professional_consult=true, regardless of what the answering model
# said — the prompt already tells it to, but "already told to" is not a
# control. This regex is the control.
RISK_PATTERN = re.compile(
    r"\b(safe|safety|danger|dangerous|risk|risky|interact\w*|allerg\w*|overdose|"
    r"side.?effect\w*|adverse|contraindicat\w*|harmful|toxic|stop taking|"
    r"increase|decrease|double|halve|adjust|change (?:my|the) dose|together|combine|mix|"
    r"dosage|dose)\b",
    re.IGNORECASE,
)

CHROMA_DIR = os.environ.get("CHROMA_DIR", "./chroma_db")
EMBEDDING_BATCH_SIZE = 100  # keep well under the API's per-request item limit
# VECTOR_STORE is read inside vector_store.py; we keep CHROMA_DIR for backward compat

# Groq has no embeddings endpoint. When an OpenAI key is available it
# is used ONLY for embeddings (never for chat); otherwise fall back to
# Chroma's built-in local ONNX MiniLM model, which needs no API key at all.
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if _OPENAI_API_KEY == "your-openai-api-key":
    _OPENAI_API_KEY = None
_openai_embedding_client = OpenAI(api_key=_OPENAI_API_KEY) if _OPENAI_API_KEY else None

_local_embedding_fn = None


def _get_local_embedding_function():
    """Lazily initialise Chroma's default local embedding function
    (all-MiniLM-L6-v2 via ONNX runtime). Weights download once on first
    use, then everything runs in-process — no API key required."""
    global _local_embedding_fn
    if _local_embedding_fn is None:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        _local_embedding_fn = ONNXMiniLM_L6_V2()
    return _local_embedding_fn


# ---------------------------------------------------------------------------
# 1. Chunking — turn a patient timeline into retrievable text chunks
# ---------------------------------------------------------------------------

def _chunk_id(patient_key: str, source_file: Optional[str], chunk_type: str, index: int) -> str:
    """Stable, deterministic chunk ID so re-indexing the same documents
    upserts in place instead of creating duplicates."""
    raw = f"{patient_key}|{source_file or 'unknown'}|{chunk_type}|{index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _medication_chunk_text(med: Dict[str, Any]) -> str:
    ingredients = ", ".join(med.get("ingredients") or []) or "unknown"
    duration = med.get("duration") or "not specified"

    dosage_value, dosage_unit = med.get("dosage_value"), med.get("dosage_unit")
    normalized_dose = f"{dosage_value} {dosage_unit}" if dosage_value is not None and dosage_unit else "not normalized"

    if med.get("is_as_needed"):
        normalized_freq = "as needed (PRN)"
    elif med.get("frequency_per_day") is not None:
        normalized_freq = f"{med['frequency_per_day']} time(s) per day"
    else:
        normalized_freq = "not normalized"

    return (
        f"Medication: {med.get('name', 'unknown')}. "
        f"Active ingredient(s) (normalized): {ingredients}. "
        f"Dosage as printed: {med.get('dosage', 'unknown')} "
        f"(normalized: {normalized_dose}). "
        f"Frequency as printed: {med.get('frequency', 'unknown')} "
        f"(normalized: {normalized_freq}). "
        f"Duration: {duration}. "
        f"Prescribed on {med.get('date') or 'an unknown date'} "
        f"(source: {med.get('source_file') or 'unknown file'})."
    )


def _lab_result_chunk_text(lab: Dict[str, Any]) -> str:
    unit = lab.get("unit") or ""
    ref_range = lab.get("reference_range") or "not specified"
    return (
        f"Lab result: {lab.get('test_name', 'unknown test')} = "
        f"{lab.get('value', 'unknown')}{(' ' + unit) if unit else ''} "
        f"(flag: {lab.get('flag', 'unknown')}, reference range: {ref_range}). "
        f"Recorded on {lab.get('date') or 'an unknown date'} "
        f"(source: {lab.get('source_file') or 'unknown file'})."
    )


def _clinical_note_chunk_text(visit: Dict[str, Any]) -> str:
    source_file = visit.get("_source", {}).get("file")
    return (
        f"Clinical note from visit on {visit.get('date') or 'an unknown date'} "
        f"(source: {source_file or 'unknown file'}): {visit.get('clinical_notes')}"
    )


def _allergy_chunk_text(allergies: List[str]) -> str:
    return "Known allergies: " + ", ".join(allergies) + "."


def build_chunks_from_timeline(patient_key: str, timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converts a patient timeline (the dict returned by build_patient_timeline())
    into a flat list of retrievable chunks. Each chunk is:
        {"id": str, "text": str, "metadata": {...}}

    One chunk is produced per medication entry, per lab result, per visit's
    clinical_notes (when present), and one chunk lists all known_allergies
    together. Chunk IDs are deterministic hashes so re-running this on the
    same documents upserts instead of duplicating.
    """
    chunks: List[Dict[str, Any]] = []

    for i, med in enumerate(timeline.get("medications_timeline", [])):
        chunks.append({
            "id": _chunk_id(patient_key, med.get("source_file"), "medication", i),
            "text": _medication_chunk_text(med),
            "metadata": {
                "patient_key": patient_key,
                "date": med.get("date") or "",
                "source_file": med.get("source_file") or "",
                "chunk_type": "medication",
            },
        })

    for i, lab in enumerate(timeline.get("lab_results_timeline", [])):
        chunks.append({
            "id": _chunk_id(patient_key, lab.get("source_file"), "lab_result", i),
            "text": _lab_result_chunk_text(lab),
            "metadata": {
                "patient_key": patient_key,
                "date": lab.get("date") or "",
                "source_file": lab.get("source_file") or "",
                "chunk_type": "lab_result",
            },
        })

    for i, visit in enumerate(timeline.get("visits", [])):
        if not visit.get("clinical_notes"):
            continue
        source_file = visit.get("_source", {}).get("file")
        chunks.append({
            "id": _chunk_id(patient_key, source_file, "clinical_note", i),
            "text": _clinical_note_chunk_text(visit),
            "metadata": {
                "patient_key": patient_key,
                "date": visit.get("date") or "",
                "source_file": source_file or "",
                "chunk_type": "clinical_note",
            },
        })

    allergies = timeline.get("known_allergies") or []
    if allergies:
        chunks.append({
            "id": _chunk_id(patient_key, None, "allergy", 0),
            "text": _allergy_chunk_text(allergies),
            "metadata": {
                "patient_key": patient_key,
                "date": "",
                "source_file": "",
                "chunk_type": "allergy",
            },
        })

    return chunks


# ---------------------------------------------------------------------------
# 2. Embedding + Chroma storage
# ---------------------------------------------------------------------------

def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embeds a list of strings, batching to stay under the API's
    per-request item limit. Uses OpenAI's text-embedding-3-small when
    OPENAI_API_KEY is set; otherwise Chroma's local ONNX MiniLM model
    (Groq offers no embeddings API). Raises RuntimeError with context
    if the embedding call fails (auth, rate limit, network, etc.)."""
    if not texts:
        return []

    if _openai_embedding_client is not None:
        embeddings: List[List[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start:start + EMBEDDING_BATCH_SIZE]
            try:
                response = _openai_embedding_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            except OpenAIError as e:
                raise RuntimeError(f"Embedding request failed for {len(batch)} chunk(s): {e}") from e
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    try:
        return _get_local_embedding_function()(texts)
    except Exception as e:
        raise RuntimeError(f"Local embedding failed for {len(texts)} chunk(s): {e}") from e


def _sanitize_collection_name(patient_key: str) -> str:
    """Chroma collection names must be 3-63 chars, start/end alphanumeric,
    and contain only [a-zA-Z0-9._-]. This maps an arbitrary patient_key
    (e.g. 'amit sharma') into a safe, stable collection name."""
    name = re.sub(r"[^a-z0-9._-]+", "_", patient_key.strip().lower()).strip("_.-")
    if not name:
        name = "patient"
    if not name[0].isalnum():
        name = "p" + name
    if not name[-1].isalnum():
        name = name + "0"
    while len(name) < 3:
        name += "0"
    return name[:63]


def _get_chroma_client():
    # Delegate to vector_store's lazily-imported, process-cached client.
    # (Previously this referenced `chromadb` without ever importing it —
    # `from chromadb.utils... import ONNXMiniLM_L6_V2` above only binds the
    # function name, not the package — so every Chroma-path call raised
    # "NameError: name 'chromadb' is not defined", silently degrading
    # uploads to indexed=False and 500-ing /qa.) Delegation keeps one Chroma
    # client per process and one actionable 'not installed' message.
    return vector_store.get_chroma_client()


def _get_patient_collection(patient_key: str, create: bool):
    """Fetches (or creates) the Chroma collection for one patient. Returns
    None if create=False and no collection exists yet for this patient."""
    db = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    if create:
        return db.get_or_create_collection(name=name, metadata={"patient_key": patient_key})
    try:
        return db.get_collection(name=name)
    except Exception:
        return None


def index_patient_timeline(patient_key: str, timeline: Dict[str, Any]) -> int:
    """
    Entry point for indexing: chunks a patient's timeline, embeds every
    chunk, and upserts them into that patient's local Chroma collection
    (persisted under ./chroma_db). Safe to call repeatedly on the same
    timeline — chunk IDs are deterministic, so re-indexing overwrites
    existing entries rather than duplicating them.

    Returns the number of chunks indexed. Returns 0 — WITHOUT storing
    anything — when the timeline has no retrievable content (no
    medications, lab results, clinical notes, or allergies), in which
    case callers must NOT report the patient as indexed: there is
    literally nothing for Q&A to retrieve. (Previously this returned
    None after printing "skipping indexing", which made upload callers
    log "re-indexed for Q&A" and index=True — a misleading contradiction.)
    """
    if not patient_key or not patient_key.strip():
        raise ValueError("patient_key is required and cannot be empty.")

    chunks = build_chunks_from_timeline(patient_key, timeline)
    if not chunks:
        logger.warning(
            "No indexable content found for patient '%s' — skipping indexing "
            "(nothing to retrieve for Q&A).",
            patient_key,
        )
        return 0

    embeddings = embed_texts([c["text"] for c in chunks])

    if vector_store.get_store_name() == "supabase":
        vector_store.upsert(
            patient_key,
            ids=[c["id"] for c in chunks],
            embeddings=embeddings,
            documents=[c["text"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
        )
        logger.info("Indexed %d chunk(s) for patient '%s' into supabase (supabase).", len(chunks), patient_key)
    else:
        # Chroma path (kept for backward compat with tests that mock _get_patient_collection)
        collection = _get_patient_collection(patient_key, create=True)
        collection.upsert(
            ids=[c["id"] for c in chunks],
            embeddings=embeddings,
            documents=[c["text"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
        )
        logger.info("Indexed %d chunk(s) for patient '%s' into Chroma (%s).", len(chunks), patient_key, CHROMA_DIR)
    return len(chunks)


# ---------------------------------------------------------------------------
# 3. Record vocabulary — deterministic entity matching against the patient's
#    own record. Powers conversational focus carry-over (conversation.py):
#    "what if I take it with this?" resolves against real record entities
#    even when the LLM query rewrite fails.
# ---------------------------------------------------------------------------

def build_record_vocabulary(timeline: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Every entity name that appears anywhere in this patient's timeline. Used
    to resolve conversational focus deterministically without an LLM call:
    a question can only ever be matched against drugs/tests/files the patient
    actually has on record.
    """
    medications = set()
    for med in timeline.get("medications_timeline", []) or []:
        if med.get("name"):
            medications.add(med["name"])
        for ingredient in med.get("ingredients") or []:
            if ingredient:
                medications.add(ingredient)

    lab_tests = {
        lab["test_name"]
        for lab in timeline.get("lab_results_timeline", []) or []
        if lab.get("test_name")
    }
    source_files = {
        (visit.get("_source") or {}).get("file")
        for visit in timeline.get("visits", []) or []
        if (visit.get("_source") or {}).get("file")
    }

    return {
        "medications": sorted(medications),
        "lab_tests": sorted(lab_tests),
        "source_files": sorted(f for f in source_files if f),
        "allergies": list(timeline.get("known_allergies") or []),
    }


# Words that appear inside record entity names but carry no identity on their
# own — matching a question against them alone would select half the record.
_GENERIC_TERM_WORDS = {
    "fasting", "random", "total", "free", "direct", "serum", "plasma", "blood",
    "urine", "level", "levels", "test", "tests", "count", "profile", "panel",
    "report", "ratio", "index", "pdf", "jpg", "jpeg", "png", "webp", "page",
    "tablet", "tablets", "capsule", "capsules", "oral", "injection",
}

# Below this length a term is matched whole-word only: "ALT" as a substring
# also hits "salt" and "alternative".
_SUBSTRING_SAFE_MIN_LEN = 5


def _significant_words(term: str):
    return {
        word
        for word in re.findall(r"[a-z0-9]+", term.lower())
        if len(word) >= 4 and word not in _GENERIC_TERM_WORDS
    }


def match_vocabulary(text: str, vocabulary: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """
    Deterministic entity spotting: which known medications / lab tests /
    source files does this text actually name? Matching is against a closed,
    patient-specific vocabulary, so an unrelated drug the patient isn't on
    can never be selected.

    Matches three ways, in decreasing strictness:
      * the full term appears verbatim ("metformin sr");
      * a short term appears as a whole word (so "ALT" doesn't match "salt");
      * a distinctive word of the term appears — this is what lets "my
        glucose" find the record's "Fasting Glucose". Generic qualifiers
        ("fasting", "serum", "total") are excluded from that last rule, so
        the match still has to be on something identifying.
    """
    lowered = (text or "").lower()
    if not lowered:
        return {"medications": [], "lab_tests": [], "source_files": []}

    words = set(re.findall(r"[a-z0-9]+", lowered))

    def matches(term: str) -> bool:
        lowered_term = term.lower()
        if len(lowered_term) >= _SUBSTRING_SAFE_MIN_LEN:
            if lowered_term in lowered:
                return True
        elif lowered_term in words:
            return True
        return bool(_significant_words(term) & words)

    return {
        field: [term for term in vocabulary.get(field, []) if term and matches(term)]
        for field in ("medications", "lab_tests", "source_files")
    }


def _timeline_for(patient_key: str) -> Dict[str, Any]:
    """Builds the patient's timeline from persisted documents, or {} when
    nothing is stored/unreachable. Pure-Python and cheap; used to enrich
    cited sources and to pin conversational focus into the prompt."""
    docs = _persisted_documents(patient_key)
    if not docs:
        return {}
    from medical_extractor import build_patient_timeline
    return build_patient_timeline(docs)


MAX_FOCUS_ENTRIES_PER_ENTITY = 8  # keep the pinned focus block bounded


def _render_focus_context(timeline: Dict[str, Any], focus: Dict[str, List[str]]) -> str:
    """
    Renders the conversation's current focus — the medications, lab tests and
    documents under discussion — as established facts taken directly from the
    patient's timeline. This block is appended to the retrieved context so a
    follow-up's subject is pinned into the prompt even when the embedding
    search for the rewritten query misses it. Deterministic: no model call.
    """
    if not timeline or not focus:
        return ""

    lines: List[str] = []

    meds = focus.get("medications") or []
    if meds:
        lowered = {m.lower() for m in meds}
        picked = [
            med for med in timeline.get("medications_timeline", []) or []
            if any(term in (med.get("name") or "").lower()
                   or any(term in (ing or "").lower() for ing in med.get("ingredients") or [])
                   for term in lowered)
        ][:MAX_FOCUS_ENTRIES_PER_ENTITY]
        for med in picked:
            lines.append(
                f"- Medication on file: {med.get('name') or 'unknown'} — "
                f"{med.get('dosage') or 'dose not printed'} "
                f"{med.get('frequency') or ''} "
                f"(prescribed {med.get('date') or 'undated'}, "
                f"source: {med.get('source_file') or 'unknown file'})"
            )

    tests = focus.get("lab_tests") or []
    if tests:
        lowered = {t.lower() for t in tests}
        picked = [
            lab for lab in timeline.get("lab_results_timeline", []) or []
            if any(term in (lab.get("test_name") or "").lower() for term in lowered)
        ][:MAX_FOCUS_ENTRIES_PER_ENTITY]
        for lab in picked:
            lines.append(
                f"- Lab result on file: {lab.get('test_name')} = {lab.get('value')}"
                f"{(' ' + lab.get('unit')) if lab.get('unit') else ''} "
                f"(flag: {lab.get('flag') or 'unknown'}, "
                f"recorded {lab.get('date') or 'undated'}, "
                f"source: {lab.get('source_file') or 'unknown file'})"
            )

    files = focus.get("source_files") or []
    if files:
        by_file = {
            (visit.get("_source") or {}).get("file"): visit
            for visit in timeline.get("visits", []) or []
        }
        for name in files[:MAX_FOCUS_ENTRIES_PER_ENTITY]:
            visit = by_file.get(name)
            if not visit:
                continue
            lines.append(
                f"- Document on file: {name} "
                f"(type: {visit.get('document_type') or 'unknown'}, "
                f"date: {visit.get('date') or 'undated'})"
            )

    if not lines:
        return ""
    return (
        "Entities this conversation is already about (from the patient's own "
        "records — treat these as established context for the follow-up):\n"
        + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# 4. Retrieval + Q&A
# ---------------------------------------------------------------------------

QA_SYSTEM_PROMPT = """
You are a patient-facing medical records assistant. You answer questions
using ONLY the retrieved context provided to you below — structured chunks
pulled from that patient's own extracted medical records (medications, lab
results, clinical notes, allergies).

Rules:
- Answer strictly from the retrieved context. If the context does not cover
  the question, say "I don't have enough information" rather than guessing
  or using outside medical knowledge.
- NEVER provide a diagnosis or interpret what a result "means" clinically.
- Whenever the question touches on risk, drug interactions, allergy
  conflicts, or changing/adjusting a dosage, explicitly recommend the
  patient consult a doctor or pharmacist, and set
  recommend_professional_consult to true.
- Cite the date and source_file of every chunk you rely on in "sources".
- Set cross_document to true if your answer combined facts from more than
  one source document (different source_file values), e.g. comparing a drug
  prescribed in one document with a lab result or allergy noted in another.
- Respond with STRICT JSON only, matching the required schema.

CONFIDENCE SCORING — "confidence" reflects how directly the retrieved
context answers the question, not how fluent your answer sounds:
- 0.90-1.00: the retrieved chunks state the answer directly and completely.
- 0.60-0.89: the retrieved chunks are relevant but partial, or you combined
  more than one chunk to form the answer.
- Below 0.60: the retrieved chunks are only tangentially related, or you
  are largely saying "I don't have enough information."
"""

ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "source_file": {"type": "string"},
                },
                "required": ["date", "source_file"],
                "additionalProperties": False,
            },
        },
        "cross_document": {"type": "boolean"},
        "recommend_professional_consult": {"type": "boolean"},
    },
    "required": [
        "answer",
        "confidence",
        "sources",
        "cross_document",
        "recommend_professional_consult",
    ],
    "additionalProperties": False,
}

ANSWER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "patient_qa_answer",
        "strict": True,
        "schema": ANSWER_JSON_SCHEMA,
    },
}

_NO_INFO_ANSWER = {
    "answer": "I don't have enough information — no indexed records were found for this patient yet.",
    "confidence": 0.0,
    "sources": [],
    "cross_document": False,
    "recommend_professional_consult": False,
    "low_confidence": False,
}

# Patient HAS persisted documents, but none of them contain anything the
# Q&A indexer can retrieve (no medications, lab results, clinical notes,
# or allergies). Different from _NO_INFO_ANSWER, which means "no records
# were ever uploaded" — returning the wrong one of the two is what made
# users with uploaded documents see a false "no indexed records" message.
_NO_INDEXABLE_CONTENT_ANSWER = {
    "answer": (
        "I don't have enough information — your records were found, but they "
        "contain no medications, lab results, clinical notes, or allergies for "
        "Q&A to search."
    ),
    "confidence": 0.0,
    "sources": [],
    "cross_document": False,
    "recommend_professional_consult": False,
    "low_confidence": False,
}


def _enrich_sources(sources: List[Dict[str, Any]], timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Attaches document_type and the archived document_url to each cited
    source by looking it up in the timeline. Done in code rather than asked
    of the model — a URL is exactly the kind of field a model will happily
    invent."""
    by_file: Dict[str, Dict[str, Any]] = {}
    for visit in timeline.get("visits", []) or []:
        source_file = (visit.get("_source") or {}).get("file")
        if source_file:
            by_file[source_file] = visit

    enriched = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        visit = by_file.get(source.get("source_file") or "")
        entry = dict(source)
        if visit:
            entry["document_type"] = visit.get("document_type")
            if visit.get("document_url"):
                entry["document_url"] = visit["document_url"]
        enriched.append(entry)
    return enriched


def _apply_safety_guard(result: Dict[str, Any], question: str) -> Dict[str, Any]:
    """
    Deterministic backstop for the product's stated safety promise:
    recommend a professional for risk/allergy/dosage questions OR
    low-confidence answers. The answering prompt already tells the model to
    do this, but "already told to" is not a control — this makes it one, and
    records WHY it fired in `consult_reason`.

    Never de-escalates: it can only turn recommend_professional_consult on,
    never off.
    """
    reasons: List[str] = []

    if RISK_PATTERN.search(question or ""):
        reasons.append(
            "the question involves safety, interactions, allergies, or a dosage change"
        )

    confidence = result.get("confidence")
    low_confidence = (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and confidence <= LOW_CONFIDENCE_THRESHOLD
    )
    if low_confidence:
        reasons.append(
            f"the answer's confidence is low ({confidence:.2f} at or below "
            f"{LOW_CONFIDENCE_THRESHOLD:.2f})"
        )

    result["low_confidence"] = bool(low_confidence)
    result["cross_document"] = bool(result.get("cross_document"))
    if reasons:
        result["recommend_professional_consult"] = True
        result["consult_reason"] = (
            "Please confirm this with a doctor or pharmacist, because "
            + "; ".join(dict.fromkeys(reasons))
            + "."
        )
    elif result.get("recommend_professional_consult"):
        result["consult_reason"] = (
            "Please confirm this with a doctor or pharmacist before acting on it."
        )
    return result


def _persisted_documents(patient_key: str) -> Optional[List[Dict[str, Any]]]:
    """Returns the patient's extracted documents from the persistent DB, or
    None if they can't be confirmed (unconfigured Supabase, offline test
    environment, missing `documents` table, ...). Callers treat None as
    'no documents to work from' and keep the legacy graceful behavior."""
    try:
        import db  # lazy: retrieval.py must stay importable without Supabase
        return db.load_documents(patient_key) or []
    except Exception:
        return None


def _reindex_from_persisted_documents(patient_key: str) -> Optional[int]:
    """Self-healing re-index: rebuilds the patient's vector index from the
    documents already persisted in Supabase (documents + patient_snapshots
    survive deploys/restarts, while a local Chroma store or a freshly
    migrated `chunks` table may not).

    Returns:
        int  — number of chunks indexed (0 = documents exist but contain no
               indexable content)
        None — the patient has no persisted documents (nothing to re-index)

    Raises RuntimeError (embedding/store failure) — callers surface that as
    an actionable error rather than masking it as "no records".
    """
    docs = _persisted_documents(patient_key)
    if not docs:
        return None

    from medical_extractor import build_patient_timeline
    timeline = build_patient_timeline(docs)
    return index_patient_timeline(patient_key, timeline)


def answer_question(
    patient_key: str,
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    top_k: int = 8,
    retrieval_query: Optional[str] = None,
    focus: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Answers a natural-language question about one patient, grounded only in
    that patient's already-indexed timeline chunks.

    1. Embeds the retrieval query (see retrieval_query below).
    2. Queries the patient's Chroma collection for the top_k most similar
       chunks.
    3. Builds a prompt from those chunks (each tagged with its date and
       source_file), plus chat_history and the (display) question. When
       `focus` is given, the entities under discussion are additionally
       pinned into the prompt as established facts from the timeline.
    4. Calls the chat model with a system prompt that forbids diagnosis,
       requires deferring to a professional for risk/interaction/dosage
       questions, and forces structured JSON output.
    5. Post-processes deterministically: cited sources are enriched with
       document_type/document_url from the timeline, and the safety guard
       forces recommend_professional_consult=true on risk/allergy/dosage
       questions and low-confidence answers (see _apply_safety_guard).

    retrieval_query: optional string used for embedding/Chroma retrieval
        instead of `question`. Lets a caller (e.g. conversation.py) rewrite
        an ambiguous follow-up like "was that safe?" into a fully-specified
        search query, while `question` remains the literal text shown to
        the answering LLM as "the question asked". Defaults to `question`
        when omitted, so existing single-shot callers are unaffected.
    focus: entities under discussion in this conversation (medications,
        lab_tests, source_files), carried across turns by conversation.py so
        a follow-up keeps its subject even if the rewrite/embedding misses.

    Returns the parsed JSON:
        {"answer": str, "confidence": float,
         "sources": [{"date", "source_file", "document_type"?, "document_url"?}],
         "cross_document": bool, "recommend_professional_consult": bool,
         "low_confidence": bool, "consult_reason": str?}

    Raises ValueError for a missing patient_key/question, RuntimeError if
    the embedding or chat call fails (including VectorStoreSchemaError when
    VECTOR_STORE=supabase but the `chunks` table has not been migrated).

    Empty-index self-healing: if the patient's vector index is empty but
    persisted documents exist (e.g. a local Chroma store wiped by a redeploy
    without a volume, or a `chunks` table created after the last upload),
    the index is rebuilt from those saved documents before answering — so Q&A
    keeps working instead of falsely reporting "no indexed records". Only a
    patient with NO documents at all gets that graceful no-records message;
    a patient whose documents contain nothing retrievable gets an explicit
    "no indexable content" answer instead.
    """
    if not patient_key or not patient_key.strip():
        raise ValueError("patient_key is required and cannot be empty.")
    if not question or not question.strip():
        raise ValueError("question is required and cannot be empty.")

    effective_retrieval_query = (
        retrieval_query if retrieval_query and retrieval_query.strip() else question
    )

    # Use vector_store abstraction when supabase, else Chroma directly (for test mocks)
    if vector_store.get_store_name() == "supabase":
        if vector_store.count(patient_key) == 0:
            # Empty index + persisted documents => the index is stale/missing
            # (ephemeral Chroma dir wiped by a redeploy, chunks table freshly
            # created, background job crashed before indexing). Rebuild it from
            # the patient's saved records so the question can still be answered.
            reindexed = _reindex_from_persisted_documents(patient_key)
            if reindexed is None:
                return dict(_NO_INFO_ANSWER)
            if reindexed == 0:
                return dict(_NO_INDEXABLE_CONTENT_ANSWER)
        query_embedding = embed_texts([effective_retrieval_query])[0]
        _, docs, metadatas = vector_store.query(patient_key, query_embedding, top_k)
    else:
        collection = _get_patient_collection(patient_key, create=False)
        if collection is None or collection.count() == 0:
            reindexed = _reindex_from_persisted_documents(patient_key)
            if reindexed is None:
                return dict(_NO_INFO_ANSWER)
            if reindexed == 0:
                return dict(_NO_INDEXABLE_CONTENT_ANSWER)
            # Re-fetch now that the re-index has populated the store.
            collection = _get_patient_collection(patient_key, create=False)
            if collection is None or collection.count() == 0:
                return dict(_NO_INFO_ANSWER)
        query_embedding = embed_texts([effective_retrieval_query])[0]
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
        )
        docs = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]

    if not docs:
        # Normally unreachable after the re-index step above; keep a
        # graceful fallback that does not lie: distinguish "no records were
        # ever uploaded" from "records exist but nothing was retrieved".
        if _persisted_documents(patient_key):
            return dict(_NO_INDEXABLE_CONTENT_ANSWER)
        return dict(_NO_INFO_ANSWER)

    context_blocks = [
        f"[date: {meta.get('date') or 'unknown'} | source_file: {meta.get('source_file') or 'unknown'} "
        f"| type: {meta.get('chunk_type') or 'unknown'}]\n{text}"
        for text, meta in zip(docs, metadatas)
    ]
    context_str = "\n\n".join(context_blocks)

    # Conversational focus: pin the entities the conversation is already
    # about into the prompt as established facts from the timeline. This is
    # the deterministic half of follow-up handling — it does not depend on
    # the LLM rewrite having succeeded, so "what if I take it with this?"
    # keeps its subject even on a bad rewrite day.
    focus_block = ""
    if focus and any(focus.get(field) for field in ("medications", "lab_tests", "source_files")):
        focus_block = _render_focus_context(_timeline_for(patient_key), focus)
        if focus_block:
            context_str = f"{context_str}\n\n{focus_block}"

    user_content = (
        f"Retrieved patient records:\n\n{context_str}\n\nQuestion: {question}"
    )
    # Reuse the resilient completion runner so reasoning models'
    # <think>...</think> blocks get stripped client-side and transient
    # server-side JSON-validation rejections are retried, matching the
    # behaviour of the extraction and cross-check paths.
    if chat_history:
        # _completion_resilient takes a single user turn; if there's chat
        # history we do one direct call with the strict response format and
        # let any retryable error surface — history is only passed on
        # follow-up turns in the same session and reasoning-tag leaks are
        # still covered by the tolerant parse below.
        messages = [{"role": "system", "content": QA_SYSTEM_PROMPT}]
        messages.extend(chat_history)
        messages.append({"role": "user", "content": user_content})
        try:
            response = _chat_completion(
                model=CHAT_MODEL,
                messages=messages,
                response_format=ANSWER_RESPONSE_FORMAT,
            )
        except OpenAIError as e:
            raise RuntimeError(f"Chat completion failed while answering question: {e}") from e
        raw = response.choices[0].message.content or ""
    else:
        raw = _completion_resilient(
            model=CHAT_MODEL,
            system_prompt=QA_SYSTEM_PROMPT,
            user_content=user_content,
            strict_format=ANSWER_RESPONSE_FORMAT,
        )

    # Tolerant parse: reuse the same think-stripping logic the extractor
    # uses, so a model that still emits <think> tags (e.g. under fallback
    # to plain-text mode) doesn't blow up the Q&A endpoint.
    from medical_extractor import _parse_json_object
    try:
        result = _parse_json_object(raw)
    except ValueError as e:
        raise RuntimeError(f"Chat model returned unparseable output: {e}") from e

    # Enforce the response contract even when a provider's fallback ladder
    # produced partial JSON: cross_document defaults to False, never missing.
    result.setdefault("cross_document", False)
    result.setdefault("recommend_professional_consult", False)
    result.setdefault("sources", [])

    # Deterministic post-processing, in code rather than left to the model:
    # sources gain document_type/document_url from the timeline, and the
    # safety guard forces a professional consult on risk/allergy/dosage
    # questions and low-confidence answers.
    timeline = _timeline_for(patient_key)
    result["sources"] = _enrich_sources(result.get("sources") or [], timeline)
    result = _apply_safety_guard(result, question)
    return result
