# tests/test_analytics_queries.py
from datetime import date

from analytics_service import queries
from analytics_service.queries import Filters, route_where_clause, where_clause


def test_no_filters_gives_no_where_clause():
    assert where_clause(Filters()) == ("", [])


def test_all_filters_become_placeholders_in_order():
    filters = Filters(date(2024, 1, 1), date(2024, 1, 31), ("Queens", "Bronx"), (1, 2))
    clause, params = where_clause(filters)
    assert clause == (" WHERE date >= %s AND date <= %s AND pickup_borough = ANY(%s) AND payment_type_key = ANY(%s)")
    assert params == [date(2024, 1, 1), date(2024, 1, 31), ["Queens", "Bronx"], [1, 2]]


def test_values_are_never_pasted_into_the_sql_text():
    clause, _ = where_clause(Filters(boroughs=("Robert'); DROP TABLE x;--",)))
    assert "DROP" not in clause


def test_route_filters_use_whole_months_and_ignore_payment_type():
    filters = Filters(date(2024, 1, 15), date(2024, 3, 20), ("Queens",), (1,))
    clause, params = route_where_clause(filters)
    assert clause == " WHERE month_key >= %s AND month_key <= %s AND pickup_borough = ANY(%s)"
    assert params == [202401, 202403, ["Queens"]]


def test_kpis_query_reads_the_summary_and_carries_filter_params():
    sql, params = queries.kpis_query(Filters(boroughs=("Queens",)))
    assert "-- q:kpis" in sql
    assert "analytics.trip_summary WHERE pickup_borough = ANY(%s)" in sql
    assert params == [["Queens"]]


def test_heatmap_query_groups_by_weekday_and_hour():
    sql, _ = queries.heatmap_query(Filters())
    assert "isodow" in sql
    assert "GROUP BY 1, 2" in sql


def test_top_zones_pickup_and_dropoff_use_different_columns_and_append_the_limit():
    pickup_sql, pickup_params = queries.top_zones_query(Filters(start=date(2024, 2, 1)), "pickup", 7)
    dropoff_sql, _ = queries.top_zones_query(Filters(), "dropoff", 7)
    assert "pickup_zone AS zone" in pickup_sql
    assert "dropoff_zone AS zone" in dropoff_sql
    assert pickup_params == [202402, 7]


def test_top_routes_and_zone_hourly_parameters():
    _, route_params = queries.top_routes_query(Filters(), 5)
    _, zone_params = queries.zone_hourly_query(132)
    assert route_params == [5]
    assert zone_params == [132]
