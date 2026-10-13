# services/cleaning/cleaning_service/rules.py
"""The validation rules, written once, in one place.

Every rule is a SQL condition that is TRUE for a *bad* row. The conditions use
the standardised (snake_case) column names created in `sql_builder.py`. The thresholds
come from settings (`MAX_TRIP_DISTANCE_MILES` etc. in `.env`), so you can tighten or
loosen them without editing code.

These rules come from `docs/data-quality-findings.md`. If you change a rule, bump
`RULES_VERSION`: months cleaned with an older version are then cleaned again.
"""

from dataclasses import dataclass

from shared.config import Settings

# Increase when any rule or the output format changes.
RULES_VERSION = "1.0.0"

# Highest valid NYC taxi zone ID in the lookup table.
MAX_ZONE_ID = 265


@dataclass(frozen=True)
class Rule:
    """One validation rule.

    Attributes:
        name: Short identifier; shown in quarantine reasons and the report.
        description: Plain-English meaning.
        condition: SQL expression that is TRUE when a row breaks the rule.
    """

    name: str
    description: str
    condition: str


def thresholds(settings: Settings) -> dict:
    """Collect the numeric thresholds in effect (stored in each report).

    Args:
        settings: Application settings.

    Returns:
        A dict of threshold name to value.
    """
    return {
        "max_trip_distance_miles": settings.max_trip_distance_miles,
        "max_trip_hours": settings.max_trip_hours,
        "max_speed_mph": settings.max_speed_mph,
        "max_passengers": settings.max_passengers,
    }


def build_rules(settings: Settings) -> list[Rule]:
    """Create the list of rejection rules using the configured thresholds.

    Rows that break ANY of these are moved to quarantine. Missing passenger counts and
    zero passengers are deliberately NOT here: those rows are kept and flagged instead.

    Args:
        settings: Application settings (thresholds).

    Returns:
        The rules, in a fixed order.
    """
    max_minutes = settings.max_trip_hours * 60
    return [
        Rule(
            "missing_required_value",
            "A mandatory field (times, distance, zones, payment type, fare, total) is missing",
            "tpep_pickup_datetime IS NULL OR tpep_dropoff_datetime IS NULL OR trip_distance IS NULL "
            "OR pu_location_id IS NULL OR do_location_id IS NULL OR payment_type IS NULL "
            "OR fare_amount IS NULL OR total_amount IS NULL",
        ),
        Rule("negative_fare", "Fare is below zero", "fare_amount < 0"),
        Rule("negative_total_amount", "Total amount is below zero", "total_amount < 0"),
        Rule("negative_tip", "Tip is below zero", "tip_amount < 0"),
        Rule("zero_or_negative_distance", "Trip distance is zero or negative", "trip_distance <= 0"),
        Rule(
            "excessive_distance",
            f"Trip distance is over {settings.max_trip_distance_miles} miles",
            f"trip_distance > {settings.max_trip_distance_miles}",
        ),
        Rule(
            "dropoff_not_after_pickup",
            "Drop-off is at or before pickup",
            "tpep_dropoff_datetime <= tpep_pickup_datetime",
        ),
        Rule(
            "excessive_duration",
            f"Trip lasted more than {settings.max_trip_hours} hours",
            f"trip_duration_minutes > {max_minutes}",
        ),
        Rule(
            "excessive_speed",
            f"Average speed is over {settings.max_speed_mph} mph",
            f"avg_speed_mph > {settings.max_speed_mph}",
        ),
        Rule(
            "too_many_passengers",
            f"More than {settings.max_passengers} passengers",
            f"passenger_count > {settings.max_passengers}",
        ),
        Rule(
            "pickup_outside_file_month",
            "Pickup date is not in the month of its file",
            "CAST(date_trunc('month', tpep_pickup_datetime) AS DATE) <> make_date(source_year, source_month, 1)",
        ),
        Rule(
            "invalid_pickup_zone",
            f"Pickup zone ID is outside 1 to {MAX_ZONE_ID}",
            f"pu_location_id NOT BETWEEN 1 AND {MAX_ZONE_ID}",
        ),
        Rule(
            "invalid_dropoff_zone",
            f"Drop-off zone ID is outside 1 to {MAX_ZONE_ID}",
            f"do_location_id NOT BETWEEN 1 AND {MAX_ZONE_ID}",
        ),
        Rule(
            "invalid_payment_type",
            "Payment type is outside 0 to 6",
            "payment_type NOT BETWEEN 0 AND 6",
        ),
        Rule(
            "duplicate_row",
            "Same pickup, drop-off, zones and total as an earlier row (first one is kept)",
            "duplicate_rank > 1",
        ),
    ]
