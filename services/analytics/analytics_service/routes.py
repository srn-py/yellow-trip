# services/analytics/analytics_service/routes.py
"""HTTP endpoints of the analytics API."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import queries
from .database import Database, ModelsNotBuiltError
from .queries import Filters
from .schemas import (
    AirportDailyPoint,
    AirportRow,
    BoroughRow,
    DailyPoint,
    FiltersMeta,
    HeatmapCell,
    Kpis,
    PaymentRow,
    PaymentTypeOption,
    RouteRow,
    ZoneInfo,
    ZoneRow,
)

router = APIRouter()


def get_database(request: Request) -> Database:
    """Dependency: the shared Database (set up in main.py). Tests replace it with a fake."""
    return request.app.state.db


def get_filters(
    start: Annotated[date | None, Query(description="First pickup date, YYYY-MM-DD")] = None,
    end: Annotated[date | None, Query(description="Last pickup date, YYYY-MM-DD")] = None,
    borough: Annotated[list[str] | None, Query(description="Pickup borough; repeat to pick several")] = None,
    payment_type: Annotated[list[int] | None, Query(description="Payment type ID; repeat to pick several")] = None,
) -> Filters:
    """Collect the common filters from the query string.

    Raises:
        HTTPException: 422 if `start` is after `end`.
    """
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="'start' must not be after 'end'")
    return Filters(start, end, tuple(borough or ()), tuple(payment_type or ()))


DbDep = Annotated[Database, Depends(get_database)]
FiltersDep = Annotated[Filters, Depends(get_filters)]


def register_error_handlers(app: FastAPI) -> None:
    """Turn "tables not built yet" into a clear 503 answer.

    Args:
        app: The FastAPI application.
    """

    @app.exception_handler(ModelsNotBuiltError)
    async def models_not_built(request: Request, exc: ModelsNotBuiltError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})


def _ratio(numerator: float, denominator: float) -> float | None:
    """Divide, returning None instead of failing when the denominator is zero."""
    return round(numerator / denominator, 4) if denominator else None


# ---- metadata ---------------------------------------------------------------------
@router.get("/meta/filters", response_model=FiltersMeta, tags=["meta"], summary="What the filters can offer")
def meta_filters(db: DbDep) -> FiltersMeta:
    """Available dates, months, boroughs and payment types."""
    dates = db.query(queries.META_DATES)[0]
    return FiltersMeta(
        date_min=dates["date_min"],
        date_max=dates["date_max"],
        months=[row["month"] for row in db.query(queries.META_MONTHS)],
        boroughs=[row["borough"] for row in db.query(queries.META_BOROUGHS)],
        payment_types=[PaymentTypeOption(**row) for row in db.query(queries.META_PAYMENTS)],
    )


@router.get("/zones", response_model=list[ZoneInfo], tags=["meta"], summary="All taxi zones")
def zones(db: DbDep) -> list[dict]:
    """The zone lookup table (ID, name, borough, airport flag)."""
    return db.query(queries.ZONES)


# ---- headline numbers and series --------------------------------------------------------
@router.get("/kpis", response_model=Kpis, tags=["overview"], summary="Headline numbers")
def kpis(db: DbDep, filters: FiltersDep) -> Kpis:
    """Totals and averages for the chosen filters."""
    row = db.query(*queries.kpis_query(filters))[0]
    trips = row["trips"]
    return Kpis(
        trips=trips,
        total_revenue=row["total_revenue"],
        fare_revenue=row["fare_revenue"],
        tip_revenue=row["tip_revenue"],
        avg_fare=_ratio(row["fare_revenue"], trips),
        avg_total_per_trip=_ratio(row["total_revenue"], trips),
        avg_distance_miles=_ratio(row["total_distance_miles"], trips),
        avg_duration_minutes=_ratio(row["total_duration_minutes"], trips),
        airport_trips=row["airport_trips"],
        airport_share_pct=_ratio(100 * row["airport_trips"], trips),
    )


@router.get(
    "/trips/daily",
    response_model=list[DailyPoint],
    tags=["overview"],
    summary="Trips and revenue per day",
)
def trips_daily(db: DbDep, filters: FiltersDep) -> list[dict]:
    """One point per pickup day."""
    return db.query(*queries.daily_query(filters))


@router.get(
    "/demand/heatmap",
    response_model=list[HeatmapCell],
    tags=["demand"],
    summary="Trips by weekday and hour",
)
def demand_heatmap(db: DbDep, filters: FiltersDep) -> list[dict]:
    """Weekday (1 = Monday) by hour of day."""
    return db.query(*queries.heatmap_query(filters))


@router.get(
    "/demand/zone-hourly",
    response_model=list[HeatmapCell],
    tags=["demand"],
    summary="Weekday and hour demand of one pickup zone",
)
def demand_zone_hourly(
    db: DbDep, zone_id: Annotated[int, Query(ge=1, le=265, description="TLC zone ID")]
) -> list[dict]:
    """All loaded months together; the date and payment filters do not apply here."""
    return db.query(*queries.zone_hourly_query(zone_id))


# ---- breakdowns -----------------------------------------------------------------------
@router.get(
    "/breakdown/payment-type",
    response_model=list[PaymentRow],
    tags=["breakdown"],
    summary="Trips, fares and tipping per payment type",
)
def breakdown_payment(db: DbDep, filters: FiltersDep) -> list[dict]:
    """Cash tips are not recorded in the source data, so cash looks like it never tips."""
    return db.query(*queries.payment_query(filters))


@router.get(
    "/breakdown/borough",
    response_model=list[BoroughRow],
    tags=["breakdown"],
    summary="Trips per pickup borough",
)
def breakdown_borough(db: DbDep, filters: FiltersDep) -> list[dict]:
    """Trips and revenue by the borough where the trip started."""
    return db.query(*queries.borough_query(filters))


@router.get(
    "/airports",
    response_model=list[AirportRow],
    tags=["airports"],
    summary="Airport versus other pickups",
)
def airports(db: DbDep, filters: FiltersDep) -> list[dict]:
    """Two rows at most: airport pickups and all other pickups."""
    return db.query(*queries.airports_query(filters))


@router.get(
    "/airports/daily",
    response_model=list[AirportDailyPoint],
    tags=["airports"],
    summary="Daily share of airport pickups",
)
def airports_daily(db: DbDep, filters: FiltersDep) -> list[dict]:
    """Airport pickups per day and their share of all pickups."""
    return db.query(*queries.airports_daily_query(filters))


# ---- zones and routes (month grain) ---------------------------------------------------------
@router.get("/zones/top", response_model=list[ZoneRow], tags=["places"], summary="Busiest zones")
def zones_top(
    db: DbDep,
    filters: FiltersDep,
    by: Annotated[Literal["pickup", "dropoff"], Query(description="Rank by pickups or drop-offs")] = "pickup",
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[dict]:
    """Uses whole months, ignores the payment filter; `borough` means pickup borough."""
    return db.query(*queries.top_zones_query(filters, by, limit))


@router.get("/routes/top", response_model=list[RouteRow], tags=["places"], summary="Busiest routes")
def routes_top(
    db: DbDep,
    filters: FiltersDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[dict]:
    """Busiest pickup to drop-off zone pairs. Whole months, ignores the payment filter."""
    return db.query(*queries.top_routes_query(filters, limit))
