-- dbt/models/staging/stg_trips.sql
-- Staging: a light, tidy view over landing.trips. No business logic here:
-- readable names, a trip_id, and a month_key. Everything else happens in the marts.

select
    -- A stable, unique key for each trip: raw file + row number within that file.
    md5(source_file || '-' || source_row_number::text) as trip_id,
    source_year * 100 + source_month as month_key,          -- e.g. 202401

    vendor_id,
    tpep_pickup_datetime as pickup_datetime,
    tpep_dropoff_datetime as dropoff_datetime,
    passenger_count,
    trip_distance,
    ratecode_id as rate_code_id,
    store_and_fwd_flag,
    pu_location_id as pickup_zone_id,
    do_location_id as dropoff_zone_id,
    payment_type as payment_type_id,

    fare_amount,
    extra,
    mta_tax,
    tip_amount,
    tolls_amount,
    improvement_surcharge,
    total_amount,
    congestion_surcharge,
    airport_fee,
    cbd_congestion_fee,

    trip_duration_minutes,
    avg_speed_mph,
    has_missing_trip_details,
    is_zero_passengers,

    source_year,
    source_month,
    source_file,
    source_row_number,
    loaded_at
from {{ source('landing', 'trips') }}