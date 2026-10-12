-- dbt/models/marts/dim_zone.sql
-- One row per taxi zone (IDs 1 to 265).

select
    location_id as zone_key,
    borough,
    zone,
    service_zone,
    service_zone in ('Airports', 'EWR') as is_airport
from {{ ref('stg_zones') }}