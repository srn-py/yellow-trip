-- dbt/tests/assert_fact_matches_landing.sql
-- A singular test: a query that must return ZERO rows. Any row it returns is a failure.
-- Here: every loaded month must have exactly as many rows in fct_trips as in landing.trips.

with landing as (
    select source_year * 100 + source_month as month_key, count(*) as landing_rows
    from {{ source('landing', 'trips') }}
    group by 1
),

fact as (
    select month_key, count(*) as fact_rows
    from {{ ref('fct_trips') }}
    group by 1
)

select
    landing.month_key,
    landing.landing_rows,
    fact.fact_rows
from landing
left join fact on fact.month_key = landing.month_key
where fact.fact_rows is distinct from landing.landing_rows