-- dbt/tests/assert_fact_values_are_valid.sql
-- Same promises as the cleaning service's data contract, re-checked in the warehouse.
-- Returns the offending trips (zero rows = pass).

select trip_id
from {{ ref('fct_trips') }}
where dropoff_datetime <= pickup_datetime
   or trip_distance <= 0
   or fare_amount < 0
   or total_amount < 0