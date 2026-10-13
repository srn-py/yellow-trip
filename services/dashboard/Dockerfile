# services/dashboard/Dockerfile
# Image for the Streamlit dashboard. Build context is the REPO ROOT.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/dashboard/dashboard_app ./dashboard_app
COPY services/dashboard/.streamlit ./.streamlit

RUN useradd --uid 1000 --create-home appuser
USER appuser

EXPOSE 8501
CMD ["streamlit", "run", "dashboard_app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
