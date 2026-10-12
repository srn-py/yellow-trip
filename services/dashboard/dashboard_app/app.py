# services/dashboard/dashboard_app/app.py
"""The NYC Yellow Taxi dashboard (Streamlit).

Streamlit re-runs this whole file from top to bottom every time you touch a widget. Two things make
that fast: `st.cache_data` remembers API answers for 5 minutes, and the API itself reads small
pre-aggregated tables. All data comes from the analytics API; this file never touches a database.
"""

import os
from datetime import date

import pandas as pd
import streamlit as st

from dashboard_app import charts
from dashboard_app.api_client import AnalyticsApiError, AnalyticsClient, FilterSelection

st.set_page_config(page_title="NYC Taxi Dashboard", page_icon="🚕", layout="wide")

# Halve the default metric value font size (default is ~2.25rem → 1.125rem).
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 1.125rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_client() -> AnalyticsClient:
    """Create the API client once and reuse it across reruns."""
    return AnalyticsClient(os.environ.get("ANALYTICS_URL", "http://analytics:8000"))


@st.cache_data(ttl=300, show_spinner=False)
def fetch(path: str, start, end, boroughs: tuple, payment_types: tuple, extra: tuple = ()):
    """Ask the API a question; the answer is cached for 5 minutes.

    Arguments are plain tuples and strings, so Streamlit can use them as the cache key.
    """
    selection = FilterSelection(start, end, boroughs, payment_types)
    return get_client().get(path, selection, dict(extra))


def frame(path: str, selection: tuple, **extra) -> pd.DataFrame:
    """Fetch a list endpoint as a table.

    Args:
        path: Endpoint path.
        selection: (start, end, boroughs, payment_types).
        **extra: Extra query parameters, for example `limit=10`.

    Returns:
        The answer as a DataFrame (empty if there are no rows).
    """
    return pd.DataFrame(fetch(path, *selection, extra=tuple(sorted(extra.items()))))


def money(value: float | None) -> str:
    """Format a dollar amount."""
    return "n/a" if value is None else f"${value:,.2f}"


def whole(value: float | None) -> str:
    """Format a whole number with thousands separators."""
    return "n/a" if value is None else f"{value:,.0f}"


def sidebar_filters(meta: dict) -> tuple:
    """Draw the filters in the sidebar and return the selection.

    Args:
        meta: Answer of `/meta/filters`.

    Returns:
        (start, end, boroughs, payment_types), ready to pass to `fetch`.
    """
    first, last = date.fromisoformat(meta["date_min"]), date.fromisoformat(meta["date_max"])
    st.sidebar.header("Filters")
    picked = st.sidebar.date_input("Pickup dates", value=(first, last), min_value=first, max_value=last)
    if not isinstance(picked, (tuple, list)) or len(picked) != 2:
        st.info("Pick an end date to continue.")
        st.stop()

    boroughs = tuple(st.sidebar.multiselect("Pickup borough (empty = all)", options=meta["boroughs"]))
    names = {item["id"]: item["name"] for item in meta["payment_types"]}
    payments = tuple(
        st.sidebar.multiselect(
            "Payment type (empty = all)",
            options=list(names),
            format_func=lambda payment_id: names[payment_id],
        )
    )
    if st.sidebar.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption("Answers are cached for 5 minutes. Use Refresh after loading new months.")
    return picked[0].isoformat(), picked[1].isoformat(), boroughs, payments


def show_kpis(selection: tuple) -> bool:
    """Show the headline numbers.

    Args:
        selection: The sidebar selection.

    Returns:
        False if no trips match (so the caller can stop).
    """
    kpis = fetch("/kpis", *selection)
    if kpis["trips"] == 0:
        st.warning("No trips match these filters. Widen the dates or clear a filter.")
        return False
    columns = st.columns(5)
    columns[0].metric("Trips", whole(kpis["trips"]))
    columns[1].metric("Revenue", money(kpis["total_revenue"]))
    columns[2].metric("Average fare", money(kpis["avg_fare"]))
    columns[3].metric("Average distance", f"{kpis['avg_distance_miles']:.2f} mi")
    columns[4].metric("Airport pickups", f"{kpis['airport_share_pct']:.1f}%")
    return True


def tab_overview(selection: tuple) -> None:
    """Trips and revenue over time."""
    daily = frame("/trips/daily", selection)
    st.plotly_chart(charts.daily_trips_chart(daily))
    st.plotly_chart(charts.daily_revenue_chart(daily))


def tab_when(selection: tuple) -> None:
    """Demand by weekday and hour."""
    st.plotly_chart(charts.heatmap_chart(frame("/demand/heatmap", selection)))
    st.caption("Darker means more trips. Look for the weekday commute peaks and the weekend nightlife.")


def tab_where(selection: tuple) -> None:
    """Busiest zones and routes."""
    st.caption(
        "Zones and routes use whole months, ignore the payment filter, and treat the borough filter as the "
        "pickup borough."
    )
    left, right = st.columns(2)
    pickups = frame("/zones/top", selection, by="pickup", limit=10)
    dropoffs = frame("/zones/top", selection, by="dropoff", limit=10)
    left.plotly_chart(charts.top_bar_chart(pickups, "zone", "trips", "Top 10 pickup zones"))
    right.plotly_chart(charts.top_bar_chart(dropoffs, "zone", "trips", "Top 10 drop-off zones"))
    st.plotly_chart(charts.borough_chart(frame("/breakdown/borough", selection)))
    st.subheader("Busiest routes")
    routes = frame("/routes/top", selection, limit=15)
    if not routes.empty:
        st.dataframe(routes.round(2), hide_index=True)


def tab_payments(selection: tuple) -> None:
    """Payment types and tipping."""
    payments = frame("/breakdown/payment-type", selection)
    st.plotly_chart(charts.payment_tip_chart(payments))
    st.info(
        "**Cash tips are not recorded** in the source data, so cash trips look like they never tip. "
        "Compare credit-card trips only. Flex-fare trips (payment type 0) are recorded without a "
        "passenger count and rate code."
    )
    if not payments.empty:
        st.dataframe(payments.round(2), hide_index=True)


def tab_airports(selection: tuple) -> None:
    """Airport pickups."""
    st.plotly_chart(charts.airport_share_chart(frame("/airports/daily", selection)))
    airports = frame("/airports", selection)
    if not airports.empty:
        airports["is_airport"] = airports["is_airport"].map({True: "Airport pickups", False: "All other pickups"})
        st.dataframe(airports.round(2), hide_index=True)


def main() -> None:
    """Draw the whole page."""
    st.title("NYC Yellow Taxi")
    st.caption(
        "NYC TLC trip records, cleaned and modelled by this platform. Every number comes from the analytics API."
    )

    try:
        meta = fetch("/meta/filters", None, None, (), ())
        if not meta.get("date_min"):
            st.warning("The warehouse has no trips yet. Run the pipeline first (Airflow: taxi_month_pipeline).")
            st.stop()

        selection = sidebar_filters(meta)
        if not show_kpis(selection):
            st.stop()

        overview, when, where, payments, airports = st.tabs(
            ["Overview", "When", "Where", "Payments and tips", "Airports"]
        )
        with overview:
            tab_overview(selection)
        with when:
            tab_when(selection)
        with where:
            tab_where(selection)
        with payments:
            tab_payments(selection)
        with airports:
            tab_airports(selection)
    except AnalyticsApiError as exc:
        st.error(str(exc))
        st.info(
            "Is the analytics service running (`docker compose ps`)? Have the dbt models been built "
            "(ETL service: POST /transform/run, or the taxi_dbt_rebuild DAG)?"
        )


# Two pages in the sidebar: the data dashboard (the function above) and the "How it works" guide.
navigation = st.navigation(
    [
        st.Page(main, title="Dashboard", icon="📊", url_path="dashboard", default=True),
        st.Page("views/how_it_works.py", title="How it works", icon="🧭", url_path="how-it-works"),
    ]
)
navigation.run()
