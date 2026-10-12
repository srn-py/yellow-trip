-- dbt/models/marts/hourly_demand_by_zone.sql
-- Aggregate: demand per pickup zone, day of week and hour (all loaded months together).
-- Perfect for a "when and where are taxis wanted" heatmap.

select
    f.pickup_zone_key,
    z.borough,
    z.zone,
    d.day_of_week,
    f.pickup_hour_key as hour_of_day,
    count(*) as trips,
    round(avg(f.fare_amount), 2) as avg_fare,
    round(avg(f.trip_distance)::numeric, 2) as avg_distance_miles
from {{ ref('fct_trips') }} as f
join {{ ref('dim_zone') }} as z on z.zone_key = f.pickup_zone_key
join {{ ref('dim_date') }} as d on d.date_key = f.pickup_date_key
group by f.pickup_zone_key, z.borough, z.zone, d.day_of_week, f.pickup_hour_key