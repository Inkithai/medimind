"""
Vector Store Inspection CLI
=========================================
Read-only debug/demo helper for looking at what's actually stored in the
vector store (Chroma at ./chroma_db or Supabase `chunks` table when
VECTOR_STORE=supabase) that retrieval.py builds and queries. Never modifies
the store, never calls OpenAI.

Usage:
    python inspect_chroma.py                            # list every patient collection + chunk count
    python inspect_chroma.py "amit sharma"               # show chunks for one patient
    python inspect_chroma.py "amit sharma" --limit 20    # show more chunks
    python inspect_chroma.py "amit sharma" --type medication   # filter by chunk_type
    VECTOR_STORE=supabase python inspect_chroma.py "amit sharma"  # use Supabase backend
"""

import argparse
import os
from typing import Optional

from retrieval import CHROMA_DIR, _get_chroma_client, _sanitize_collection_name
import vector_store

CHUNK_TYPES = ["medication", "lab_result", "clinical_note", "allergy"]


def list_collections() -> None:
    """Prints every patient collection currently in the vector store."""
    if vector_store.get_store_name() == "supabase":
        # Supabase: list distinct patient_key
        try:
            from db import _get_client
            client = _get_client()
            # Distinct patient_key via query
            res = client.table("chunks").select("patient_key").execute()
            keys = {}
            for r in (res.data or []):
                k = r.get("patient_key")
                if k:
                    keys[k] = keys.get(k, 0) + 1
            if not keys:
                print("No chunks found in Supabase `chunks` table — nothing has been indexed yet.")
                print("Run `supabase_schema.sql` migration if table missing.")
                return
            print(f"{len(keys)} patient(s) in Supabase `chunks` (VECTOR_STORE=supabase):")
            for k, cnt in sorted(keys.items()):
                print(f"  {k}  ({cnt} chunk(s))")
        except Exception as e:
            print(f"Supabase list failed (is VECTOR_STORE=supabase and table migrated?): {e}")
        return

    # Chroma
    client = _get_chroma_client()
    collections = client.list_collections()
    if not collections:
        print(f"No collections found in {CHROMA_DIR} — nothing has been indexed yet.")
        return
    print(f"{len(collections)} collection(s) in {CHROMA_DIR} (VECTOR_STORE=chroma):")
    for c in collections:
        coll = client.get_collection(c.name)
        print(f"  {c.name}  ({coll.count()} chunk(s))")


def show_patient(patient_key: str, limit: int, chunk_type: Optional[str]) -> None:
    """Prints up to `limit` chunks (text + metadata) for one patient,
    optionally filtered to a single chunk_type."""
    if vector_store.get_store_name() == "supabase":
        try:
            from db import _get_client
            client = _get_client()
            q = client.table("chunks").select("text, metadata").eq("patient_key", patient_key).limit(limit)
            # Note: filtering by chunk_type requires jsonb -> PostgREST syntax not trivial; filter in Python
            res = q.execute()
            rows = res.data or []
            if chunk_type:
                rows = [r for r in rows if (r.get("metadata") or {}).get("chunk_type") == chunk_type]
                rows = rows[:limit]
            header = f"Patient '{patient_key}' — {len(rows)} chunk(s) showing up to {limit} (Supabase)"
            if chunk_type:
                header += f" (chunk_type={chunk_type})"
            print(header + ":\n")
            if not rows:
                print("  (no chunks matched)")
                return
            for i, r in enumerate(rows):
                print(f"[{i}] {r.get('metadata')}")
                print(f"    {r.get('text')}\n")
        except Exception as e:
            print(f"Supabase show failed: {e}")
        return

    # Chroma
    client = _get_chroma_client()
    name = _sanitize_collection_name(patient_key)
    try:
        coll = client.get_collection(name)
    except Exception:
        print(f"No collection found for patient_key '{patient_key}' (looked for '{name}').")
        return

    where = {"chunk_type": chunk_type} if chunk_type else None
    data = coll.get(limit=limit, where=where, include=["documents", "metadatas"])
    docs = data["documents"]
    metas = data["metadatas"]

    header = f"Collection '{name}' — {coll.count()} total chunk(s), showing up to {limit}"
    if chunk_type:
        header += f" (chunk_type={chunk_type})"
    print(header + ":\n")

    if not docs:
        print("  (no chunks matched)")
        return

    for i, (doc, meta) in enumerate(zip(docs, metas)):
        print(f"[{i}] {meta}")
        print(f"    {doc}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect the local Chroma vector store (read-only).")
    parser.add_argument("patient_key", nargs="?", help="Patient to inspect (omit to list all collections)")
    parser.add_argument("--limit", type=int, default=10, help="Max chunks to show (default: 10)")
    parser.add_argument("--type", dest="chunk_type", default=None, choices=CHUNK_TYPES,
                         help="Filter to one chunk_type")
    args = parser.parse_args()

    if args.patient_key:
        show_patient(args.patient_key, args.limit, args.chunk_type)
    else:
        list_collections()
