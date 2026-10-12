# tests/test_dashboard_charts.py
import pandas as pd
from dashboard_app import charts


def test_empty_data_gives_a_friendly_message_instead_of_failing():
    for build in (
        charts.daily_trips_chart,
        charts.daily_revenue_chart,
        charts.heatmap_chart,
        charts.borough_chart,
        charts.payment_tip_chart,
        charts.airport_share_chart,
    ):
        figure = build(pd.DataFrame())
        assert figure.layout.annotations[0].text == charts.NO_DATA


def test_daily_charts_have_one_line_each():
    frame = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "trips": [10, 12], "total_revenue": [100.0, 130.0]})
    assert len(charts.daily_trips_chart(frame).data) == 1
    assert len(charts.daily_revenue_chart(frame).data) == 1


def test_heatmap_is_always_seven_days_by_twenty_four_hours():
    frame = pd.DataFrame({"day_of_week": [1, 5], "hour_of_day": [8, 23], "trips": [50, 70]})
    figure = charts.heatmap_chart(frame)
    grid = figure.data[0].z
    assert grid.shape == (7, 24)
    assert grid[0][8] == 50  # Monday 08:00
    assert grid[4][23] == 70  # Friday 23:00
    assert grid[2][3] == 0  # missing combinations are filled with zero


def test_top_bar_chart_is_horizontal_with_the_largest_bar_last_so_it_shows_on_top():
    frame = pd.DataFrame({"zone": ["A", "B", "C"], "trips": [5, 30, 12]})
    figure = charts.top_bar_chart(frame, "zone", "trips", "Top zones")
    assert figure.data[0].orientation == "h"
    assert list(figure.data[0].y) == ["A", "C", "B"]


def test_borough_payment_and_airport_charts_build():
    assert len(charts.borough_chart(pd.DataFrame({"borough": ["Queens"], "trips": [3]})).data) == 1
    payments = pd.DataFrame({"payment_type": ["Credit card", "Cash"], "tip_pct_of_fare": [20.0, 0.0]})
    assert len(charts.payment_tip_chart(payments).data) == 1
    airport = pd.DataFrame({"date": ["2024-01-01"], "airport_share_pct": [4.5]})
    assert len(charts.airport_share_chart(airport).data) == 1
