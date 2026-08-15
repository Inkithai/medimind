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

import gc
import os
import re
import json
import hashlib
import logging
from typing import Any, Dict, Iterator, List, Optional

from openai import OpenAI, OpenAIError

from medical_extractor import client, MODEL, _completion_resilient, _chat_completion
from memory_probe import log_rss
import vector_store  # abstraction over Chroma (local) and Supabase (no volume)

logger = logging.getLogger("retrieval")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = MODEL  # reuse the same chat model configured in medical_extractor.py

CHROMA_DIR = os.environ.get("CHROMA_DIR", "./chroma_db")


def _embedding_batch_size() -> int:
    """Chunks embedded (and upserted) per batch.

    This bounds peak memory during indexing: a batch's texts + float vectors
    are the only embedding data alive at any moment. The default of 16 keeps
    an ONNX MiniLM batch small enough to survive a 512 MB container; raise
    EMBEDDING_BATCH_SIZE on a bigger instance to trade memory for speed.
    """
    try:
        return max(1, min(256, int(os.environ.get("EMBEDDING_BATCH_SIZE", "16"))))
    except ValueError:
        return 16


EMBEDDING_BATCH_SIZE = _embedding_batch_size()
# VECTOR_STORE is read inside vector_store.py; we keep CHROMA_DIR for backward compat

# Groq has no embeddings endpoint. When an OpenAI key is available it
# is used ONLY for embeddings (never for chat); otherwise fall back to
# Chroma's built-in local ONNX MiniLM model, which needs no API key at all.
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if _OPENAI_API_KEY == "your-openai-api-key":
    _OPENAI_API_KEY = None
_openai_embedding_client = OpenAI(api_key=_OPENAI_API_KEY) if _OPENAI_API_KEY else None

_local_embedding_fn = None


def _apply_onnx_cache_dir(model_cls) -> None:
    """Point Chroma's ONNX model cache at ONNX_MODEL_CACHE_DIR when set.

    Chroma hardcodes the cache to ``Path.home()/.cache/chroma/onnx_models``.
    On a container with an ephemeral home that means every cold start
    re-downloads the ~79 MB all-MiniLM-L6-v2 archive, extracts it, and holds
    both in memory during the first upload — exactly when extraction results
    are also resident. Baking the model into the image (see backend/Dockerfile)
    and pointing here at that path removes the download from the request path.

    Best effort only: an unknown chromadb layout must not break indexing.
    """
    cache_dir = os.environ.get("ONNX_MODEL_CACHE_DIR", "").strip()
    if not cache_dir:
        return
    try:
        from pathlib import Path

        target = Path(cache_dir) / model_cls.MODEL_NAME
        target.mkdir(parents=True, exist_ok=True)
        model_cls.DOWNLOAD_PATH = target
        logger.info("ONNX embedding model cache directory: %s", target)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not apply ONNX_MODEL_CACHE_DIR=%s: %s", cache_dir, exc)


def _get_local_embedding_function():
    """Lazily initialise Chroma's default local embedding function
    (all-MiniLM-L6-v2 via ONNX runtime), ONCE per process.

    The model weights (~79 MB) download on first use and the ONNX session
    itself costs tens of MB of RSS. Both are cached in the module-level
    ``_local_embedding_fn`` so a second upload never pays for them again —
    re-creating the session per upload was a large part of the memory
    growth that got the container OOM-killed.

    CPU execution is requested explicitly: containers have no GPU, and
    letting onnxruntime probe for one both wastes memory on provider
    initialisation and emits the noisy "GPU device discovery failed"
    warning about /sys/class/drm/card0/device/vendor.
    """
    global _local_embedding_fn
    if _local_embedding_fn is None:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        _apply_onnx_cache_dir(ONNXMiniLM_L6_V2)
        log_rss(logger, "embedding_model_load_start")
        try:
            _local_embedding_fn = ONNXMiniLM_L6_V2(
                preferred_providers=["CPUExecutionProvider"]
            )
        except TypeError:
            # Older chromadb builds don't accept preferred_providers.
            _local_embedding_fn = ONNXMiniLM_L6_V2()
        log_rss(logger, "embedding_model_load_done")
    return _local_embedding_fn


def preload_embedding_model() -> bool:
    """Warm the embedding backend at startup instead of mid-upload.

    Returns True when a local model was loaded, False when embeddings are
    served by OpenAI (nothing to preload) or the load failed. Failure is
    never fatal: indexing retries lazily and uploads must not depend on it.
    """
    if _openai_embedding_client is not None:
        logger.info("Embeddings use OpenAI (%s) — no local model to preload.", EMBEDDING_MODEL)
        return False
    try:
        _get_local_embedding_function()
        return True
    except Exception as exc:
        logger.warning("Local embedding model preload failed (will retry lazily): %s", exc)
        return False


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

    # Local ONNX path: batch here too. Previously the whole corpus was sent
    # to the model in ONE call, so peak memory scaled with the number of
    # chunks (tokenised tensors + output vectors all alive at once).
    embed = _get_local_embedding_function()
    local_embeddings: List[List[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        try:
            vectors = embed(batch)
        except Exception as e:
            raise RuntimeError(f"Local embedding failed for {len(batch)} chunk(s): {e}") from e
        local_embeddings.extend(
            vector.tolist() if hasattr(vector, "tolist") else list(vector)
            for vector in vectors
        )
        del vectors
    return local_embeddings


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


def _iter_batches(chunks: List[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    for start in range(0, len(chunks), size):
        yield chunks[start:start + size]


def index_patient_timeline(patient_key: str, timeline: Dict[str, Any]) -> int:
    """
    Entry point for indexing: chunks a patient's timeline, embeds every
    chunk, and upserts them into that patient's local Chroma collection
    (persisted under ./chroma_db). Safe to call repeatedly on the same
    timeline — chunk IDs are deterministic, so re-indexing overwrites
    existing entries rather than duplicating them.

    Memory behaviour (this is why the work is batched): embedding is the
    single largest allocation in the whole upload pipeline. Chunks are
    therefore embedded and upserted in EMBEDDING_BATCH_SIZE-sized batches,
    and each batch's texts/vectors are released before the next one is
    built, so peak RSS is a function of the batch size rather than of how
    many documents the patient has. RSS is sampled around each stage so a
    container OOM kill can be attributed to a specific batch instead of
    just ending the log.

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

    total = len(chunks)
    store_name = vector_store.get_store_name()
    batch_size = EMBEDDING_BATCH_SIZE
    log_rss(logger, "indexing_start", chunks=total, batch_size=batch_size, store=store_name)

    # One collection handle is resolved once and reused by every batch
    # (the Chroma client itself is process-cached in vector_store).
    collection = None if store_name == "supabase" else _get_patient_collection(patient_key, create=True)

    indexed = 0
    for batch_number, batch in enumerate(_iter_batches(chunks, batch_size), start=1):
        ids = [c["id"] for c in batch]
        texts = [c["text"] for c in batch]
        metadatas = [c["metadata"] for c in batch]
        embeddings = embed_texts(texts)

        if collection is None:
            vector_store.upsert(
                patient_key,
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        else:
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

        indexed += len(batch)
        # Drop this batch's vectors before building the next one so peak
        # memory stays flat across a large record.
        del embeddings, ids, texts, metadatas, batch
        log_rss(logger, "indexing_batch_done", batch=batch_number, indexed=indexed, total=total)

    # The chunk list is the last large structure held by this function.
    del chunks
    gc.collect()
    log_rss(logger, "indexing_done", chunks=indexed, store=store_name)
    logger.info(
        "Indexed %d chunk(s) for patient '%s' into %s.",
        indexed,
        patient_key,
        "supabase" if store_name == "supabase" else f"Chroma ({CHROMA_DIR})",
    )
    return indexed


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
- Cite the date and source_file of every chunk you rely on in "sources".
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
        "recommend_professional_consult": {"type": "boolean"},
    },
    "required": ["answer", "confidence", "sources", "recommend_professional_consult"],
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
        "contain no medications, lab results, clinical notes, or allergies for "
        "Q&A to search."
    ),
    "confidence": 0.0,
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
        f"| type: {meta.get('chunk_type') or 'unknown'}]\n{text}"
        for text, meta in zip(docs, metadatas)
    ]
    context_str = "\n\n".join(context_blocks)

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
        return _parse_json_object(raw)
    except ValueError as e:
        raise RuntimeError(f"Chat model returned unparseable output: {e}") from e
