<!-- services/dashboard/README.md -->
# Dashboard

**Job:** an interactive page to explore the taxi data. It reads **only** from the analytics API
(`ANALYTICS_URL`), never from the warehouse.

URL: http://localhost:8501

| File | Responsibility |
|---|---|
| `dashboard_app/app.py` | The Streamlit page: filters, KPIs, tabs |
| `dashboard_app/api_client.py` | Calls the analytics API, turns failures into readable errors |
| `dashboard_app/charts.py` | Builds the Plotly charts from tables (no Streamlit inside, so it is testable) |
| `dashboard_app/flows.py` | The Streamlit page: filters, KPIs, tabs |
| `dashboard_app/views/how_it_works.py` | The Streamlit page: filters, KPIs, tabs |

Answers are cached for 5 minutes. Use **Refresh data** in the sidebar after loading new months.
