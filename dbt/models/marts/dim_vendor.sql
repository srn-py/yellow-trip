-- dbt/models/marts/dim_vendor.sql
-- The company that supplied the trip record. -1 is the "not recorded" member.

select
    vendor_id as vendor_key,
    vendor_name
from {{ ref('vendors') }}