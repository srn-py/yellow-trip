-- dbt/models/marts/tip_analysis.sql
-- Aggregate: tipping by payment type and part of the day.
-- IMPORTANT: cash tips are NOT recorded in the data, so cash rows show tips near zero.
-- That is a limit of the data, not of passengers' generosity. Compare card payments only.

select
    p.payment_type_name,
    t.day_part,
    count(*) as trips,
    count(*) filter (where f.tip_amount > 0) as trips_with_tip,
    round(100.0 * count(*) filter (where f.tip_amount > 0) / count(*), 2) as pct_trips_with_tip,
    round(avg(f.tip_amount), 2) as avg_tip_amount,
    round(100 * avg(f.tip_amount / f.fare_amount), 2) as avg_tip_pct_of_fare
from {{ ref('fct_trips') }} as f
join {{ ref('dim_payment_type') }} as p on p.payment_type_key = f.payment_type_key
join {{ ref('dim_time') }} as t on t.hour_key = f.pickup_hour_key
where f.fare_amount > 0
group by p.payment_type_name, t.day_part