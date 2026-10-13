# services/quality/Dockerfile
# Image for the data-quality service. Build context is the REPO ROOT.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/quality/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/quality/quality_service ./quality_service

RUN useradd --uid 1000 --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "quality_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
