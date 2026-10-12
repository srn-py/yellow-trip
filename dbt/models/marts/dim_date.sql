-- dbt/models/marts/dim_date.sql
-- One row per calendar day, 2009 to 2035 (the TLC data starts in 2009).
-- The key is an integer like 20240115, easy to read and cheap to join on.

with days as (
    select generate_series(date '2009-01-01', date '2035-12-31', interval '1 day')::date as date_day
)

select
    to_char(date_day, 'YYYYMMDD')::int as date_key,
    date_day as date,
    extract(year from date_day)::int as year,
    extract(quarter from date_day)::int as quarter,
    extract(month from date_day)::int as month,
    to_char(date_day, 'FMMonth') as month_name,
    extract(day from date_day)::int as day_of_month,
    extract(isodow from date_day)::int as day_of_week,       -- 1 = Monday ... 7 = Sunday
    to_char(date_day, 'FMDay') as day_name,
    extract(isodow from date_day) in (6, 7) as is_weekend,
    extract(week from date_day)::int as iso_week
from days