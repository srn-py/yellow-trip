# notebooks/03_inspect_cleaned_data.py
# %% [markdown]
# # 03 - Inspecting the cleaned data
#
# **Goal:** check the cleaning service's work with our own eyes.
#
# 1. Do the numbers add up? (raw rows = clean rows + quarantined rows)
# 2. Why were rows quarantined?
# 3. Does the clean data really satisfy the rules?
# 4. Are the flagged rows what we expected?
#
# Run `POST /clean/trips` on the cleaning service (http://localhost:8100/docs) first.

# %%
# %load_ext autoreload
# %autoreload 2

# %%
import json
import urllib.request

import plotly.express as px

from shared.config import get_settings
from shared.lake import open_lake

settings = get_settings()
con = open_lake()  # gives us the raw views: trips_raw, zones

CLEAN = f"s3://{settings.bucket_clean}/yellow_tripdata/year=*/month=*/*.parquet"
QUARANTINE = f"s3://{settings.bucket_quarantine}/yellow_tripdata/year=*/month=*/*.parquet"

for view, pattern in (("clean_trips", CLEAN), ("quarantine_trips", QUARANTINE)):
    con.execute(
        f"CREATE OR REPLACE VIEW {view} AS "
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true, union_by_name = true)"
    )

# %% [markdown]
# ## 1. Reconciliation: does every raw row end up in exactly one place?

# %%
raw = con.execute("""
    SELECT CAST(year AS INTEGER) AS year, CAST(month AS INTEGER) AS month, count(*) AS raw_rows
    FROM trips_raw GROUP BY 1, 2
""").df()
clean = con.execute("""
    SELECT CAST(year AS INTEGER) AS year, CAST(month AS INTEGER) AS month, count(*) AS clean_rows
    FROM clean_trips GROUP BY 1, 2
""").df()
quarantine = con.execute("""
    SELECT CAST(year AS INTEGER) AS year, CAST(month AS INTEGER) AS month, count(*) AS quarantine_rows
    FROM quarantine_trips GROUP BY 1, 2
""").df()

table = raw.merge(clean, on=["year", "month"], how="left").merge(quarantine, on=["year", "month"], how="left").fillna(0)
table["difference"] = table["raw_rows"] - table["clean_rows"] - table["quarantine_rows"]
table["pct_quarantined"] = (100 * table["quarantine_rows"] / table["raw_rows"]).round(2)
table.sort_values(["year", "month"])

# %% [markdown]
# `difference` must be **0** for every month you cleaned. A month with `clean_rows = 0` simply
# has not been cleaned yet.

# %% [markdown]
# ## 2. Why were rows quarantined?
# One row can break several rules, so these counts add up to more than the quarantined rows.

# %%
reasons = con.execute("""
    SELECT reason, count(*) AS rows
    FROM (SELECT unnest(string_split(reject_reasons, ';')) AS reason FROM quarantine_trips)
    GROUP BY reason ORDER BY rows DESC
""").df()
px.bar(reasons, x="rows", y="reason", orientation="h", title="Quarantine reasons").show()
reasons

# %% [markdown]
# ## 3. Look at examples
# Always look at real rejected rows, not just counts, to confirm the rule does what we meant.

# %%
con.execute("""
    SELECT tpep_pickup_datetime, trip_distance, fare_amount, total_amount, payment_type, reject_reasons
    FROM quarantine_trips
    WHERE reject_reasons LIKE '%negative_fare%'
    LIMIT 10
""").df()

# %% [markdown]
# **Which payment types do negative fares come from?** Refunds and disputes would show up as
# types 3 and 4. This answers the question we raised while writing the findings.

# %%
con.execute("""
    SELECT payment_type, count(*) AS negative_fare_rows
    FROM quarantine_trips
    WHERE reject_reasons LIKE '%negative_fare%'
    GROUP BY 1 ORDER BY 2 DESC
""").df()

# %% [markdown]
# ## 4. Does the clean data satisfy the rules?
# Every value should be inside the allowed range.

# %%
con.execute("""
    SELECT min(fare_amount)           AS min_fare,
           min(trip_distance)         AS min_distance,
           max(trip_distance)         AS max_distance,
           min(trip_duration_minutes) AS min_minutes,
           max(trip_duration_minutes) AS max_minutes,
           max(avg_speed_mph)         AS max_speed
    FROM clean_trips
""").df()

# %% [markdown]
# ## 5. The flag columns
# Flex-fare trips (`payment_type = 0`) should be exactly the rows with
# `has_missing_trip_details = true`.

# %%
con.execute("""
    SELECT payment_type, has_missing_trip_details, count(*) AS trips
    FROM clean_trips
    GROUP BY 1, 2 ORDER BY 1, 2
""").df()

# %% [markdown]
# ## 6. The cleaning reports
# Each month's report is stored as JSON and served by the cleaning API.

# %%
with urllib.request.urlopen("http://cleaning:8000/reports/trips") as response:
    summary = json.load(response)
summary

# %%
with urllib.request.urlopen("http://cleaning:8000/reports/trips/2024/1") as response:
    report = json.load(response)
print(json.dumps(report["counts"], indent=2))
print(json.dumps(report["rule_violations"], indent=2))
print(json.dumps(report["schema"], indent=2))

# %% [markdown]
# ## Your turn
# * Which rule removes the most rows? Is that what the findings predicted?
# * Does `pct_quarantined` change between months?
# * Pick one quarantined row and trace it back: `source_file` and `source_row_number` give its raw file and row.
