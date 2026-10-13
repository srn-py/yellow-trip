# services/airflow/Dockerfile
# Airflow with our DAGs baked in, for production. (Development mounts the DAG folder instead.)
# Build context is the REPO ROOT.
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}

COPY --chown=airflow:0 airflow/dags /opt/airflow/dags