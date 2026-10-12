# services/ingestion/Dockerfile
# Recipe for building the ingestion service image.
# The build context is the REPO ROOT (see docker-compose.yml) so we can copy
# both `shared/` and this service's code.

# Small official Python image.
FROM python:3.12-slim

# PYTHONUNBUFFERED: print logs immediately. PYTHONDONTWRITEBYTECODE: no .pyc clutter.
# PYTHONPATH=/app: lets `import shared` and `import ingestion_service` work.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies FIRST. Docker caches each step, so code edits do not
# re-install libraries unless requirements.txt itself changed.
COPY services/ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy our code.
COPY shared ./shared
COPY services/ingestion/ingestion_service ./ingestion_service

# Run as a normal user (not root): safer. UID 1000 matches the first user on most
# Linux machines so files in the mounted drop-zone folder stay accessible.
RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /data/dropzone /data/registry \
    && chown -R appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "ingestion_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
