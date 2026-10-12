-- dbt/models/marts/route_summary.sql
-- Aggregate for "top zones" and "top routes".
-- GRAIN: one row per month x pickup zone x drop-off zone. Month (not day) keeps it small:
-- there are up to 265 x 265 zone pairs, and per-day rows would be far too many.
-- Like trip_summary, it stores additive sums so the API can compute correct averages.

{{ config(indexes=[{'columns': ['month_key']}]) }}

select
    f.month_key,
    f.pickup_zone_key,
    pz.zone as pickup_zone,
    pz.borough as pickup_borough,
    f.dropoff_zone_key,
    dz.zone as dropoff_zone,
    dz.borough as dropoff_borough,
    count(*) as trips,
    sum(f.total_amount) as total_revenue,
    sum(f.fare_amount) as fare_revenue,
    sum(f.trip_distance) as total_distance_miles,
    sum(f.trip_duration_minutes) as total_duration_minutes
from {{ ref('fct_trips') }} as f
join {{ ref('dim_zone') }} as pz on pz.zone_key = f.pickup_zone_key
join {{ ref('dim_zone') }} as dz on dz.zone_key = f.dropoff_zone_key
group by 1, 2, 3, 4, 5, 6, 7