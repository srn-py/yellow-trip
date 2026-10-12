-- dbt/models/marts/daily_revenue.sql
-- Aggregate: one row per pickup day.

select
    d.date_key,
    d.date,
    d.day_name,
    d.is_weekend,
    count(*) as trips,
    sum(f.total_amount) as total_revenue,
    sum(f.fare_amount) as fare_revenue,
    sum(f.tip_amount) as tip_revenue,
    round(avg(f.fare_amount), 2) as avg_fare,
    round(avg(f.trip_distance)::numeric, 2) as avg_distance_miles,
    round(avg(f.trip_duration_minutes)::numeric, 1) as avg_duration_minutes
from {{ ref('fct_trips') }} as f
join {{ ref('dim_date') }} as d on d.date_key = f.pickup_date_key
group by d.date_key, d.date, d.day_name, d.is_weekend