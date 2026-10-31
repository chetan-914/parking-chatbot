
import pytest

from datetime import datetime, time, timedelta

from app.validators import (
    ValidationError,
    parse_local_datetime,
    validate_car_number,
    validate_name,
    validate_period,
)


def test_valid_car_numbers():
    """Accept valid Indian vehicle registration numbers."""

    valid_numbers = [
        "TS09AB1234",
        "TS09 AB 1234",
        "TS09-AB-1234",
        "MH12CD5678",
        "KA03MN1234",
        "09BH1234AA",
    ]

    for number in valid_numbers:
        assert validate_car_number(number) is not None


@pytest.mark.parametrize(
    "number",
    [
        "INVALID",
        "TS09AB123",
        "TS09AB12345",
        "T091234",
        "1234AB5678",
        "",
        "TS09@B1234",
    ],
)
def test_invalid_car_numbers(number):
    """Reject malformed registration numbers."""

    with pytest.raises(ValidationError):
        validate_car_number(number)


@pytest.mark.parametrize(
    "name",
    [
        "Asha",
        "Rahul Sharma",
        "Mary-Jane",
        "O'Connor",
        "A B",
    ],
)
def test_valid_names(name):
    """Accept names containing permitted characters."""

    assert validate_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "John123",
        "John@Doe",
        "A" * 51,
        "John_Doe",
    ],
)
def test_invalid_names(name):
    """Reject invalid names."""

    with pytest.raises(ValidationError):
        validate_name(name)


def test_parse_local_datetime():
    """Parse a valid local date and time."""

    result = parse_local_datetime(
        "2026-11-02 10:30"
    )

    assert isinstance(result, datetime)
    assert result == datetime(2026, 11, 2, 10, 30)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-date",
        "2026/11/02",
        "tomorrow morning",
    ],
)
def test_invalid_datetime(value):
    """Reject unsupported datetime formats."""

    with pytest.raises(ValidationError):
        parse_local_datetime(value)


def test_valid_booking_period():
    """Accept a valid one-hour booking."""

    now = datetime(2026, 11, 1, 10, 0)

    start = datetime(2026, 11, 2, 10, 0)
    end = datetime(2026, 11, 2, 11, 0)

    hours = (
        time(6, 0),
        time(22, 0),
    )

    result = validate_period(
        start=start,
        end=end,
        now=now,
        hours=hours,
    )

    assert result is None


@pytest.mark.parametrize(
    "start_offset,end_offset,expected_error",
    [
        (
            timedelta(hours=1),
            timedelta(hours=1),
            "INVALID_PERIOD",
        ),
        (
            timedelta(days=-1),
            timedelta(hours=-23),
            "PAST_START",
        ),
        (
            timedelta(days=15),
            timedelta(days=15, hours=1),
            "TOO_FAR",
        ),
        (
            timedelta(hours=1),
            timedelta(days=1, hours=1),
            "MULTI_DAY",
        ),
        (
            timedelta(minutes=15),
            timedelta(hours=1, minutes=15),
            "NOT_ON_GRID",
        ),
        (
            timedelta(hours=1),
            timedelta(hours=1, minutes=30),
            "BAD_DURATION",
        ),
        (
            timedelta(hours=1),
            timedelta(hours=14),
            "BAD_DURATION",
        ),
    ],
)
def test_invalid_booking_periods(
    start_offset,
    end_offset,
    expected_error,
):
    """Reject periods that violate booking rules."""

    now = datetime(2026, 11, 1, 10, 0)

    start = now + timedelta(days=1) + start_offset
    end = now + timedelta(days=1) + end_offset

    hours = (
        time(6, 0),
        time(22, 0),
    )

    result = validate_period(
        start=start,
        end=end,
        now=now,
        hours=hours,
    )

    assert result == expected_error


def test_booking_outside_working_hours():
    """Reject bookings outside facility working hours."""

    now = datetime(2026, 11, 1, 10, 0)

    start = datetime(2026, 11, 2, 5, 0)
    end = datetime(2026, 11, 2, 6, 0)

    result = validate_period(
        start=start,
        end=end,
        now=now,
        hours=(
            time(6, 0),
            time(22, 0),
        ),
    )

    assert result == "OUTSIDE_HOURS"


def test_booking_on_closed_day():
    """Reject bookings when the facility is closed."""

    now = datetime(2026, 11, 1, 10, 0)

    start = datetime(2026, 11, 2, 10, 0)
    end = datetime(2026, 11, 2, 11, 0)

    result = validate_period(
        start=start,
        end=end,
        now=now,
        hours=None,
    )

    assert result == "OUTSIDE_HOURS"
