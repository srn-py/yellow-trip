<!-- services/analytics/README.md -->
# Analytics API

**Job:** answer analytical questions from the warehouse. It is the **only** thing that reads the
`analytics` schema for dashboards. Connections are read-only and queries time out after 30 seconds.

Common filters (all optional): `start`, `end` (pickup dates, YYYY-MM-DD), `borough` (repeat for several),
`payment_type` (repeat for several).

| Endpoint | Returns |
|---|---|
| `GET /meta/filters` | Available dates, months, boroughs, payment types |
| `GET /kpis` | Headline numbers |
| `GET /trips/daily` | Trips and revenue per day |
| `GET /demand/heatmap` | Trips by weekday and hour |
| `GET /breakdown/payment-type` | Trips, average fare and tipping by payment type |
| `GET /breakdown/borough` | Trips and revenue by pickup borough |
| `GET /airports`, `GET /airports/daily` | Airport vs other pickups; daily airport share |
| `GET /zones/top?by=pickup\|dropoff&limit=10` | Busiest zones (month grain, ignores payment filter) |
| `GET /routes/top?limit=10` | Busiest pickup to drop-off routes (month grain) |
| `GET /zones`, `GET /demand/zone-hourly?zone_id=132` | Zone list; weekday-hour demand of one zone |
| `GET /health`, `GET /health/ready` | Liveness / readiness |

Interactive docs: http://localhost:8300/docs

## Code map (`analytics_service/`)

| File | Responsibility |
|---|---|
| `database.py` | Pooled, read-only PostgreSQL access |
| `queries.py` | Filters and all SQL (parameterised) |
| `schemas.py` | Response shapes |
| `routes.py` | HTTP endpoints and error handling |
| `main.py` | Start-up and health checks |