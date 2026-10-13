# services/analytics/analytics_service/schemas.py
"""Response shapes of the analytics API (they also appear in the interactive docs)."""

from datetime import date

from pydantic import BaseModel


class PaymentTypeOption(BaseModel):
    """One payment type that exists in the data."""

    id: int
    name: str


class FiltersMeta(BaseModel):
    """What the dashboard may offer in its filters."""

    date_min: date | None
    date_max: date | None
    months: list[str]
    boroughs: list[str]
    payment_types: list[PaymentTypeOption]


class Kpis(BaseModel):
    """Headline numbers for the current filters. Averages are None when there are no trips."""

    trips: int
    total_revenue: float
    fare_revenue: float
    tip_revenue: float
    avg_fare: float | None
    avg_total_per_trip: float | None
    avg_distance_miles: float | None
    avg_duration_minutes: float | None
    airport_trips: int
    airport_share_pct: float | None


class DailyPoint(BaseModel):
    """Trips and revenue of one day."""

    date: date
    trips: int
    total_revenue: float
    avg_fare: float | None


class HeatmapCell(BaseModel):
    """Trips at one weekday and hour (1 = Monday)."""

    day_of_week: int
    hour_of_day: int
    trips: int


class PaymentRow(BaseModel):
    """Trips and tipping for one payment type."""

    payment_type_id: int
    payment_type: str
    trips: int
    total_revenue: float
    avg_fare: float | None
    tip_pct_of_fare: float | None
    pct_trips_with_tip: float | None


class BoroughRow(BaseModel):
    """Trips and revenue for one pickup borough."""

    borough: str
    trips: int
    total_revenue: float
    avg_fare: float | None


class AirportRow(BaseModel):
    """Airport pickups (is_airport true) versus all other pickups."""

    is_airport: bool
    trips: int
    total_revenue: float
    avg_fare: float | None
    avg_distance_miles: float | None


class AirportDailyPoint(BaseModel):
    """Airport pickups on one day and their share of all pickups."""

    date: date
    total_trips: int
    airport_trips: int
    airport_share_pct: float


class ZoneRow(BaseModel):
    """A busy zone."""

    zone: str
    borough: str
    trips: int
    total_revenue: float


class RouteRow(BaseModel):
    """A busy pickup to drop-off route."""

    pickup_zone: str
    dropoff_zone: str
    trips: int
    avg_fare: float | None
    avg_distance_miles: float | None


class ZoneInfo(BaseModel):
    """A taxi zone from the lookup table."""

    zone_id: int
    zone: str
    borough: str
    is_airport: bool
