# services/analytics/Dockerfile
# Image for the analytics API. Build context is the REPO ROOT.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/analytics/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/analytics/analytics_service ./analytics_service

RUN useradd --uid 1000 --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "analytics_service.main:app", "--host", "0.0.0.0", "--port", "8000"]