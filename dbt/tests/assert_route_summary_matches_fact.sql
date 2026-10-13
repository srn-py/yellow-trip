-- dbt/tests/assert_route_summary_matches_fact.sql
-- Same promise for the route summary: no trips lost or invented.

with summary as (
    select sum(trips) as trips, sum(total_revenue) as revenue
    from {{ ref('route_summary') }}
),

fact as (
    select count(*) as trips, sum(total_amount) as revenue
    from {{ ref('fct_trips') }}
)

select
    summary.trips as summary_trips,
    fact.trips as fact_trips
from summary
cross join fact
where summary.trips is distinct from fact.trips
   or abs(coalesce(summary.revenue, 0) - coalesce(fact.revenue, 0)) > 0.01
