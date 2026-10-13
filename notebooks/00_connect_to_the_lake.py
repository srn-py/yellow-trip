# %%
# notebooks/00_connect_to_the_lake.py
# %% [markdown]
# # 00 - Connecting to the data lake with DuckDB
#
# **Goal:** query the Parquet files in our raw bucket with plain SQL, without
# downloading or loading anything into a database.
#
# **How it works:** DuckDB runs inside this notebook. Its `httpfs` extension reads
# `s3://raw/...` straight from our object store. We created two *views*
# (saved queries, no data copied):
#
# | View | Contents |
# |---|---|
# | `trips_raw` | All trip files, combined. Extra columns: `year`, `month` (from folder names), `filename` |
# | `zones` | Taxi zone lookup (location id to borough and zone name) |

# %%
# Reload our own modules automatically when you edit them.
# %load_ext autoreload
# %autoreload 2

# %%
from shared.lake import open_lake

con = open_lake()  # connects to the lake and creates the views

# %% [markdown]
# ## 1. What do we have?

# %%
con.execute("SELECT table_name, table_type FROM information_schema.tables").df()

# %%
con.execute("SELECT count(*) AS trips FROM trips_raw").df()

# %%
con.execute("SELECT * FROM trips_raw LIMIT 5").df()

# %% [markdown]
# ## 2. Column names and types
# `DESCRIBE` shows what DuckDB found in the files. Compare these types with the
# data dictionary (`docs/data_dictionary.md`).

# %%
con.execute("DESCRIBE trips_raw").df()

# %% [markdown]
# ## 3. SQL in five lines
# * `SELECT` chooses columns, `FROM` chooses the table
# * `WHERE` keeps only rows that match
# * `GROUP BY` makes one row per group, with aggregates like `count`, `avg`
# * `ORDER BY` sorts
# * `JOIN` combines two tables on a shared key

# %%
con.execute("""
    SELECT passenger_count,
           count(*)                    AS trips,
           round(avg(fare_amount), 2)  AS avg_fare
    FROM trips_raw
    GROUP BY passenger_count
    ORDER BY passenger_count
""").df()

# %% [markdown]
# **Question:** which borough has the most pickups? We `JOIN` trips to the zone
# lookup using the pickup location id. (Needs the zone file from Milestone 1.)

# %%
con.execute("""
    SELECT z.Borough, count(*) AS trips
    FROM trips_raw AS t
    JOIN zones AS z ON t.PULocationID = z.LocationID
    GROUP BY z.Borough
    ORDER BY trips DESC
""").df()

# %% [markdown]
# ## Your turn
# 1. How many trips were paid by cash (`payment_type = 2`)?
# 2. What is the average `trip_distance` per month?
# 3. What is the single most expensive trip (`total_amount`)? Does it look realistic?

# %%
