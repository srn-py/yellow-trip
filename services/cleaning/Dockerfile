# services/cleaning/Dockerfile
# Image for the cleaning service. Build context is the REPO ROOT.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/cleaning/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/cleaning/cleaning_service ./cleaning_service

RUN useradd --uid 1000 --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "cleaning_service.main:app", "--host", "0.0.0.0", "--port", "8000"]