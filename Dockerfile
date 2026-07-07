# ============================================================
# VaultMind — Multi-stage Docker build (CPU-only, no Metal GPU)
# ============================================================
# NOTE: Metal GPU acceleration is NOT available in Docker.
# For best performance, run natively on macOS Apple Silicon.
# This image is intended for CI, testing, and Linux deployment.
# ============================================================

FROM python:3.12-slim AS builder

# Build dependencies for llama-cpp-python (CPU)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

# Install Python deps; compile llama-cpp-python for CPU only
RUN pip install --no-cache-dir --prefix=/install \
    numpy==1.26.4 \
    huggingface-hub==0.23.0 \
    psutil==5.9.8 \
    fastapi==0.111.0 \
    uvicorn==0.30.1 \
    python-multipart==0.0.9 \
    openai==1.30.1 \
    python-docx==1.2.0 \
    && CMAKE_ARGS="-DGGML_BLAS=OFF" \
       pip install --no-cache-dir --prefix=/install llama-cpp-python==0.2.76

# -----------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL maintainer="VaultMind Contributors"
LABEL description="Privacy-first local RAG system with Knowledge Graph"

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY ingestion.py indexing.py inference.py formatter.py \
     server.py cli.py ./
COPY templates/ ./templates/

# Create directories for runtime data
RUN mkdir -p workspaces models raw_inputs

# Non-root user for security
RUN useradd --create-home --shell /bin/bash vaultmind \
    && chown -R vaultmind:vaultmind /app
USER vaultmind

# Volumes for persistent data
VOLUME ["/app/workspaces", "/app/models"]

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/')" || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "server:app"]
CMD ["--host", "0.0.0.0", "--port", "8001"]
