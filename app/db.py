from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings


class BookingError(Exception):
    """Raised when PostgreSQL rejects a booking."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@lru_cache
def get_pool() -> ConnectionPool:
    """Create and cache the PostgreSQL connection pool."""
    pool = ConnectionPool(
        conninfo=settings.agent_dsn,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    pool.open(wait=True)
    return pool


def close_pool() -> None:
    """Close the PostgreSQL connection pool."""
    if get_pool.cache_info().currsize:
        get_pool().close()
        get_pool.cache_clear()


def get_working_hours(
    requested_date: date,
) -> dict | None:
    """
    Get working hours for a particular date.

    Returns None when the facility is closed or no
    working-hours record exists for that weekday.
    """
    query = """
        SELECT open_time, close_time, is_closed
        FROM working_hours
        WHERE weekday = EXTRACT(DOW FROM %s)::INT
    """

    with get_pool().connection() as conn:
        row = conn.execute(query, (requested_date,)).fetchone()

    if row is None or row["is_closed"]:
        return None

    return {
        "open_time": row["open_time"],
        "close_time": row["close_time"],
    }


def get_pricing_bands() -> list[dict]:
    """Return configured pricing bands."""
    query = """
        SELECT
            band_name,
            start_time,
            end_time,
            hourly_rate
        FROM pricing
        ORDER BY start_time
    """

    with get_pool().connection() as conn:
        rows = conn.execute(query).fetchall()

    return rows


def free_space_count(
    start: datetime,
    end: datetime,
) -> int:
    """Return the number of available parking spaces."""
    query = """
        SELECT free_space_count(%s, %s) AS available_spaces
    """

    with get_pool().connection() as conn:
        row = conn.execute(query, (start, end)).fetchone()

    return row["available_spaces"]


def quote_price(
    start: datetime,
    end: datetime,
) -> Decimal:
    """Calculate the reservation price using PostgreSQL."""
    query = """
        SELECT quote_price(%s, %s) AS total_price
    """

    with get_pool().connection() as conn:
        row = conn.execute(query, (start, end)).fetchone()

    return row["total_price"]


def make_booking(
    first_name: str,
    last_name: str,
    car_number: str,
    start: datetime,
    end: datetime,
    conversation_id: UUID,
) -> UUID:
    """
    Create a reservation through the database function.

    Customer and reservation records remain private.
    Only the booking reference is returned.
    """
    query = """
        SELECT make_booking(%s, %s, %s, %s, %s, %s)
        AS booking_ref
    """

    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                query,
                (
                    first_name,
                    last_name,
                    car_number,
                    start,
                    end,
                    conversation_id,
                ),
            ).fetchone()

        return row["booking_ref"]

    except psycopg.errors.RaiseException as exc:
        message = (
            exc.diag.message_primary
            if exc.diag and exc.diag.message_primary
            else str(exc)
        )

        code = message.split(":", 1)[0].strip()

        raise BookingError(code, message) from exc


def cancel_booking(
    booking_ref: UUID,
    car_number: str,
) -> bool:
    """
    Cancel a future reservation.

    The database function checks both the booking reference
    and vehicle number without exposing customer records.
    """
    query = """
        SELECT cancel_booking(%s, %s) AS cancelled
    """

    with get_pool().connection() as conn:
        row = conn.execute(
            query,
            (booking_ref, car_number),
        ).fetchone()

    return row["cancelled"]


def save_conversation_log(
    conversation_id: UUID,
    transcript: str,
    end_reason: str,
    turn_count: int,
    started_at: datetime,
) -> None:
    """
    Save a redacted conversation transcript.

    The caller must redact all names, vehicle numbers,
    and other PII before passing the transcript here.
    """
    query = """
        INSERT INTO conversation_log (
            conversation_id,
            transcript,
            end_reason,
            turn_count,
            started_at
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (conversation_id) DO NOTHING
    """

    with get_pool().connection() as conn:
        conn.execute(
            query,
            (
                conversation_id,
                transcript,
                end_reason,
                turn_count,
                started_at,
            ),
        )