"""Regression tests for the Chroma client wiring.

Covers the production 500: `retrieval._get_chroma_client()` referenced
`chromadb` without ever importing it (`from chromadb.utils... import X`
only binds X, never the package name), so every Chroma-path call raised
"NameError: name 'chromadb' is not defined" — silently swallowed into
index_error on uploads, and an unhandled 500 on /api/v1/qa.

Verifies:
  1. _get_chroma_client builds ONE cached PersistentClient and retrieval
     delegates to it.
  2. A genuinely missing chromadb raises an actionable RuntimeError
     ("pip install chromadb" / VECTOR_STORE=supabase) — never a bare
     NameError.
  3. The full chroma path works end-to-end (index -> answer) with a fake
     chromadb, proving the wiring the NameError broke.
  4. A never-indexed patient gets the graceful _NO_INFO_ANSWER (200)
     instead of an exception.
"""
import os
import sys
import json
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ.pop("VECTOR_STORE", None)  # default = chroma

import vector_store
import retrieval

TIMELINE = {
    "visits": [{"date": "2024-03-15", "clinical_notes": None, "_source": {"file": "rx.jpg"}}],
    "medications_timeline": [{
        "name": "Paracetamol", "ingredients": ["Paracetamol"], "dosage": "500 mg",
        "frequency": "3x daily", "duration": "5 days", "dosage_value": 500,
        "dosage_unit": "mg", "frequency_per_day": 3, "is_as_needed": False,
        "confidence": 0.95, "date": "2024-03-15", "source_file": "rx.jpg",
    }],
    "lab_results_timeline": [{
        "test_name": "HbA1c", "value": "6.1", "unit": "%", "reference_range": "<5.7",
        "flag": "high", "confidence": 0.9, "date": "2024-03-15", "source_file": "lab.pdf",
    }],
    "known_allergies": ["Penicillin"],
}

ANSWER_JSON = json.dumps({
    "answer": "You are taking Paracetamol 500 mg three times daily.",
    "confidence": 0.95,
    "sources": [{"date": "2024-03-15", "source_file": "rx.jpg", "page": 1}],
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
            state["clients"].append(self)

        def get_or_create_collection(self, name, metadata=None):
            return state["collections"].setdefault(name, FakeCollection(name))

        def get_collection(self, name):
            if name not in state["collections"]:
                raise ValueError(f"Collection {name} does not exist")
            return state["collections"][name]

        def delete_collection(self, name):
            state["collections"].pop(name, None)

    fake_module = types.ModuleType("chromadb")
    fake_module.PersistentClient = FakeClient
    return fake_module, state


def _restore_chromadb(saved):
    if saved is None:
        sys.modules.pop("chromadb", None)
    else:
        sys.modules["chromadb"] = saved


def test_client_built_once_and_shared():
    fake, state = _make_fake_chromadb()
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = fake
    vector_store._chroma_client = None
    try:
        c1 = vector_store._get_chroma_client()
        c2 = vector_store._get_chroma_client()
        c3 = retrieval._get_chroma_client()  # delegates to the same one
        assert c1 is c2 is c3
        assert len(state["clients"]) == 1, "PersistentClient must be constructed once per process"
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_missing_chromadb_is_actionable_runtime_error():
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = None  # makes `import chromadb` raise ImportError
    vector_store._chroma_client = None
    try:
        vector_store._get_chroma_client()
    except RuntimeError as e:
        msg = str(e)
        assert "pip install" in msg, msg
        assert "VECTOR_STORE=supabase" in msg, msg
    except NameError as e:
        raise AssertionError(f"regressed to bare NameError: {e}")
    else:
        raise AssertionError("expected RuntimeError when chromadb missing")
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_index_then_answer_over_chroma_path():
    fake, _state = _make_fake_chromadb()
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = fake
    vector_store._chroma_client = None
    try:
        with mock.patch.object(retrieval, "embed_texts",
                               side_effect=lambda texts: [[0.1] * 384 for _ in texts]), \
             mock.patch.object(retrieval, "_completion_resilient", return_value=ANSWER_JSON):
            n = retrieval.index_patient_timeline("anon_qa", TIMELINE)
            # 1 medication + 1 lab result + 1 allergy chunk (no clinical notes)
            assert n == 3, n
            out = retrieval.answer_question("anon_qa", "what medication am I on?")
        assert out["answer"].startswith("You are taking Paracetamol")
        assert out["confidence"] == 0.95
        assert "directly" in out["confidence_reason"]
        assert out["sources"] == [{"date": "2024-03-15", "source_file": "rx.jpg", "page": 1}]
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_reindex_does_not_leave_stale_chunks_after_order_shift():
    """Re-indexing a longer, re-sorted timeline must replace the previous
    collection rather than accumulating leftover index-based ids."""
    fake, state = _make_fake_chromadb()
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = fake
    vector_store._chroma_client = None
    try:
        with mock.patch.object(retrieval, "embed_texts",
                               side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
            n1 = retrieval.index_patient_timeline("anon_shift", TIMELINE)
            assert n1 == 3
            older = {
                **TIMELINE,
                "medications_timeline": [
                    {
                        "name": "Aspirin", "ingredients": ["Aspirin"], "dosage": "75 mg",
                        "frequency": "daily", "duration": None, "dosage_value": 75,
                        "dosage_unit": "mg", "frequency_per_day": 1, "is_as_needed": False,
                        "confidence": 0.9, "date": "2023-01-01", "source_file": "old.pdf",
                    },
                    *TIMELINE["medications_timeline"],
                ],
            }
            n2 = retrieval.index_patient_timeline("anon_shift", older)
        # 2 medications + 1 lab + 1 allergy
        assert n2 == 4
        assert state["collections"]["anon_shift"].count() == 4, (
            "stale chunks from the previous index survived re-index"
        )
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


def test_never_indexed_patient_gets_graceful_no_info():
    fake, _state = _make_fake_chromadb()
    saved = sys.modules.get("chromadb")
    sys.modules["chromadb"] = fake
    vector_store._chroma_client = None
    try:
        out = retrieval.answer_question("anon_brand_new", "anything?")
        assert "don't have enough information" in out["answer"]
        assert out["confidence"] == 0.0 and out["sources"] == []
    finally:
        vector_store._chroma_client = None
        _restore_chromadb(saved)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
