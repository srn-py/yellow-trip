-- dbt/models/marts/dim_rate_code.sql
-- The fare rate in effect at the end of the trip. -1 is the "not recorded" member
-- (flex-fare trips have no rate code).

select
    rate_code_id as rate_code_key,
    rate_code_name
from {{ ref('rate_codes') }}