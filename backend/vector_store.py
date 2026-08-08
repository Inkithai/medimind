"""
Vector Store Abstraction — Chroma vs Supabase (pgvector-style)
==============================================================
MediMind originally used local Chroma (PersistentClient at CHROMA_DIR)
which requires a Railway Volume at /data/chroma_db. This module
abstracts the vector store so Railway can run without a volume:

  VECTOR_STORE=chroma   → local Chroma (default, backward compat, needs volume)
  VECTOR_STORE=supabase → Supabase table `chunks` (no volume, brute-force cosine in Python;
                          uses existing Supabase service_role key, no new deps)

Both backends expose the same interface:
  upsert(patient_key, ids, embeddings, documents, metadatas)
  query(patient_key, query_embedding, n_results) -> (ids, documents, metadatas)
  count(patient_key)
  delete_collection(patient_key)

The supabase backend stores embeddings as jsonb and does Python cosine
similarity. Per-user chunk counts are small (10-30), so brute-force is
fast (<5ms) and avoids needing the pgvector extension. If you later
enable pgvector, you can replace the Python loop with a single `rpc`
call without changing callers.

Env:
  VECTOR_STORE   chroma | supabase (default: chroma)
  CHROMA_DIR     ./chroma_db (only for chroma)
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (only for supabase)
"""

import os
import re
import math
import logging
from typing import Any, Dict, List, Tuple, Optional

logger = logging.getLogger("vector_store")

VECTOR_STORE = os.environ.get("VECTOR_STORE", "chroma").strip().lower() or "chroma"
CHROMA_DIR = os.environ.get("CHROMA_DIR", "./chroma_db")

# --- Chroma backend (lazy import) ---

_chroma_client = None

def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        try:
            import chromadb  # lazy, so supabase mode doesn't require chromadb
        except ImportError as e:
            raise RuntimeError(
                "chromadb is not installed but VECTOR_STORE=chroma is active. "
                "Install it with: pip install chromadb  (or: pip install -r requirements.txt) "
                "— or set VECTOR_STORE=supabase to keep vectors in Supabase instead "
                "(no local volume, no chromadb dependency)."
            ) from e
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client

def get_chroma_client():
    """Public alias so sibling modules (retrieval.py) share this process's
    single, lazily-constructed Chroma client — and its one actionable
    'chromadb not installed' message — instead of each constructing their
    own PersistentClient per call."""
    return _get_chroma_client()

def _sanitize_collection_name(patient_key: str) -> str:
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

def _chroma_upsert(patient_key: str, ids: List[str], embeddings: List[List[float]], documents: List[str], metadatas: List[Dict[str, Any]]):
    db = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    col = db.get_or_create_collection(name=name, metadata={"patient_key": patient_key})
    col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    logger.info("Chroma upsert %d chunks for %s", len(ids), patient_key)

def _chroma_query(patient_key: str, query_embedding: List[float], n_results: int) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    db = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    try:
        col = db.get_collection(name=name)
    except Exception:
        return [], [], []
    if col.count() == 0:
        return [], [], []
    res = col.query(query_embeddings=[query_embedding], n_results=min(n_results, col.count()))
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    return ids, docs, metas

def _chroma_count(patient_key: str) -> int:
    db = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    try:
        col = db.get_collection(name=name)
        return col.count()
    except Exception:
        return 0

def _chroma_delete(patient_key: str):
    db = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    try:
        db.delete_collection(name=name)
    except Exception:
        pass

# --- Supabase backend (brute-force) ---

def _supabase_client():
    # Import lazily to avoid circular import with db.py
    from db import _get_client
    return _get_client()

def _cosine(a: List[float], b: List[float]) -> float:
    # Returns similarity (1 = identical, -1 = opposite). Handles zero vectors.
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)

def _supabase_upsert(patient_key: str, ids: List[str], embeddings: List[List[float]], documents: List[str], metadatas: List[Dict[str, Any]]):
    client = _supabase_client()
    # Upsert per chunk. Supabase doesn't have bulk upsert with jsonb vector easily,
    # so we do per-row upsert. Chunk counts are small (20-30), so fine.
    for i, cid in enumerate(ids):
        row = {
            "id": cid,
            "patient_key": patient_key,
            "text": documents[i],
            "embedding": embeddings[i],  # stored as jsonb array
            "metadata": metadatas[i],
        }
        # postgrest upsert on conflict (id)
        try:
            client.table("chunks").upsert(row, on_conflict="id").execute()
        except Exception as e:
            # Fallback: delete then insert (for older postgrest)
            try:
                client.table("chunks").delete().eq("id", cid).execute()
                client.table("chunks").insert(row).execute()
            except Exception as e2:
                logger.error("Supabase upsert failed for %s: %s / %s", cid, e, e2)
                raise
    logger.info("Supabase upsert %d chunks for %s", len(ids), patient_key)

def _supabase_query(patient_key: str, query_embedding: List[float], n_results: int) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    client = _supabase_client()
    try:
        res = client.table("chunks").select("id, text, metadata, embedding").eq("patient_key", patient_key).execute()
    except Exception as e:
        # Table may not exist yet (old deployment before migration). Fall back to empty.
        if "chunks" in str(e).lower() or "PGRST205" in str(e):
            logger.warning("Supabase chunks table missing (run supabase_schema.sql migration): %s", e)
            return [], [], []
        raise
    rows = res.data or []
    if not rows:
        return [], [], []
    # Score each row
    scored = []
    for r in rows:
        emb = r.get("embedding")
        if not emb or not isinstance(emb, list):
            continue
        try:
            sim = _cosine(query_embedding, emb)
        except Exception:
            sim = -1
        scored.append((sim, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:n_results]
    ids = [r["id"] for _, r in top]
    docs = [r["text"] for _, r in top]
    metas = [r["metadata"] or {} for _, r in top]
    return ids, docs, metas

def _supabase_count(patient_key: str) -> int:
    client = _supabase_client()
    try:
        res = client.table("chunks").select("id", count="exact").eq("patient_key", patient_key).execute()
        # supabase-py returns count in res.count
        if hasattr(res, "count") and res.count is not None:
            return res.count
        return len(res.data or [])
    except Exception as e:
        if "chunks" in str(e).lower() or "PGRST205" in str(e):
            return 0
        raise

def _supabase_delete(patient_key: str):
    client = _supabase_client()
    try:
        client.table("chunks").delete().eq("patient_key", patient_key).execute()
    except Exception:
        pass

# --- Public facade ---

def upsert(patient_key: str, ids: List[str], embeddings: List[List[float]], documents: List[str], metadatas: List[Dict[str, Any]]):
    if VECTOR_STORE == "supabase":
        return _supabase_upsert(patient_key, ids, embeddings, documents, metadatas)
    return _chroma_upsert(patient_key, ids, embeddings, documents, metadatas)

def query(patient_key: str, query_embedding: List[float], n_results: int) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    if VECTOR_STORE == "supabase":
        return _supabase_query(patient_key, query_embedding, n_results)
    return _chroma_query(patient_key, query_embedding, n_results)

def count(patient_key: str) -> int:
    if VECTOR_STORE == "supabase":
        return _supabase_count(patient_key)
    return _chroma_count(patient_key)

def delete_collection(patient_key: str):
    if VECTOR_STORE == "supabase":
        return _supabase_delete(patient_key)
    return _chroma_delete(patient_key)

def get_store_name() -> str:
    return VECTOR_STORE
