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
# Install system dependencies needed by pymupdf and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
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
# The container listens on 8000; the hosting platform maps this to its port
EXPOSE 8000
# Production: no --reload, bind to 0.0.0.0
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

