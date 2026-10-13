<!-- monitoring/README.md -->
# Monitoring configuration

These files are mounted into the Prometheus and Grafana containers. Nothing here is built into an image.

| File | Purpose |
|---|---|
| `prometheus/prometheus.yml` | Which services to scrape, and how often |
| `prometheus/alerts.yml` | Alert rules |
| `grafana/provisioning/datasources/prometheus.yml` | Connects Grafana to Prometheus |
| `grafana/provisioning/dashboards/dashboards.yml` | Tells Grafana where dashboard files are |
| `grafana/dashboards/pipeline-health.json` | The "Pipeline health" dashboard |

After editing a Prometheus file: `docker compose restart prometheus`.
Dashboard JSON changes are picked up by Grafana within 30 seconds.
