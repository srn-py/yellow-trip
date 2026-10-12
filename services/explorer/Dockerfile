# services/explorer/Dockerfile
# Image for the explorer: JupyterLab with DuckDB, pandas and Plotly.
# Build context is the REPO ROOT (see docker-compose.yml).

FROM python:3.12-slim

# PYTHONPATH=/app lets notebooks do `from shared.lake import ...`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/explorer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as a normal user; UID 1000 matches most Linux hosts so notebook files
# saved into the mounted folder stay editable on your machine.
RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /app/notebooks \
    && chown -R appuser /app/notebooks
USER appuser

# DuckDB reads S3 through its "httpfs" extension. Install it NOW (at build time)
# so notebooks never have to download anything while you work.
RUN python -c "import duckdb; duckdb.install_extension('httpfs')"

# Copy shared code (docker-compose also mounts ./shared over it for live editing).
COPY shared /app/shared

WORKDIR /app/notebooks
EXPOSE 8888

# The login token is read automatically from the JUPYTER_TOKEN environment variable.
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]
