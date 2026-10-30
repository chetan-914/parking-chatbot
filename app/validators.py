import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import get_working_hours


class ValidationError(ValueError):
    """Raised when user-provided reservation data is invalid."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


# Standard Indian registration number and Bharat series formats.
CAR_NUMBER_PATTERN = re.compile(
    r"^([A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}|"
    r"[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$"
)


def validate_name(value: str) -> str:
    """
    Validate and normalize a customer's first or last name.

    Allowed characters:
    - Letters
    - Spaces
    - Hyphens
    - Apostrophes

    Length: 1–50 characters.
    """
    if not isinstance(value, str):
        raise ValidationError("INVALID_NAME", "Please enter a valid name.")

    name = value.strip()

    if not 1 <= len(name) <= 50:
        raise ValidationError(
            "INVALID_NAME",
            "Name must contain between 1 and 50 characters.",
        )

    if not any(char.isalpha() for char in name):
        raise ValidationError("INVALID_NAME", "Name must contain letters.")

    if not all(char.isalpha() or char in " '-" for char in name):
        raise ValidationError(
            "INVALID_NAME",
            "Name can contain only letters, spaces, hyphens, and apostrophes.",
        )

    return name


def normalize_car_number(value: str) -> str:
    """Normalize a vehicle number by removing spaces and hyphens."""
    if not isinstance(value, str):
        raise ValidationError(
            "INVALID_CAR_NUMBER",
            "Please enter a valid vehicle registration number.",
        )

    return re.sub(r"[\s-]+", "", value).upper()


def validate_car_number(value: str) -> str:
    """
    Normalize and validate an Indian vehicle registration number.

    Examples:
        TS09AB1234
        KA01A1234
        22BH1234AA
    """
    car_number = normalize_car_number(value)

    if not CAR_NUMBER_PATTERN.fullmatch(car_number):
        raise ValidationError(
            "INVALID_CAR_NUMBER",
            "Please enter a valid Indian vehicle registration number, "
            "for example TS09AB1234 or 22BH1234AA.",
        )

    return car_number


def parse_local_datetime(value: str | datetime) -> datetime:
    """
    Parse a datetime as a naive local datetime.

    The application stores booking times as local wall-clock values.
    Timezone-aware inputs are rejected rather than silently converted.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValidationError(
                "INVALID_DATETIME",
                "Please provide a valid date and time.",
            ) from exc
    else:
        raise ValidationError(
            "INVALID_DATETIME",
            "Please provide a valid date and time.",
        )

    if parsed.tzinfo is not None:
        raise ValidationError(
            "INVALID_DATETIME",
            "Please provide the date and time in local time without a timezone.",
        )

    return parsed


def _local_now() -> datetime:
    """Get the current local wall-clock time configured for the application."""
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)


def validate_period(
    start: datetime | str,
    end: datetime | str,
    now: datetime | None = None,
) -> None:
    """
    Validate a reservation period.

    Raises:
        ValidationError: If any reservation rule is violated.

    Rules:
        - Start cannot be in the past.
        - Start cannot be more than 14 days ahead.
        - Start and end must be on the same date.
        - Both times must align to a 30-minute grid.
        - Duration must be between 1 and 12 hours.
        - The complete period must fit within facility working hours.
    """
    start_dt = parse_local_datetime(start)
    end_dt = parse_local_datetime(end)
    current_time = now or _local_now()

    if current_time.tzinfo is not None:
        raise ValueError("The now argument must be a naive local datetime.")

    if start_dt < current_time:
        raise ValidationError(
            "PAST_START",
            "The reservation start time cannot be in the past.",
        )

    if start_dt.date() > current_time.date() + timedelta(days=14):
        raise ValidationError(
            "TOO_FAR",
            "Reservations can only be made up to 14 days in advance.",
        )

    if start_dt.date() != end_dt.date():
        raise ValidationError(
            "MULTI_DAY",
            "Reservations must start and end on the same day.",
        )

    if start_dt >= end_dt:
        raise ValidationError(
            "INVALID_PERIOD",
            "The end time must be later than the start time.",
        )

    if not _is_on_half_hour_grid(start_dt) or not _is_on_half_hour_grid(end_dt):
        raise ValidationError(
            "NOT_ON_GRID",
            "Reservation times must be on a 30-minute interval.",
        )

    duration = end_dt - start_dt

    if duration < timedelta(hours=1) or duration > timedelta(hours=12):
        raise ValidationError(
            "BAD_DURATION",
            "Reservations must be between 1 and 12 hours long.",
        )

    # Fetch working hours for the requested reservation date.
    working_hours = get_working_hours(start_dt.date())

    if not working_hours:
        raise ValidationError(
            "OUTSIDE_HOURS",
            "The facility is closed on the selected date.",
        )

    opening_time = _as_time(working_hours["open_time"])
    closing_time = _as_time(working_hours["close_time"])

    if start_dt.time() < opening_time or end_dt.time() > closing_time:
        raise ValidationError(
            "OUTSIDE_HOURS",
            f"The selected period must be within facility hours "
            f"({opening_time.strftime('%H:%M')}–{closing_time.strftime('%H:%M')}).",
        )


def _is_on_half_hour_grid(value: datetime) -> bool:
    """Return whether a datetime falls exactly on a 30-minute boundary."""
    return (
        value.minute in (0, 30)
        and value.second == 0
        and value.microsecond == 0
    )


def _as_time(value: time | str) -> time:
    """Convert a database time value into a Python time object."""
    if isinstance(value, time):
        return value

    if isinstance(value, str):
        return time.fromisoformat(value)

    raise TypeError(f"Unsupported working-hours value: {type(value).__name__}")