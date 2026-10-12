# %%
# notebooks/01_profile_trip_data.py
# %% [markdown]
# # 01 - Profiling the trip data
#
# **Goal:** measure the data's quality *before* changing anything. Every problem we
# find here becomes a cleaning rule in Milestone 3. Results go into
# `docs/data-quality-findings.md`.

# %%
# %load_ext autoreload
# %autoreload 2

# %%
import plotly.express as px

from shared.config import get_settings
from shared.lake import open_lake, trips_glob
from shared.profiling import (
    column_profile,
    count_duplicates,
    find_schema_drift,
    quality_report,
    row_counts_by_month,
    schema_by_file,
)

settings = get_settings()
con = open_lake()

# %% [markdown]
# ## 1. How many rows per month?
# A month that is much smaller or larger than its neighbours deserves a closer look.

# %%
row_counts_by_month(con)

# %% [markdown]
# ## 2. Do all files have the same columns? (schema drift)
# Rows are column names, columns are months. Blank cells mean "column missing in that file".

# %%
schema = schema_by_file(con, trips_glob(settings))
schema

# %% [markdown]
# Only the columns that are **not** identical everywhere. With several months you may see
# differences such as `Airport_fee` vs `airport_fee` or new fee columns. Our cleaning step must
# map these onto one consistent schema.

# %%
find_schema_drift(schema)

# %% [markdown]
# ## 3. Column-by-column profile
# Look at `null_percentage`, `min`, `max` and the quartiles (`q25`, `q50`, `q75`).
# Anything surprising in `min` or `max` is a candidate outlier (for example negative fares).

# %%
column_profile(con)

# %% [markdown]
# ## 4. Duplicate rows
# Rows with identical pickup time, drop-off time, zones and total amount.

# %%
count_duplicates(con)

# %% [markdown]
# ## 5. Rule-by-rule quality report
# Each row of this table is a rule that flags *bad* rows. This list is the first draft of
# the Milestone 3 validation rules.

# %%
report = quality_report(con)
report[["check", "bad_rows", "bad_pct", "rule"]]

# %%
fig = px.bar(
    report.sort_values("bad_pct"),
    x="bad_pct",
    y="check",
    orientation="h",
    title="Share of rows breaking each rule (%)",
)
fig.show()

# %% [markdown]
# ## 6. Dates that should not be there
# Each file should only contain trips from its own month. TLC files are known to contain
# a few trips from other years.

# %%
con.execute("""
    SELECT year(tpep_pickup_datetime) AS pickup_year, count(*) AS trips
    FROM trips_raw
    GROUP BY 1
    ORDER BY 1
""").df()

# %% [markdown]
# ## 7. Save the report
# Writes `quality_report.csv` next to this notebook (visible in your `notebooks/` folder).
# Copy the numbers into `docs/data-quality-findings.md`.

# %%
report.to_csv("quality_report.csv", index=False)
print(f"Saved {len(report)} checks.")

# %%
con.execute("""
      SELECT year, month, count(*) AS trips,
             round(100 * count(*) FILTER (WHERE passenger_count IS NULL) / count(*), 2) AS pct_null
      FROM trips_raw GROUP BY year, month ORDER BY year, month
  """).df()


# %%
con.execute("""
    SELECT VendorID, count(*) AS trips,
           round(100 * count(*) FILTER (WHERE passenger_count IS NULL) / count(*), 2) AS pct_null
    FROM trips_raw GROUP BY VendorID ORDER BY VendorID
""").df()

# %%
con.execute("""
    SELECT payment_type, count(*) AS trips,
           count(*) FILTER (WHERE fare_amount < 0) AS negative_fares
    FROM trips_raw GROUP BY payment_type ORDER BY payment_type
""").df()

# %%
con.execute("""
    SELECT payment_type, count(*) AS trips,
           round(100 * count(*) FILTER (WHERE passenger_count IS NULL) / count(*), 2) AS pct_null
    FROM trips_raw GROUP BY payment_type ORDER BY payment_type
""").df()

# %%
con.execute("""select count(*) from analytics.fct_trips""")

# %%

# %%
