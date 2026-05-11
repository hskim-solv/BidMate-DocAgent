# BidMate-DocAgent demo API container.
#
# One-shot reviewer flow:
#   docker build -t bidmate-demo .
#   docker run --rm -p 8000:8000 bidmate-demo
#
# The entrypoint builds the index from data/raw on first start if it is
# missing, then launches uvicorn. Mount a volume on /app/data/index to
# persist the index across runs.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BIDMATE_INDEX_DIR=/app/data/index \
    EMBEDDING_BACKEND=hashing \
    BIDMATE_TRACE_BACKEND=none

WORKDIR /app

# OS deps needed by opencv-python-headless / pymupdf / pytesseract.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy only the code/data needed at runtime. tests/, benchmarks/, eval/
# are intentionally left out of the image to keep it small — they are
# part of the CLI evaluation flow, not the demo surface.
COPY rag_core.py rag_synthesis.py rag_observability.py ingestion.py visual_ingestion.py app.py ./
COPY api/ ./api/
COPY demo/ ./demo/
COPY scripts/build_index.py ./scripts/build_index.py
COPY data/raw/ ./data/raw/
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
