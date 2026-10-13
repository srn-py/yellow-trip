# airflow/dags/taxi_pipeline/alerts.py
"""What happens when a task fails.

For now an alert is a clear, easy-to-find log message. Because the function is passed to every
task as its `on_failure_callback`, it is the single place to extend later: send an email
(Airflow has SMTP support), post to Slack, or write to a monitoring system (Milestone 7).
"""

import logging

logger = logging.getLogger("airflow.task")


def notify_failure(context: dict) -> None:
    """Log a readable alert for a task that has failed for good (all retries used up).

    Must never raise, because an error inside an alert would hide the original problem.

    Args:
        context: The context Airflow passes to failure callbacks.
    """
    try:
        task_instance = context.get("task_instance") or context.get("ti")
        logger.error(
            "PIPELINE ALERT | dag=%s task=%s run=%s attempt=%s | %s",
            getattr(task_instance, "dag_id", "?"),
            getattr(task_instance, "task_id", "?"),
            getattr(task_instance, "run_id", "?"),
            getattr(task_instance, "try_number", "?"),
            context.get("exception"),
        )
    except Exception:  # an alert must not fail
        logger.exception("Could not build the failure alert")
