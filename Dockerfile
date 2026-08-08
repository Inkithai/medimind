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

# Install system dependencies needed by pymupdf and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./

# The container listens on 8000; the hosting platform maps this to its port
EXPOSE 8000

# Production: no --reload, bind to 0.0.0.0
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
