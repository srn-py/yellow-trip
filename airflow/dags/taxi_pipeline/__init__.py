# airflow/dags/taxi_pipeline/__init__.py
"""Helper code for the platform's Airflow DAGs.

Nothing in this package imports Airflow. That keeps it easy to test with plain pytest and
means a DAG file stays short: it only describes *what runs in which order*, while this
package knows *how* to talk to each service.
"""
