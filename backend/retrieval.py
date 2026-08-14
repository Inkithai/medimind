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

from medical_extractor import MODEL, _completion_resilient
import vector_store  # abstraction over Chroma (local) and Supabase (no volume)

logger = logging.getLogger("retrieval")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = MODEL  # reuse the same chat model configured in medical_extractor.py

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

def _chunk_id(patient_key: str, source_file: Optional[str], chunk_type: str, payload: str) -> str:
    """Stable, content-addressed chunk ID so re-indexing the same documents
    upserts in place instead of creating duplicates.

    IDs must NOT include the item's position in the timeline list. That list
    is rebuilt and re-sorted on every upload, so an index-based id (``…|0``,
    ``…|1``) shifts whenever an older document is added and leaves the
    previous id behind as a stale duplicate the next Q&A still retrieves.
    """
    raw = f"{patient_key}|{source_file or 'unknown'}|{chunk_type}|{payload}"
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


def _diagnosis_chunk_text(diagnosis: Dict[str, Any]) -> str:
    return (
        f"Diagnosis or condition explicitly mentioned: {diagnosis.get('name', 'unknown')} "
        f"on {diagnosis.get('date') or 'an unknown date'} "
        f"(source: {diagnosis.get('source_file') or 'unknown file'})."
    )


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

    for med in timeline.get("medications_timeline", []):
        text = _medication_chunk_text(med)
        chunks.append({
            "id": _chunk_id(patient_key, med.get("source_file"), "medication", text),
            "text": text,
            "metadata": {
                "patient_key": patient_key,
                "date": med.get("date") or "",
                "source_file": med.get("source_file") or "",
                "source_page": med.get("source_page") or 0,
                "chunk_type": "medication",
            },
        })

    for lab in timeline.get("lab_results_timeline", []):
        text = _lab_result_chunk_text(lab)
        chunks.append({
            "id": _chunk_id(patient_key, lab.get("source_file"), "lab_result", text),
            "text": text,
            "metadata": {
                "patient_key": patient_key,
                "date": lab.get("date") or "",
                "source_file": lab.get("source_file") or "",
                "source_page": lab.get("source_page") or 0,
                "chunk_type": "lab_result",
            },
        })

    for visit in timeline.get("visits", []):
        if not visit.get("clinical_notes"):
            continue
        source_file = visit.get("_source", {}).get("file")
        text = _clinical_note_chunk_text(visit)
        chunks.append({
            "id": _chunk_id(patient_key, source_file, "clinical_note", text),
            "text": text,
            "metadata": {
                "patient_key": patient_key,
                "date": visit.get("date") or "",
                "source_file": source_file or "",
                "source_page": visit.get("_source", {}).get("page") or 0,
                "chunk_type": "clinical_note",
            },
        })

    for i, diagnosis in enumerate(timeline.get("diagnoses_timeline", []) or []):
        chunks.append({
            "id": _chunk_id(patient_key, diagnosis.get("source_file"), "diagnosis", i),
            "text": _diagnosis_chunk_text(diagnosis),
            "metadata": {
                "patient_key": patient_key,
                "date": diagnosis.get("date") or "",
                "source_file": diagnosis.get("source_file") or "",
                "source_page": diagnosis.get("source_page") or 0,
                "chunk_type": "diagnosis",
            },
        })

    allergies = timeline.get("known_allergies") or []
    if allergies:
        text = _allergy_chunk_text(allergies)
        chunks.append({
            "id": _chunk_id(patient_key, None, "allergy", text),
            "text": text,
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
    (e.g. 'amit sharma') into a safe, stable collection name.

    Truncation to 63 chars happens BEFORE the end-alphanumeric fixup, not
    after. Truncating last can slice a long key mid-separator (e.g. right
    after a '_'), leaving a trailing non-alphanumeric character that
    violates Chroma's naming rule — and it can also undo the minimum-length
    padding below. Trimming trailing separators post-truncation and then
    re-applying the alnum-ending fix closes both gaps.

    Kept byte-identical to vector_store._sanitize_collection_name(); both
    must agree or the Chroma path would read from a different collection
    than it wrote to."""
    name = re.sub(r"[^a-z0-9._-]+", "_", patient_key.strip().lower()).strip("_.-")
    if not name:
        name = "patient"
    if not name[0].isalnum():
        name = "p" + name
    # Truncate BEFORE the end-alphanumeric fixup. Cutting last can land on a
    # separator (e.g. 62 'a's + space → trailing '_') and Chroma rejects it.
    name = name[:63].rstrip("_.-")
    if not name:
        name = "patient"
    if not name[-1].isalnum():
        name = name + "0"
    while len(name) < 3:
        name += "0"
    return name


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
# 3. Retrieval + Q&A
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
- Cite the date, source_file, and page (null when unavailable) of every chunk you rely on in "sources".
- Give a concise confidence_reason that says whether the evidence was direct,
  combined across records, partial, or insufficient. Never use model internals
  or hidden reasoning in this explanation.
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
        "confidence_reason": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "source_file": {"type": "string"},
                    "page": {"type": ["integer", "null"]},
                },
                "required": ["date", "source_file", "page"],
                "additionalProperties": False,
            },
        },
        "recommend_professional_consult": {"type": "boolean"},
    },
    "required": [
        "answer", "confidence", "confidence_reason", "sources",
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
    "confidence_reason": "No indexed patient records were available to support an answer.",
    "sources": [],
    "recommend_professional_consult": False,
}

# Patient HAS persisted documents, but none of them contain anything the
# Q&A indexer can retrieve (no medications, lab results, clinical notes,
# or allergies). Different from _NO_INFO_ANSWER, which means "no records
# were ever uploaded" — returning the wrong one of the two is what made
# users with uploaded documents see a false "no indexed records" message.
_NO_INDEXABLE_CONTENT_ANSWER = {
    "answer": (
        "I don't have enough information — your records were found, but they "
        "contain no medications, lab results, clinical notes, diagnoses, or allergies for "
        "Q&A to search."
    ),
    "confidence": 0.0,
    "confidence_reason": "The uploaded records contain no medications, lab results, clinical notes, diagnoses, or allergies that Q&A can retrieve.",
    "sources": [],
    "recommend_professional_consult": False,
}


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
) -> Dict[str, Any]:
    """
    Answers a natural-language question about one patient, grounded only in
    that patient's already-indexed timeline chunks.

    1. Embeds the retrieval query (see retrieval_query below).
    2. Queries the patient's Chroma collection for the top_k most similar
       chunks.
    3. Builds a prompt from those chunks (each tagged with its date and
       source_file), plus chat_history and the (display) question.
    4. Calls the chat model with a system prompt that forbids diagnosis,
       requires deferring to a professional for risk/interaction/dosage
       questions, and forces structured JSON output.

    retrieval_query: optional string used for embedding/Chroma retrieval
        instead of `question`. Lets a caller (e.g. conversation.py) rewrite
        an ambiguous follow-up like "was that safe?" into a fully-specified
        search query, while `question` remains the literal text shown to
        the answering LLM as "the question asked". Defaults to `question`
        when omitted, so existing single-shot callers are unaffected.

    Returns the parsed JSON:
        {"answer": str, "confidence": float, "sources": [{"date", "source_file"}],
         "recommend_professional_consult": bool}

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
        f"| page: {meta.get('source_page') or 'unknown'} | type: {meta.get('chunk_type') or 'unknown'}]\n{text}"
        for text, meta in zip(docs, metadatas)
    ]
    context_str = "\n\n".join(context_blocks)

    # Fold prior turns into the single user message so follow-ups go through
    # the same resilient ladder as first-shot Q&A. The previous split path
    # called _chat_completion() directly, so a json_validate_failed / 429 on
    # turn 2 crashed the conversation instead of retrying.
    history_block = ""
    if chat_history:
        transcript = "\n".join(
            f"{(turn.get('role') or 'user').upper()}: {turn.get('content') or ''}"
            for turn in chat_history
        )
        history_block = (
            "Prior conversation (context only — not retrieved records):\n"
            f"{transcript}\n\n"
        )
    user_content = (
        f"{history_block}Retrieved patient records:\n\n{context_str}\n\nQuestion: {question}"
    )
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
        for source in result.get("sources", []) or []:
            if isinstance(source, dict):
                source.setdefault("page", None)
        if not result.get("confidence_reason"):
            confidence = result.get("confidence")
            if isinstance(confidence, (int, float)) and confidence >= 0.9:
                reason = "The retrieved records directly and consistently support this answer."
            elif isinstance(confidence, (int, float)) and confidence >= 0.6:
                reason = "The answer combines relevant records, but some supporting detail is incomplete."
            else:
                reason = "The retrieved evidence is partial or insufficient, so this answer has low confidence."
            result["confidence_reason"] = reason
        return result
    except ValueError as e:
        raise RuntimeError(f"Chat model returned unparseable output: {e}") from e
