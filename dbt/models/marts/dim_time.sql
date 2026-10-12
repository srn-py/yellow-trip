-- dbt/models/marts/dim_time.sql
-- One row per hour of the day, with a friendly "day part" for analysis.

select
    t.hour_of_day as hour_key,
    to_char(make_time(t.hour_of_day, 0, 0), 'HH24:MI') as hour_label,
    case
        when t.hour_of_day between 6 and 9 then 'Morning rush'
        when t.hour_of_day between 10 and 15 then 'Midday'
        when t.hour_of_day between 16 and 19 then 'Evening rush'
        when t.hour_of_day between 20 and 23 then 'Evening'
        else 'Night'
    end as day_part
from generate_series(0, 23) as t(hour_of_day)
