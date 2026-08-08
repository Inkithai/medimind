"""Regression tests for the "no indexed records" Q&A false negative.

The user-reported bug: /api/v1/qa returned
"I don't have enough information — no indexed records were found for this
patient yet." (HTTP 200, confidence 0, no sources) even though the patient
had uploaded documents. Root causes:

  1. The vector index lives in a local Chroma dir / `chunks` table, while
     the extracted documents live in Supabase Postgres. On redeploys /
     restarts without a persistent volume (or a migration run after the
     uploads), the index is empty even though documents exist.
  2. The supabase backend swallowed a missing `chunks` table (PGRST205) as
     "0 chunks" — misconfiguration masquerading as "no records".

Fixes under test:
  - answer_question() self-heals: when the index is empty but persisted
    documents exist, it rebuilds the index from those documents and answers
    normally instead of lying "no indexed records".
  - A patient with documents but nothing indexable gets a truthful
    "no indexable content" message (not "no indexed records").
  - A missing Supabase `chunks` table raises an actionable
    VectorStoreSchemaError instead of silently returning "no records".
"""
import os
import sys
import json
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy-service-role-key"
os.environ.pop("VECTOR_STORE", None)  # default = chroma

import vector_store
import retrieval

# One extracted document as persisted in the `documents` table (same shape
# the upload pipeline stores: flat page dict with medications/lab/allergies).
PERSISTED_DOCS = [{
    "document_type": "prescription",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "medications": [{
        "name": "Paracetamol", "ingredients": ["Paracetamol"], "dosage": "500 mg",
        "frequency": "3x daily", "duration": "5 days", "dosage_value": 500,
        "dosage_unit": "mg", "frequency_per_day": 3, "is_as_needed": False,
        "confidence": 0.95,
    }],
    "lab_results": [{
        "test_name": "HbA1c", "value": "6.1", "unit": "%", "reference_range": "<5.7",
        "flag": "high", "confidence": 0.9,
    }],
    "allergies_noted": ["Penicillin"],
    "clinical_notes": None,
    "overall_confidence": 0.92,
    "_source": {"file": "rx.pdf"},
}]

ANSWER_JSON = json.dumps({
    "answer": "You are taking Paracetamol 500 mg three times daily.",
    "confidence": 0.95,
    "sources": [{"date": "2024-03-15", "source_file": "rx.pdf"}],
    "recommend_professional_consult": False,
})


def _make_fake_chromadb():
    """A fake chromadb module with per-module persistent collections."""
    state = {"clients": [], "collections": {}}

    class FakeCollection:
        def __init__(self, name):
            self.name = name
            self.rows = {}

        def upsert(self, ids, embeddings, documents, metadatas):
            for i, cid in enumerate(ids):
                self.rows[cid] = (embeddings[i], documents[i], metadatas[i])

        def count(self):
            return len(self.rows)

        def query(self, query_embeddings, n_results):
            docs, metas = [], []
            for _emb, doc, meta in list(self.rows.values())[:n_results]:
                docs.append(doc)
                metas.append(meta)
            return {"documents": [docs], "metadatas": [metas]}

    class FakeClient:
        def __init__(self, path):
            self.path = path

        def get_or_create_collection(self, name, metadata=None):
            return state["collections"].setdefault(name, FakeCollection(name))

        def get_collection(self, name):
            if name not in state["collections"]:
                raise ValueError(f"Collection {name} does not exist")
            return state["collections"][name]

    fake_module = types.ModuleType("chromadb")
    fake_module.PersistentClient = FakeClient
    return fake_module, state


def _restore_chromadb(saved):
    if saved is None:
        sys.modules.pop("chromadb", None)
    else:
        sys.modules["chromadb"] = saved


def _install_fake_chromadb():
    fake, state = _make_fake_chromadb()
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = fake
    vector_store._chroma_client = None
    return fake, state, saved


def test_index_lost_but_documents_exist_self_heals_and_answers():
    """The user's exact scenario: documents are in the DB, the vector index
    is empty (wiped Chroma dir / fresh container) — Q&A must rebuild the
    index from persisted documents and answer, not claim 'no records'."""
    fake, state, saved = _install_fake_chromadb()
    try:
        with mock.patch.object(retrieval, "embed_texts",
                               side_effect=lambda texts: [[0.1] * 384 for _ in texts]), \
             mock.patch.object(retrieval, "_completion_resilient", return_value=ANSWER_JSON), \
             mock.patch("db.load_documents", return_value=list(PERSISTED_DOCS)):
            out = retrieval.answer_question("anon_self_heal", "what medication am I on?")

        assert "Paracetamol" in out["answer"], out
        assert out["confidence"] == 0.95
        assert out["sources"] == [{"date": "2024-03-15", "source_file": "rx.pdf"}]
        # The store must now actually contain the rebuilt index.
        assert state["collections"]["anon_self_heal"].count() == 3  # med + lab + allergy
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_never_uploaded_patient_keeps_graceful_no_info():
    """No documents, no index -> the legacy 'no indexed records' message
    (containing 'don't have enough information') is still correct."""
    fake, state, saved = _install_fake_chromadb()
    try:
        with mock.patch("db.load_documents", return_value=[]):
            out = retrieval.answer_question("anon_brand_new", "anything?")
        assert "don't have enough information" in out["answer"]
        assert out["confidence"] == 0.0 and out["sources"] == []
        assert state["collections"] == {}, "must not create an index for a patient with no records"
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_documents_without_indexable_content_get_truthful_message():
    """Patient has documents, but they contain no medications/labs/notes/
    allergies -> truthful 'no indexable content', NOT 'no indexed records'."""
    fake, state, saved = _install_fake_chromadb()
    try:
        with mock.patch("db.load_documents", return_value=[{
            "document_type": "other",
            "date": "2024-03-15",
            "medications": [], "lab_results": [], "allergies_noted": [],
            "clinical_notes": None, "overall_confidence": 0.0,
            "_source": {"file": "misc.pdf"},
        }]):
            out = retrieval.answer_question("anon_empty_docs", "what medication am I on?")
        assert "don't have enough information" in out["answer"]
        assert "no medications, lab results, clinical notes" in out["answer"], out["answer"]
        assert "no indexed records were found" not in out["answer"], out["answer"]
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_missing_supabase_chunks_table_raises_actionable_error():
    """VECTOR_STORE=supabase with a missing `chunks` table must raise an
    actionable VectorStoreSchemaError — not silently return 0 and claim
    'no indexed records'."""
    os.environ["VECTOR_STORE"] = "supabase"
    import importlib
    importlib.reload(vector_store)  # VECTOR_STORE is read at import time
    retrieval.vector_store = vector_store  # keep retrieval pointing at it

    class FakeTable:
        def select(self, *cols, **kw):
            raise RuntimeError("PGRST205: Could not find the table 'public.chunks' in the schema cache")

    try:
        with mock.patch("db._get_client", lambda: mock.Mock(table=lambda name: FakeTable())):
            try:
                retrieval.answer_question("anon_sb", "what medication am I on?")
            except vector_store.VectorStoreSchemaError as e:
                msg = str(e)
                assert "chunks" in msg and "supabase_schema.sql" in msg, msg
            else:
                raise AssertionError("expected VectorStoreSchemaError, got a no-info answer")
    finally:
        os.environ.pop("VECTOR_STORE", None)
        importlib.reload(vector_store)  # restore chroma default for other tests


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
