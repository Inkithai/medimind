# ============================================================
# MediMind Backend — Production Dockerfile
# ============================================================
# This image contains ONLY the FastAPI backend.
# Frontend is deployed separately to Vercel (not included here).
#
# Build:   docker build -t medimind-backend .
# Run:     docker run -p 8000:8000 --env-file backend/.env medimind-backend
# ============================================================

FROM python:3.10-slim

WORKDIR /app

# System deps: compilers for wheels, Tesseract for the optional OCR pre-pass.
# libglib/libgl package names changed on Debian Trixie (python:3.13-slim);
# pick whichever name exists so a failed apt-get does not leave dpkg unhappy.
RUN apt-get update && \
    GLIB_PKG=$(apt-cache show libglib2.0-0t64 >/dev/null 2>&1 && echo libglib2.0-0t64 || echo libglib2.0-0) && \
    GL_PKG=$(apt-cache show libgl1 >/dev/null 2>&1 && echo libgl1 || echo libgl1-mesa-glx) && \
    apt-get install -y --no-install-recommends \
        build-essential \
        tesseract-ocr \
        tesseract-ocr-eng \
        "$GLIB_PKG" \
        "$GL_PKG" \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Honor $PORT (Railway/Render/Fly) and default to 8000 for local docker run.
EXPOSE 8000

# Production: no --reload, bind to 0.0.0.0. Shell form so ${PORT} expands.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
