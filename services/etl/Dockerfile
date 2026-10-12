# services/etl/Dockerfile
# Image for the ETL service (loader + dbt). Build context is the REPO ROOT.

FROM python:3.12-slim

# DO_NOT_TRACK / DBT_SEND_ANONYMOUS_USAGE_STATS: stop dbt from sending usage statistics.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DO_NOT_TRACK=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false

WORKDIR /app

COPY services/etl/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/etl/etl_service ./etl_service
# A copy of the dbt project is baked in; docker-compose mounts ./dbt over it for development.
COPY dbt ./dbt

RUN useradd --uid 1000 --create-home appuser && chown -R appuser /app/dbt
USER appuser

EXPOSE 8000
CMD ["uvicorn", "etl_service.main:app", "--host", "0.0.0.0", "--port", "8000"]