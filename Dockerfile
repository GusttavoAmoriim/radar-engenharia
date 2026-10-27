# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo RADAR_DB=/data/radar.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Test image: `docker build --target test -t radar-tests . && docker run --rm radar-tests`
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app/ ./app/
COPY static/ ./static/
COPY sources.yaml portais.yaml ./
COPY scripts/ ./scripts/
COPY tests/ ./tests/
CMD ["sh", "-c", "ruff check . && ruff format --check . && python -m pytest"]

# Production image (default target)
FROM base AS runtime
RUN useradd -r -u 10001 radar && mkdir -p /data && chown radar:radar /data
COPY app/ ./app/
COPY static/ ./static/
COPY sources.yaml portais.yaml ./
USER radar
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
