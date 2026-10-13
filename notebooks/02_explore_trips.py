# %%
# notebooks/02_explore_trips.py
# %% [markdown]
# # 02 - Exploring the trips with charts
#
# **Goal:** understand how the city uses taxis. We let DuckDB do the heavy counting
# (millions of rows) and only bring small result tables into pandas for charts.
#
# We only keep trips whose pickup falls inside the month of their file. That filter is
# one of the quality rules we found in notebook 01.

# %%
# %load_ext autoreload
# %autoreload 2

# %%
import plotly.express as px

from shared.lake import open_lake
from shared.profiling import histogram

con = open_lake()

# SQL condition: the pickup is inside the file's own month.
IN_MONTH = (
    "CAST(date_trunc('month', tpep_pickup_datetime) AS DATE) "
    "= make_date(CAST(year AS INTEGER), CAST(month AS INTEGER), 1)"
)

# %% [markdown]
# ## 1. When do people ride? Trips by hour of day

# %%
by_hour = con.execute(f"""
    SELECT hour(tpep_pickup_datetime) AS hour_of_day, count(*) AS trips
    FROM trips_raw
    WHERE {IN_MONTH}
    GROUP BY 1
    ORDER BY 1
""").df()

px.bar(by_hour, x="hour_of_day", y="trips", title="Trips by hour of day").show()

# %% [markdown]
# ## 2. Weekday x hour heatmap
# Darker cells mean more trips. Look for the weekday commute and the weekend nightlife pattern.

# %%
heat = con.execute(f"""
    SELECT isodow(tpep_pickup_datetime) AS weekday_number,
           hour(tpep_pickup_datetime)   AS hour_of_day,
           count(*)                     AS trips
    FROM trips_raw
    WHERE {IN_MONTH}
    GROUP BY 1, 2
""").df()

grid = heat.pivot(index="weekday_number", columns="hour_of_day", values="trips")
grid.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
px.imshow(grid, aspect="auto", title="Trips: weekday x hour", labels={"color": "trips"}).show()

# %% [markdown]
# ## 3. How far do people travel?
# We cut the chart at 30 miles. A tiny number of trips report hundreds of miles, which would
# squash everything else (these are outliers, and likely errors).

# %%
distance = histogram(con, "trip_distance", low=0, high=30, bins=60)
px.bar(distance, x="bin_start", y="trips", title="Trip distance (miles)").show()

# %% [markdown]
# ## 4. Does fare grow with distance?
# Plotting millions of points is slow and unreadable, so we draw a random sample of 20,000
# trips with plausible values. Notice the vertical stripe at distance 0 and the flat fares:
# these are data quality problems or special fares (for example the flat airport fare).

# %%
sample = con.execute(f"""
    SELECT trip_distance, fare_amount
    FROM (
        SELECT trip_distance, fare_amount
        FROM trips_raw
        WHERE {IN_MONTH} AND trip_distance < 40 AND fare_amount BETWEEN 0 AND 200
    ) USING SAMPLE reservoir(20000 ROWS) REPEATABLE (42)
""").df()

px.scatter(sample, x="trip_distance", y="fare_amount", opacity=0.3, title="Fare vs distance (sample)").show()

# %% [markdown]
# ## 5. Busiest pickup zones

# %%
top_zones = con.execute(f"""
    SELECT z.Zone || ' (' || z.Borough || ')' AS zone, count(*) AS trips
    FROM trips_raw AS t
    JOIN zones AS z ON t.PULocationID = z.LocationID
    WHERE {IN_MONTH}
    GROUP BY 1
    ORDER BY trips DESC
    LIMIT 10
""").df()

fig = px.bar(top_zones, x="trips", y="zone", orientation="h", title="Top 10 pickup zones")
fig.update_layout(yaxis={"categoryorder": "total ascending"})
fig.show()

# %% [markdown]
# ## 6. Tipping by payment type
# Credit-card tips are recorded automatically. **Cash tips are not recorded**, so cash trips
# appear to have almost no tips. This is a limit of the data, not of passengers' generosity,
# and it is the kind of insight that stops us making wrong conclusions later.

# %%
tips = con.execute(f"""
    SELECT CASE payment_type WHEN 1 THEN 'Credit card' WHEN 2 THEN 'Cash' ELSE 'Other' END AS payment,
           round(100 * avg(tip_amount / fare_amount), 2) AS avg_tip_pct_of_fare
    FROM trips_raw
    WHERE {IN_MONTH} AND fare_amount > 0
    GROUP BY 1
    ORDER BY 2 DESC
""").df()

px.bar(tips, x="payment", y="avg_tip_pct_of_fare", title="Average tip as % of fare").show()

# %% [markdown]
# ## Your turn
# * Add a chart of average `total_amount` by hour of day.
# * Which pickup zone has the longest average `trip_distance`?
# * Do trip counts change between the months you ingested?

# %%

# %%

# %%
