# services/dashboard/dashboard_app/charts.py
"""Builds the dashboard's charts from small tables (pandas DataFrames).

No Streamlit code lives here, only Plotly. That keeps chart logic easy to test and reuse
(for example in a notebook). Every function copes with an empty table by returning a friendly
"no data" figure instead of failing.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
NO_DATA = "No trips match these filters"


def empty_figure(message: str = NO_DATA) -> go.Figure:
    """A blank figure that shows a message.

    Args:
        message: The text to display.

    Returns:
        A Plotly figure with no axes.
    """
    figure = go.Figure()
    figure.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font={"size": 16})
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    figure.update_layout(height=300)
    return figure


def daily_trips_chart(frame: pd.DataFrame) -> go.Figure:
    """Line chart of trips per day.

    Args:
        frame: Table with columns `date` and `trips`.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    data = frame.assign(date=pd.to_datetime(frame["date"]))
    figure = px.line(data, x="date", y="trips", title="Trips per day")
    figure.update_layout(xaxis_title=None, yaxis_title="Trips")
    return figure


def daily_revenue_chart(frame: pd.DataFrame) -> go.Figure:
    """Line chart of revenue per day.

    Args:
        frame: Table with columns `date` and `total_revenue`.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    data = frame.assign(date=pd.to_datetime(frame["date"]))
    figure = px.line(data, x="date", y="total_revenue", title="Revenue per day (USD, excludes cash tips)")
    figure.update_layout(xaxis_title=None, yaxis_title="USD")
    return figure


def heatmap_chart(frame: pd.DataFrame) -> go.Figure:
    """Heatmap of trips by weekday and hour.

    Args:
        frame: Table with columns `day_of_week` (1 = Monday), `hour_of_day` and `trips`.

    Returns:
        The figure (7 rows by 24 columns).
    """
    if frame.empty:
        return empty_figure()
    grid = (
        frame.pivot(index="day_of_week", columns="hour_of_day", values="trips")
        .reindex(index=range(1, 8), columns=range(24))
        .fillna(0)
    )
    grid.index = DAY_NAMES
    return px.imshow(
        grid,
        aspect="auto",
        labels={"x": "Hour of day", "y": "Weekday", "color": "Trips"},
        title="When do people ride? Trips by weekday and hour",
    )


def top_bar_chart(frame: pd.DataFrame, label_column: str, value_column: str, title: str) -> go.Figure:
    """Horizontal bar chart of the biggest items, largest at the top.

    Args:
        frame: Table holding the label and value columns.
        label_column: Column with the names.
        value_column: Column with the numbers.
        title: Chart title.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    data = frame.sort_values(value_column)
    figure = px.bar(data, x=value_column, y=label_column, orientation="h", title=title)
    figure.update_layout(yaxis_title=None)
    return figure


def borough_chart(frame: pd.DataFrame) -> go.Figure:
    """Bar chart of trips per pickup borough.

    Args:
        frame: Table with columns `borough` and `trips`.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    figure = px.bar(frame, x="borough", y="trips", title="Trips by pickup borough")
    figure.update_layout(xaxis_title=None, yaxis_title="Trips")
    return figure


def payment_tip_chart(frame: pd.DataFrame) -> go.Figure:
    """Bar chart of tip as a percentage of fare, per payment type.

    Args:
        frame: Table with columns `payment_type` and `tip_pct_of_fare`.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    figure = px.bar(frame, x="payment_type", y="tip_pct_of_fare", title="Tip as % of fare, by payment type")
    figure.update_layout(xaxis_title=None, yaxis_title="Tip % of fare")
    return figure


def airport_share_chart(frame: pd.DataFrame) -> go.Figure:
    """Line chart of the share of pickups that happen at airports.

    Args:
        frame: Table with columns `date` and `airport_share_pct`.

    Returns:
        The figure.
    """
    if frame.empty:
        return empty_figure()
    data = frame.assign(date=pd.to_datetime(frame["date"]))
    figure = px.line(data, x="date", y="airport_share_pct", title="Airport pickups as % of all pickups")
    figure.update_layout(xaxis_title=None, yaxis_title="% of pickups")
    return figure
