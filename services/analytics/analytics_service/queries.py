# services/analytics/analytics_service/queries.py
"""All SQL of the analytics API, in one place.

Rules that keep this safe:
* Values (dates, boroughs, limits...) are ALWAYS passed as `%s` parameters, never pasted into the text.
* The only text spliced into SQL are column and table names written in this file.
* Each query starts with a `-- q:name` comment: it shows up in the PostgreSQL logs, and tests use it.

Every function returns `(sql, params)`.

The queries read two aggregate tables built by dbt:
* `trip_summary`: per pickup date, hour, borough, airport flag and payment type (additive sums)
* `route_summary`: per month, pickup zone and drop-off zone
Averages are computed here as sum / count, which stays correct for any combination of filters.
"""

from dataclasses import dataclass
from datetime import date

TRIP_SUMMARY = "analytics.trip_summary"
ROUTE_SUMMARY = "analytics.route_summary"


@dataclass(frozen=True)
class Filters:
    """The filters a caller may apply.

    Attributes:
        start: First pickup date (inclusive).
        end: Last pickup date (inclusive).
        boroughs: Pickup boroughs to keep (empty = all).
        payment_types: Payment type IDs to keep (empty = all).
    """

    start: date | None = None
    end: date | None = None
    boroughs: tuple[str, ...] = ()
    payment_types: tuple[int, ...] = ()


def where_clause(filters: Filters) -> tuple[str, list]:
    """Build the WHERE clause for queries on `trip_summary`.

    Args:
        filters: The filters to apply.

    Returns:
        (clause, params). The clause is empty, or starts with " WHERE ".
    """
    parts: list[str] = []
    params: list = []
    if filters.start:
        parts.append("date >= %s")
        params.append(filters.start)
    if filters.end:
        parts.append("date <= %s")
        params.append(filters.end)
    if filters.boroughs:
        parts.append("pickup_borough = ANY(%s)")
        params.append(list(filters.boroughs))
    if filters.payment_types:
        parts.append("payment_type_key = ANY(%s)")
        params.append(list(filters.payment_types))
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


def route_where_clause(filters: Filters) -> tuple[str, list]:
    """Build the WHERE clause for queries on `route_summary` (month grain).

    The date range becomes a range of whole months. The payment type filter does not apply
    (the table has no payment type). The borough filter applies to the pickup borough.

    Args:
        filters: The filters to apply.

    Returns:
        (clause, params). The clause is empty, or starts with " WHERE ".
    """
    parts: list[str] = []
    params: list = []
    if filters.start:
        parts.append("month_key >= %s")
        params.append(filters.start.year * 100 + filters.start.month)
    if filters.end:
        parts.append("month_key <= %s")
        params.append(filters.end.year * 100 + filters.end.month)
    if filters.boroughs:
        parts.append("pickup_borough = ANY(%s)")
        params.append(list(filters.boroughs))
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


# ---- metadata (what can the dashboard offer in its filters?) ---------------------
META_DATES = f"-- q:meta_dates\nSELECT min(date) AS date_min, max(date) AS date_max FROM {TRIP_SUMMARY}"
META_MONTHS = f"-- q:meta_months\nSELECT DISTINCT to_char(date, 'YYYY-MM') AS month FROM {TRIP_SUMMARY} ORDER BY 1"
META_BOROUGHS = f"-- q:meta_boroughs\nSELECT DISTINCT pickup_borough AS borough FROM {TRIP_SUMMARY} ORDER BY 1"
META_PAYMENTS = (
    f"-- q:meta_payments\nSELECT DISTINCT payment_type_key AS id, payment_type_name AS name "
    f"FROM {TRIP_SUMMARY} ORDER BY 1"
)
ZONES = (
    "-- q:zones\nSELECT zone_key AS zone_id, zone, borough, is_airport FROM analytics.dim_zone ORDER BY borough, zone"
)


def kpis_query(filters: Filters) -> tuple[str, list]:
    """Headline numbers (sums; the API turns them into averages)."""
    where, params = where_clause(filters)
    sql = f"""-- q:kpis
SELECT
    coalesce(sum(trips), 0)::bigint AS trips,
    coalesce(sum(total_revenue), 0)::float8 AS total_revenue,
    coalesce(sum(fare_revenue), 0)::float8 AS fare_revenue,
    coalesce(sum(tip_revenue), 0)::float8 AS tip_revenue,
    coalesce(sum(total_distance_miles), 0)::float8 AS total_distance_miles,
    coalesce(sum(total_duration_minutes), 0)::float8 AS total_duration_minutes,
    coalesce(sum(trips) FILTER (WHERE pickup_is_airport), 0)::bigint AS airport_trips
FROM {TRIP_SUMMARY}{where}"""
    return sql, params


def daily_query(filters: Filters) -> tuple[str, list]:
    """Trips and revenue per pickup day."""
    where, params = where_clause(filters)
    sql = f"""-- q:daily
SELECT
    date,
    sum(trips)::bigint AS trips,
    sum(total_revenue)::float8 AS total_revenue,
    (sum(fare_revenue) / nullif(sum(trips), 0))::float8 AS avg_fare
FROM {TRIP_SUMMARY}{where}
GROUP BY date
ORDER BY date"""
    return sql, params


def heatmap_query(filters: Filters) -> tuple[str, list]:
    """Trips by weekday (1 = Monday) and hour of day."""
    where, params = where_clause(filters)
    sql = f"""-- q:heatmap
SELECT
    extract(isodow FROM date)::int AS day_of_week,
    hour_of_day,
    sum(trips)::bigint AS trips
FROM {TRIP_SUMMARY}{where}
GROUP BY 1, 2
ORDER BY 1, 2"""
    return sql, params


def payment_query(filters: Filters) -> tuple[str, list]:
    """Trips, average fare and tipping per payment type."""
    where, params = where_clause(filters)
    sql = f"""-- q:payment
SELECT
    payment_type_key AS payment_type_id,
    payment_type_name AS payment_type,
    sum(trips)::bigint AS trips,
    sum(total_revenue)::float8 AS total_revenue,
    (sum(fare_revenue) / nullif(sum(trips), 0))::float8 AS avg_fare,
    (100.0 * sum(tip_revenue) / nullif(sum(fare_revenue), 0))::float8 AS tip_pct_of_fare,
    (100.0 * sum(trips_with_tip) / nullif(sum(trips), 0))::float8 AS pct_trips_with_tip
FROM {TRIP_SUMMARY}{where}
GROUP BY 1, 2
ORDER BY trips DESC"""
    return sql, params


def borough_query(filters: Filters) -> tuple[str, list]:
    """Trips and revenue per pickup borough."""
    where, params = where_clause(filters)
    sql = f"""-- q:borough
SELECT
    pickup_borough AS borough,
    sum(trips)::bigint AS trips,
    sum(total_revenue)::float8 AS total_revenue,
    (sum(fare_revenue) / nullif(sum(trips), 0))::float8 AS avg_fare
FROM {TRIP_SUMMARY}{where}
GROUP BY 1
ORDER BY trips DESC"""
    return sql, params


def airports_query(filters: Filters) -> tuple[str, list]:
    """Airport pickups versus all other pickups."""
    where, params = where_clause(filters)
    sql = f"""-- q:airports
SELECT
    pickup_is_airport AS is_airport,
    sum(trips)::bigint AS trips,
    sum(total_revenue)::float8 AS total_revenue,
    (sum(fare_revenue) / nullif(sum(trips), 0))::float8 AS avg_fare,
    (sum(total_distance_miles) / nullif(sum(trips), 0))::float8 AS avg_distance_miles
FROM {TRIP_SUMMARY}{where}
GROUP BY 1
ORDER BY 1 DESC"""
    return sql, params


def airports_daily_query(filters: Filters) -> tuple[str, list]:
    """Per day: airport pickups and their share of all pickups."""
    where, params = where_clause(filters)
    sql = f"""-- q:airports_daily
SELECT
    date,
    sum(trips)::bigint AS total_trips,
    coalesce(sum(trips) FILTER (WHERE pickup_is_airport), 0)::bigint AS airport_trips,
    coalesce(100.0 * sum(trips) FILTER (WHERE pickup_is_airport) / nullif(sum(trips), 0), 0)::float8
        AS airport_share_pct
FROM {TRIP_SUMMARY}{where}
GROUP BY date
ORDER BY date"""
    return sql, params


def top_zones_query(filters: Filters, by: str, limit: int) -> tuple[str, list]:
    """Busiest zones by pickups or drop-offs.

    Args:
        filters: Filters (month grain; borough means pickup borough).
        by: "pickup" or "dropoff".
        limit: How many zones to return.

    Returns:
        (sql, params).
    """
    zone_col, borough_col = (
        ("dropoff_zone", "dropoff_borough") if by == "dropoff" else ("pickup_zone", "pickup_borough")
    )
    where, params = route_where_clause(filters)
    sql = f"""-- q:top_zones
SELECT
    {zone_col} AS zone,
    {borough_col} AS borough,
    sum(trips)::bigint AS trips,
    sum(total_revenue)::float8 AS total_revenue
FROM {ROUTE_SUMMARY}{where}
GROUP BY 1, 2
ORDER BY trips DESC
LIMIT %s"""
    return sql, [*params, limit]


def top_routes_query(filters: Filters, limit: int) -> tuple[str, list]:
    """Busiest pickup to drop-off zone pairs."""
    where, params = route_where_clause(filters)
    sql = f"""-- q:top_routes
            SELECT
                pickup_zone,
                dropoff_zone,
                sum(trips)::bigint AS trips,
                (sum(fare_revenue) / nullif(sum(trips), 0))::float8 AS avg_fare,
                (sum(total_distance_miles) / nullif(sum(trips), 0))::float8 AS avg_distance_miles
            FROM {ROUTE_SUMMARY}{where}
            GROUP BY 1, 2
            ORDER BY trips DESC
            LIMIT %s
        """
    return sql, [*params, limit]


def zone_hourly_query(zone_id: int) -> tuple[str, list]:
    """Weekday-by-hour demand of one pickup zone (all loaded months together)."""
    sql = """-- q:zone_hourly
            SELECT day_of_week, hour_of_day, trips::bigint AS trips
            FROM analytics.hourly_demand_by_zone
            WHERE pickup_zone_key = %s
            ORDER BY day_of_week, hour_of_day
        """
    return sql, [zone_id]
