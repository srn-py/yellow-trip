<!-- notebooks/README.md -->
# Notebooks

Notebooks are stored as plain `.py` files in **percent format**: cells start with `# %%`
and text cells start with `# %% [markdown]`. This keeps them readable and Git-friendly.

**Open one in JupyterLab:** right-click the file → **Open With → Notebook**.
If that option is missing: File → New → Terminal, then `jupytext --to ipynb 00_connect_to_the_lake.py`
and open the generated `.ipynb`.

Run them in order:

| Notebook | Purpose |
|---|---|
| `00_connect_to_the_lake.py` | Connect with DuckDB and learn basic SQL on the trip data |
| `01_profile_trip_data.py` | Measure the data: schema drift, nulls, duplicates, bad values |
| `02_explore_trips.py` | Charts: demand by hour, distances, fares, zones, tipping |

Prerequisite: ingest at least one month (Milestone 1) and the zone lookup file.
