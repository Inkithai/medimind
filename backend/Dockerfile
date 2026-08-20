# ============================================================
# MediMind Backend — Production Dockerfile
# ============================================================
# This Dockerfile lives inside backend/ and builds ONLY the
# FastAPI backend. Frontend is deployed separately to Vercel.
#
# SnapDeploy settings:
#   Root Directory:  backend
#   Dockerfile Path: (leave empty — auto-detects this file)
#   Build Context:   (leave empty)
# ============================================================
FROM python:3.10-slim
WORKDIR /app
# System deps: compilers for wheels, Tesseract for the optional OCR pre-pass.
# libglib/libgl package names changed on Debian Trixie (python:3.13-slim);
# fall back to Bookworm names so this Dockerfile survives a base-image bump.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-eng \
    && (apt-get install -y --no-install-recommends libglib2.0-0t64 \
        || apt-get install -y --no-install-recommends libglib2.0-0) \
    && (apt-get install -y --no-install-recommends libgl1 \
        || apt-get install -y --no-install-recommends libgl1-mesa-glx \
        || true) \
    && rm -rf /var/lib/apt/lists/*
# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Copy all backend source code into the container
COPY . ./

# Bake the local ONNX embedding model (~79 MB, all-MiniLM-L6-v2) into the
# image. Without this it downloads on FIRST UPLOAD, inside the request, on
# top of the extracted document text — which is what OOM-killed the 512 MB
# web service during the indexing stage. Non-fatal if the build has no
# network: the model then falls back to downloading lazily at runtime.
ENV ONNX_MODEL_CACHE_DIR=/app/.cache/chroma
RUN python prefetch_embedding_model.py || true
# Honor $PORT (Railway/Render/Fly) and default to 8000 for local docker run.
EXPOSE 8000
# Production: no --reload, bind to 0.0.0.0. Shell form so ${PORT} expands.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]

