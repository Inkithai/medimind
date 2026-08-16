"""Offline tests for the "no indexable content" indexing fix.

Verifies that index_patient_timeline() returns 0 (and does NOT touch
Chroma) when a timeline has nothing retrievable, so upload callers stop
reporting indexed=True for an empty index.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"

import retrieval


EMPTY_TIMELINE = {
    "visits": [{"document_type": "other", "clinical_notes": None}],
    "medications_timeline": [],
    "lab_results_timeline": [],
    "known_allergies": [],
}

FULL_TIMELINE = {
    "visits": [],
    "medications_timeline": [
        {"name": "Paracetamol", "ingredients": ["Paracetamol"], "dosage": "500 mg",
         "dosage_value": 500, "dosage_unit": "mg", "frequency": "3x daily",
         "frequency_per_day": 3, "is_as_needed": False, "duration": "5 days",
         "date": "2024-01-01", "source_file": "rx1.pdf", "confidence": 0.95}
    ],
    "lab_results_timeline": [],
    "known_allergies": ["Penicillin"],
}


def test_empty_timeline_returns_zero():
    with mock.patch.object(retrieval, "_get_patient_collection") as get_collection, \
         mock.patch.object(retrieval, "embed_texts") as embed:
        count = retrieval.index_patient_timeline("anon_test", EMPTY_TIMELINE)
    assert count == 0
    get_collection.assert_not_called()
    embed.assert_not_called()


def test_full_timeline_returns_chunk_count():
    collection = mock.Mock()
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=collection), \
         mock.patch.object(retrieval.vector_store, "delete_collection"), \
         mock.patch.object(retrieval, "embed_texts", side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        count = retrieval.index_patient_timeline("anon_test", FULL_TIMELINE)
    # 1 medication chunk + 1 allergy chunk
    assert count == 2, count
    collection.upsert.assert_called_once()
    assert collection.upsert.call_args.kwargs["ids"]
    assert len(collection.upsert.call_args.kwargs["ids"]) == 2


def _many_medication_timeline(count):
    """A timeline whose medication list is large enough to span batches."""
    return {
        "visits": [],
        "medications_timeline": [
            {"name": f"Drug{i}", "ingredients": [f"Drug{i}"], "dosage": "500 mg",
             "dosage_value": 500, "dosage_unit": "mg", "frequency": "3x daily",
             "frequency_per_day": 3, "is_as_needed": False, "duration": "5 days",
             "date": "2024-01-01", "source_file": f"rx{i}.pdf", "confidence": 0.95}
            for i in range(count)
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    }


def test_indexing_streams_in_bounded_batches():
    """Regression for the Render OOM kill: indexing must embed and upsert in
    small batches instead of materialising every chunk's embedding at once.

    The old code called embed_texts() once with ALL chunk texts and then
    upserted every vector in a single call, so peak memory scaled with the
    size of the patient's record. Here 40 chunks with a batch size of 8 must
    produce 5 embed calls and 5 upserts, none larger than the batch size.
    """
    collection = mock.Mock()
    batch_sizes = []

    def fake_embed(texts):
        batch_sizes.append(len(texts))
        return [[0.1] * 384 for _ in texts]

    with mock.patch.object(retrieval, "_get_patient_collection", return_value=collection), \
         mock.patch.object(retrieval, "embed_texts", side_effect=fake_embed), \
         mock.patch.object(retrieval, "EMBEDDING_BATCH_SIZE", 8):
        count = retrieval.index_patient_timeline("anon_test", _many_medication_timeline(40))

    assert count == 40, count
    assert batch_sizes == [8, 8, 8, 8, 8], batch_sizes
    assert collection.upsert.call_count == 5, collection.upsert.call_count
    for call in collection.upsert.call_args_list:
        assert len(call.kwargs["ids"]) <= 8
        assert len(call.kwargs["embeddings"]) == len(call.kwargs["ids"])
        assert len(call.kwargs["documents"]) == len(call.kwargs["ids"])
        assert len(call.kwargs["metadatas"]) == len(call.kwargs["ids"])
    # Every chunk is written exactly once, with no duplicated ids.
    written = [i for call in collection.upsert.call_args_list for i in call.kwargs["ids"]]
    assert len(written) == 40 and len(set(written)) == 40


def test_collection_is_resolved_once_for_all_batches():
    """The Chroma collection handle (and therefore the client) must be
    reused across batches — re-resolving it per batch was a per-upload
    allocation of a whole new client in earlier versions."""
    collection = mock.Mock()
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=collection) as get_collection, \
         mock.patch.object(retrieval, "embed_texts", side_effect=lambda texts: [[0.1] * 8 for _ in texts]), \
         mock.patch.object(retrieval, "EMBEDDING_BATCH_SIZE", 4):
        retrieval.index_patient_timeline("anon_test", _many_medication_timeline(20))
    assert get_collection.call_count == 1, get_collection.call_count


def test_embedding_batch_size_env_is_clamped():
    """A misconfigured EMBEDDING_BATCH_SIZE must never disable batching."""
    with mock.patch.dict(os.environ, {"EMBEDDING_BATCH_SIZE": "0"}):
        assert retrieval._embedding_batch_size() == 1
    with mock.patch.dict(os.environ, {"EMBEDDING_BATCH_SIZE": "100000"}):
        assert retrieval._embedding_batch_size() == 256
    with mock.patch.dict(os.environ, {"EMBEDDING_BATCH_SIZE": "not-a-number"}):
        assert retrieval._embedding_batch_size() == 16
    with mock.patch.dict(os.environ, {"EMBEDDING_BATCH_SIZE": "32"}):
        assert retrieval._embedding_batch_size() == 32


def test_preload_embedding_model_is_a_noop_with_openai_key():
    """Startup preload must not try to build a local ONNX session (nor
    fail the app) when embeddings are served by OpenAI."""
    with mock.patch.object(retrieval, "_openai_embedding_client", object()), \
         mock.patch.object(retrieval, "_get_local_embedding_function") as get_local:
        assert retrieval.preload_embedding_model() is False
    get_local.assert_not_called()


def test_preload_embedding_model_never_raises():
    """A failed model download at startup must degrade to lazy loading,
    not crash the web process before it can serve /health."""
    with mock.patch.object(retrieval, "_openai_embedding_client", None), \
         mock.patch.object(retrieval, "_get_local_embedding_function",
                           side_effect=RuntimeError("no network")):
        assert retrieval.preload_embedding_model() is False


def test_onnx_cache_dir_override_is_applied():
    """ONNX_MODEL_CACHE_DIR must redirect Chroma's hardcoded ~/.cache path so
    the ~79 MB model can be baked into the image instead of downloaded during
    the first upload."""
    import tempfile
    from pathlib import Path

    class FakeModel:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = Path("/nonexistent/home/.cache/chroma")

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"ONNX_MODEL_CACHE_DIR": tmp}):
            retrieval._apply_onnx_cache_dir(FakeModel)
        expected = Path(tmp) / "all-MiniLM-L6-v2"
        assert FakeModel.DOWNLOAD_PATH == expected
        assert expected.is_dir()


def test_onnx_cache_dir_unset_leaves_default_and_never_raises():
    """No override configured -> Chroma keeps its own default, and a bad
    override must not be able to break indexing."""
    from pathlib import Path

    class FakeModel:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = Path("/default/path")

    env = {k: v for k, v in os.environ.items() if k != "ONNX_MODEL_CACHE_DIR"}
    with mock.patch.dict(os.environ, env, clear=True):
        retrieval._apply_onnx_cache_dir(FakeModel)
    assert FakeModel.DOWNLOAD_PATH == Path("/default/path")

    # Unwritable target: logged and ignored, never raised.
    with mock.patch.dict(os.environ, {"ONNX_MODEL_CACHE_DIR": "/proc/cannot/create"}):
        retrieval._apply_onnx_cache_dir(FakeModel)


def test_chunk_building_counts():
    chunks = retrieval.build_chunks_from_timeline("anon_test", FULL_TIMELINE)
    types = {c["metadata"]["chunk_type"] for c in chunks}
    assert types == {"medication", "allergy"}


def test_chunk_ids_are_stable_when_timeline_order_changes():
    """IDs must not include the list index — adding an older medication
    used to rename every subsequent chunk and leave the old ids behind."""
    older = {
        "name": "Aspirin", "ingredients": ["Aspirin"], "dosage": "75 mg",
        "dosage_value": 75, "dosage_unit": "mg", "frequency": "daily",
        "frequency_per_day": 1, "is_as_needed": False, "duration": None,
        "date": "2023-01-01", "source_file": "old.pdf", "confidence": 0.9,
    }
    first = retrieval.build_chunks_from_timeline("anon_test", FULL_TIMELINE)
    shifted = {
        **FULL_TIMELINE,
        "medications_timeline": [older, *FULL_TIMELINE["medications_timeline"]],
    }
    second = retrieval.build_chunks_from_timeline("anon_test", shifted)
    first_med_ids = {c["id"] for c in first if c["metadata"]["chunk_type"] == "medication"}
    second_med_ids = {c["id"] for c in second if c["metadata"]["chunk_type"] == "medication"}
    assert first_med_ids <= second_med_ids
    assert len(second_med_ids) == len(first_med_ids) + 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
