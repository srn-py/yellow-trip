-- dbt/models/staging/stg_zones.sql
select
    location_id,
    borough,
    zone,
    service_zone
from {{ source('landing', 'zones') }}
