# notebooks/04_analysis_questions.py
# %% [markdown]
# # 04 - Six questions about NYC taxis
#
# **Goal:** use the platform the way an analyst would: ask real questions, answer them with numbers and
# charts, and write down the conclusions *and their limits*. The data comes from the analytics API,
# which reads the warehouse.
#
# After running each section, write your conclusion in `docs/analysis-findings.md`.
# Prerequisite: the dbt models are built (ETL service `POST /transform/run`).

# %%
import calendar
import json
import urllib.parse
import urllib.request

import pandas as pd
import plotly.express as px

API = "http://analytics:8000"


def api(path: str, **params):
    """Call the analytics API. Lists become tables; other answers stay dictionaries."""
    clean = {key: value for key, value in params.items() if value not in (None, [], ())}
    query = urllib.parse.urlencode(clean, doseq=True)
    with urllib.request.urlopen(f"{API}{path}?{query}") as response:
        data = json.load(response)
    return pd.DataFrame(data) if isinstance(data, list) else data


meta = api("/meta/filters")
meta

# %% [markdown]
# ## Q1. How did trips and revenue change from month to month?
# Our data has gaps (we loaded January to March 2024 and January 2025), so compare neighbours carefully.
# Months also have different lengths, so look at trips **per day** too.

# %%
daily = api("/trips/daily")
daily["date"] = pd.to_datetime(daily["date"])
monthly = daily.groupby(daily["date"].dt.to_period("M")).agg(
    trips=("trips", "sum"), revenue=("total_revenue", "sum"), days=("date", "nunique")
)
monthly["trips_per_day"] = (monthly["trips"] / monthly["days"]).round(0)
monthly

# %%
px.bar(
    monthly.reset_index().astype({"date": str}),
    x="date",
    y="trips_per_day",
    title="Average trips per day, by month",
).show()

# %% [markdown]
# **Your conclusion:** which month was busiest per day? Is there a clear trend, or only a few months to judge by?

# %% [markdown]
# ## Q2. When is demand highest?

# %%
heat = api("/demand/heatmap")
grid = heat.pivot(index="day_of_week", columns="hour_of_day", values="trips").reindex(range(1, 8)).fillna(0)
grid.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
px.imshow(grid, aspect="auto", title="Trips by weekday and hour").show()

# %%
busiest = heat.sort_values("trips", ascending=False).head(5)
busiest

# %% [markdown]
# **Your conclusion:** what are the busiest weekday-hour slots? How do weekends differ from weekdays?

# %% [markdown]
# ## Q3. Which boroughs and zones dominate?

# %%
boroughs = api("/breakdown/borough")
boroughs["share_pct"] = (100 * boroughs["trips"] / boroughs["trips"].sum()).round(2)
boroughs

# %%
api("/zones/top", by="pickup", limit=10)

# %% [markdown]
# **Your conclusion:** how concentrated is the activity? Note that this shows where trips *start*.

# %% [markdown]
# ## Q4. How important are airport trips?

# %%
airports = api("/airports")
airports["is_airport"] = airports["is_airport"].map({True: "Airport pickups", False: "Other pickups"})
airports

# %%
airport_daily = api("/airports/daily")
px.line(airport_daily, x="date", y="airport_share_pct", title="Airport share of pickups (%)").show()

# %% [markdown]
# **Your conclusion:** what share of pickups are at airports? Compare average fare and distance with other trips.
# Airport trips also have a few extra fees; consider that when comparing fares.

# %% [markdown]
# ## Q5. Do passengers tip differently by payment type?
# **Caution:** cash tips are not recorded, so cash will look like "no tips". Only credit-card trips are comparable.

# %%
payments = api("/breakdown/payment-type")
payments[["payment_type", "trips", "avg_fare", "tip_pct_of_fare", "pct_trips_with_tip"]].round(2)

# %% [markdown]
# **Your conclusion:** what is the typical tip on a credit-card trip, as a percentage of the fare?

# %% [markdown]
# ## Q6. Are flex-fare trips (payment type 0) becoming more common?
# We found while profiling that a growing share of trips lacks passenger count and rate code, and that all of
# them are flex-fare trips. Here we measure that share month by month.

# %%
rows = []
for month in meta["months"]:
    year, number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, number)[1]
    split = api("/breakdown/payment-type", start=f"{month}-01", end=f"{month}-{last_day:02d}")
    total = split["trips"].sum()
    flex = split.loc[split["payment_type_id"] == 0, "trips"].sum()
    rows.append(
        {
            "month": month,
            "trips": total,
            "flex_fare_trips": flex,
            "flex_share_pct": round(100 * flex / total, 2),
        }
    )
flex_share = pd.DataFrame(rows)
flex_share

# %%
px.bar(flex_share, x="month", y="flex_share_pct", title="Flex-fare trips as % of all trips").show()

# %% [markdown]
# **Your conclusion:** does the share keep growing? Does it match the 4.7% to 15.5% rise we saw while profiling?

# %% [markdown]
# ## Your turn
# * Which route is busiest, and what is its average fare? (`/routes/top`)
# * Pick a zone ID from `/zones` and look at its weekday-hour demand (`/demand/zone-hourly`).
# * Filter Q1 to one borough: does its trend differ from the whole city?
