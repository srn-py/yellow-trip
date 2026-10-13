-- dbt/models/marts/trip_summary.sql
-- Aggregate used by the analytics API and the dashboard.
-- GRAIN: one row per pickup date x pickup hour x pickup borough x airport flag x payment type.
--
-- It stores SUMS and COUNTS only (never averages): sums can be added together across any
-- combination of filters, and the API then divides them (average fare = sum of fares / trips).
-- An average of averages would be wrong, because groups have different sizes.

{{ config(indexes=[{'columns': ['date']}]) }}

select
    f.pickup_date_key as date_key,
    d.date,
    f.pickup_hour_key as hour_of_day,
    z.borough as pickup_borough,
    z.is_airport as pickup_is_airport,
    f.payment_type_key,
    p.payment_type_name,
    count(*) as trips,
    count(*) filter (where f.tip_amount > 0) as trips_with_tip,
    sum(f.total_amount) as total_revenue,
    sum(f.fare_amount) as fare_revenue,
    sum(f.tip_amount) as tip_revenue,
    sum(f.trip_distance) as total_distance_miles,
    sum(f.trip_duration_minutes) as total_duration_minutes
from {{ ref('fct_trips') }} as f
join {{ ref('dim_date') }} as d on d.date_key = f.pickup_date_key
join {{ ref('dim_zone') }} as z on z.zone_key = f.pickup_zone_key
join {{ ref('dim_payment_type') }} as p on p.payment_type_key = f.payment_type_key
group by 1, 2, 3, 4, 5, 6, 7