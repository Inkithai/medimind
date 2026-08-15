"""Download the local ONNX embedding model at IMAGE BUILD time.

Why this exists
---------------
Chroma's default embedding function (all-MiniLM-L6-v2 via ONNX Runtime)
downloads a ~79 MB archive the first time it is used and extracts it into
``~/.cache/chroma/onnx_models``. On a fresh container that first use landed
in the middle of the first document upload: the download buffer, the
extracted model, the ONNX session and the freshly extracted document text
were all resident at once, which is how the 512 MB web service got
OOM-killed during the ``indexing`` stage.

Running this during ``docker build`` bakes the model into the image, so at
runtime the model is already on disk and only the (much smaller) ONNX
session is allocated.

Usage (see backend/Dockerfile):
    ONNX_MODEL_CACHE_DIR=/app/.cache/chroma python prefetch_embedding_model.py

Failure is non-fatal by design — a build running without network access
should still produce a working image; the model then downloads lazily at
runtime exactly as before.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    cache_dir = os.environ.get("ONNX_MODEL_CACHE_DIR", "").strip()
    try:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
    except Exception as exc:  # pragma: no cover - build-time only
        print(f"[prefetch] chromadb unavailable, skipping: {exc}")
        return 0

    if cache_dir:
        target = Path(cache_dir) / ONNXMiniLM_L6_V2.MODEL_NAME
        target.mkdir(parents=True, exist_ok=True)
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = target
        print(f"[prefetch] cache directory: {target}")

    try:
        embedder = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
    except TypeError:  # older chromadb builds
        embedder = ONNXMiniLM_L6_V2()
    except Exception as exc:  # pragma: no cover - build-time only
        print(f"[prefetch] could not construct embedder, skipping: {exc}")
        return 0

    try:
        # Actually exercise the model so the archive is downloaded and
        # extracted now rather than on the first user upload.
        vectors = embedder(["medimind embedding model warmup"])
        print(f"[prefetch] model ready, embedding dim={len(vectors[0])}")
    except Exception as exc:  # pragma: no cover - build-time only
        print(f"[prefetch] warmup failed (model will download at runtime): {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
