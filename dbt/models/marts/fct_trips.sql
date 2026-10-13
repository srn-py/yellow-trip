-- dbt/models/marts/fct_trips.sql
-- THE FACT TABLE. Grain: one row per clean taxi trip.
-- It holds keys to the dimensions plus the numbers (measures) we analyse.
--
-- Incremental: after the first build, only months that are NEW or were RELOADED by the loader
-- (loaded_at is newer than anything already here) are processed. For those months the old rows
-- are deleted and the new ones inserted ("delete+insert", keyed on month_key), so a reloaded
-- month fully replaces the old one.

{{
    config(
        materialized='incremental',
        unique_key='month_key',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        indexes=[
            {'columns': ['month_key']},
            {'columns': ['pickup_date_key']},
            {'columns': ['pickup_zone_key']},
        ],
    )
}}

select
    trip_id,
    month_key,

    -- keys to the dimension tables
    to_char(pickup_datetime, 'YYYYMMDD')::int as pickup_date_key,
    to_char(dropoff_datetime, 'YYYYMMDD')::int as dropoff_date_key,
    extract(hour from pickup_datetime)::int as pickup_hour_key,
    pickup_zone_id as pickup_zone_key,
    dropoff_zone_id as dropoff_zone_key,
    coalesce(vendor_id, -1) as vendor_key,
    coalesce(rate_code_id, -1) as rate_code_key,
    payment_type_id as payment_type_key,

    -- exact moments
    pickup_datetime,
    dropoff_datetime,

    -- measures
    passenger_count,
    trip_distance,
    trip_duration_minutes,
    avg_speed_mph,
    fare_amount,
    extra,
    mta_tax,
    tip_amount,
    tolls_amount,
    improvement_surcharge,
    congestion_surcharge,
    airport_fee,
    cbd_congestion_fee,
    total_amount,

    -- flags
    has_missing_trip_details,
    is_zero_passengers,
    store_and_fwd_flag,

    -- lineage: where this row came from
    source_file,
    source_row_number,
    loaded_at
from {{ ref('stg_trips') }}

{% if is_incremental() %}
where loaded_at > (select coalesce(max(loaded_at), '1900-01-01'::timestamptz) from {{ this }})
{% endif %}