-- dbt/tests/assert_trip_summary_matches_fact.sql
-- Returns a row (= test failure) if the summary lost or invented trips or revenue
-- compared with the fact table. Inner joins can silently drop rows, so we always check.

with summary as (
    select sum(trips) as trips, sum(total_revenue) as revenue
    from {{ ref('trip_summary') }}
),

fact as (
    select count(*) as trips, sum(total_amount) as revenue
    from {{ ref('fct_trips') }}
)

select
    summary.trips as summary_trips,
    fact.trips as fact_trips,
    summary.revenue as summary_revenue,
    fact.revenue as fact_revenue
from summary
cross join fact
where summary.trips is distinct from fact.trips
   or abs(coalesce(summary.revenue, 0) - coalesce(fact.revenue, 0)) > 0.01