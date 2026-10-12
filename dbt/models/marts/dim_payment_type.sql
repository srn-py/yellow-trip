-- dbt/models/marts/dim_payment_type.sql
select
    payment_type_id as payment_type_key,
    payment_type_name
from {{ ref('payment_types') }}
