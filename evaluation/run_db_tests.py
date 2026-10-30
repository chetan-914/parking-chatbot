
import os
import uuid

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg


AGENT_DSN = os.getenv("POSTGRES_AGENT_DSN")
ADMIN_DSN = os.getenv("POSTGRES_ADMIN_DSN")

TEST_FIRST_NAME = "Database"
TEST_LAST_NAME = "Tester"
TEST_CAR_NUMBER = "TS09AB1234"


def require_dsns():
    """Ensure both database connections are configured."""

    if not AGENT_DSN or not ADMIN_DSN:
        raise RuntimeError(
            "Set POSTGRES_AGENT_DSN and POSTGRES_ADMIN_DSN."
        )


def get_test_period():
    """Find a future one-hour period within opening hours."""

    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute(
            """
            SELECT
                (CURRENT_DATE + days)::date AS booking_date,
                wh.open_time,
                wh.close_time
            FROM generate_series(1, 14) AS days
            JOIN working_hours wh
              ON wh.weekday = EXTRACT(
                    DOW FROM CURRENT_DATE + days
                 )::INT
            WHERE NOT wh.is_closed
              AND wh.open_time <= TIME '10:00'
              AND wh.close_time >= TIME '11:00'
            ORDER BY days
            LIMIT 1
            """
        ).fetchone()

    if not row:
        raise RuntimeError(
            "Could not find a suitable future test date."
        )

    booking_date = row[0]

    start = datetime.combine(
        booking_date,
        datetime.strptime("10:00", "%H:%M").time(),
    )

    end = start + timedelta(hours=1)

    return start, end


def call_booking(
    first,
    last,
    car,
    start,
    end,
    conversation_id=None,
):
    """Call the database booking function as agent_role."""

    conversation_id = conversation_id or uuid.uuid4()

    with psycopg.connect(AGENT_DSN) as conn:
        return conn.execute(
            """
            SELECT make_booking(%s, %s, %s, %s, %s, %s)
            """,
            (
                first,
                last,
                car,
                start,
                end,
                conversation_id,
            ),
        ).fetchone()[0]


def call_cancel(booking_ref, car):
    """Call the cancellation function as agent_role."""

    with psycopg.connect(AGENT_DSN) as conn:
        return conn.execute(
            """
            SELECT cancel_booking(%s, %s)
            """,
            (booking_ref, car),
        ).fetchone()[0]


def get_free_space_count(start, end):
    """Read only the aggregate availability count."""

    with psycopg.connect(AGENT_DSN) as conn:
        return conn.execute(
            """
            SELECT free_space_count(%s, %s)
            """,
            (start, end),
        ).fetchone()[0]


def get_price(start, end):
    """Calculate the price through the database function."""

    with psycopg.connect(AGENT_DSN) as conn:
        return conn.execute(
            """
            SELECT quote_price(%s, %s)
            """,
            (start, end),
        ).fetchone()[0]


def expect_booking_error(expected_code, start, end):
    """Verify that an invalid booking raises the expected code."""

    try:
        call_booking(
            TEST_FIRST_NAME,
            TEST_LAST_NAME,
            TEST_CAR_NUMBER,
            start,
            end,
        )

    except psycopg.Error as exc:
        message = exc.diag.message_primary or str(exc)
        actual_code = message.split(":")[0].strip()

        assert actual_code == expected_code, (
            f"Expected {expected_code}, got {actual_code}: {message}"
        )

        print(f"PASS: {expected_code}")
        return

    raise AssertionError(
        f"Expected booking error {expected_code}, but booking succeeded."
    )


def test_price_calculation():
    """Check the sample pricing calculation."""

    start = datetime(2026, 11, 2, 16, 0)
    end = datetime(2026, 11, 2, 19, 0)

    actual = get_price(start, end)

    assert actual == Decimal("110.00"), (
        f"Expected 110.00, got {actual}"
    )

    print("PASS: Price calculation = ₹110.00")


def test_booking_validation():
    """Test invalid booking periods."""

    start, _ = get_test_period()

    # Start time is not on the 30-minute grid.
    expect_booking_error(
        "NOT_ON_GRID",
        start.replace(hour=10, minute=15),
        start.replace(hour=11, minute=15),
    )

    # Duration is less than one hour.
    expect_booking_error(
        "BAD_DURATION",
        start,
        start + timedelta(minutes=30),
    )

    # Duration exceeds twelve hours.
    expect_booking_error(
        "BAD_DURATION",
        start,
        start + timedelta(hours=13),
    )

    # Start time is in the past.
    past_start = datetime.now().replace(
        second=0,
        microsecond=0,
    ) - timedelta(days=1)

    expect_booking_error(
        "PAST_START",
        past_start,
        past_start + timedelta(hours=1),
    )

    # Booking crosses midnight.
    expect_booking_error(
        "MULTI_DAY",
        start.replace(hour=23, minute=0),
        start.replace(hour=23, minute=0) + timedelta(hours=2),
    )


def test_cancellation():
    """Test cancellation with correct and incorrect car numbers."""

    start, end = get_test_period()

    # Use a separate slot to avoid overlapping the concurrency test.
    start = start.replace(hour=12)
    end = start + timedelta(hours=1)

    booking_ref = call_booking(
        TEST_FIRST_NAME,
        TEST_LAST_NAME,
        TEST_CAR_NUMBER,
        start,
        end,
    )

    wrong_car_result = call_cancel(
        booking_ref,
        "TS09XY9999",
    )

    assert wrong_car_result is False, (
        "Cancellation with the wrong car number should fail."
    )

    print("PASS: Wrong car number cannot cancel booking")

    correct_car_result = call_cancel(
        booking_ref,
        TEST_CAR_NUMBER,
    )

    assert correct_car_result is True, (
        "Cancellation with the correct car number should succeed."
    )

    print("PASS: Correct booking cancellation")

    repeated_result = call_cancel(
        booking_ref,
        TEST_CAR_NUMBER,
    )

    assert repeated_result is False, (
        "A cancelled booking should not be cancelled again."
    )

    print("PASS: Repeated cancellation is rejected")


def test_private_table_permissions():
    """Verify agent_role cannot read private tables."""

    private_tables = [
        "customers",
        "reservations",
        "reservation_history",
        "conversation_log",
    ]

    with psycopg.connect(AGENT_DSN) as conn:
        for table in private_tables:
            try:
                conn.execute(
                    f"SELECT * FROM public.{table} LIMIT 1"
                )

            except psycopg.errors.InsufficientPrivilege:
                conn.rollback()
                print(
                    f"PASS: agent_role cannot read {table}"
                )

            else:
                raise AssertionError(
                    f"agent_role unexpectedly has SELECT access to {table}"
                )


def concurrent_booking_attempt(index, start, end):
    """Attempt one booking using an independent database connection."""

    try:
        booking_ref = call_booking(
            first=TEST_FIRST_NAME,
            last=f"Tester{index}",
            car=TEST_CAR_NUMBER,
            start=start,
            end=end,
        )

        return {
            "status": "success",
            "booking_ref": booking_ref,
        }

    except psycopg.Error as exc:
        message = exc.diag.message_primary or str(exc)

        return {
            "status": "failure",
            "error": message.split(":")[0].strip(),
        }


def test_concurrent_bookings():
    """
    Attempt more bookings than available spaces for one time slot.

    Expected:
    - Exactly the available number of bookings succeed.
    - Remaining attempts return NO_SPACE_AVAILABLE.
    - No overlapping active reservations exist.
    """

    start, end = get_test_period()

    available_spaces = get_free_space_count(start, end)

    if available_spaces <= 0:
        print(
            "SKIP: No free spaces in the selected test period."
        )
        return

    attempts = available_spaces + 1

    print(
        f"\nConcurrency test: {attempts} attempts, "
        f"{available_spaces} available spaces"
    )

    with psycopg.connect(ADMIN_DSN) as conn:
        customers_before = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

    with ThreadPoolExecutor(
        max_workers=attempts
    ) as executor:
        results = list(
            executor.map(
                lambda index: concurrent_booking_attempt(
                    index,
                    start,
                    end,
                ),
                range(attempts),
            )
        )

    successful = [
        result
        for result in results
        if result["status"] == "success"
    ]

    failed = [
        result
        for result in results
        if result["status"] == "failure"
    ]

    assert len(successful) == available_spaces, (
        f"Expected {available_spaces} successful bookings, "
        f"got {len(successful)}"
    )

    assert len(failed) == 1, (
        f"Expected one failed booking, got {len(failed)}"
    )

    assert failed[0]["error"] == "NO_SPACE_AVAILABLE", (
        f"Unexpected failure: {failed[0]}"
    )

    with psycopg.connect(ADMIN_DSN) as conn:
        customers_after = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        overlapping = conn.execute(
            """
            SELECT COUNT(*)
            FROM reservations a
            JOIN reservations b
              ON a.space_id = b.space_id
             AND a.reservation_id < b.reservation_id
             AND a.period && b.period
            WHERE a.status = 'active'
              AND b.status = 'active'
              AND a.period && tsrange(%s, %s, '[)')
              AND b.period && tsrange(%s, %s, '[)')
            """,
            (start, end, start, end),
        ).fetchone()[0]

    customer_rows_created = customers_after - customers_before

    assert customer_rows_created == len(successful), (
        "Failed booking left behind a customer record."
    )

    assert overlapping == 0, (
        "Found overlapping active reservations."
    )

    print(
        f"PASS: {len(successful)} bookings succeeded"
    )
    print(
        f"PASS: {len(failed)} booking rejected with NO_SPACE_AVAILABLE"
    )
    print(
        "PASS: Failed transaction did not leave a customer record"
    )
    print(
        "PASS: No overlapping active reservations"
    )

    # Clean up successful test bookings by cancelling them.
    for result in successful:
        call_cancel(
            result["booking_ref"],
            TEST_CAR_NUMBER,
        )

    print("PASS: Test reservations cancelled")


def main():
    """Run the database test suite."""

    require_dsns()

    print("\n======================================")
    print("        DATABASE TEST SUITE")
    print("======================================")

    tests = [
        ("Price calculation", test_price_calculation),
        ("Booking validation", test_booking_validation),
        ("Private table permissions", test_private_table_permissions),
        ("Cancellation", test_cancellation),
        ("Concurrent bookings", test_concurrent_bookings),
    ]

    passed = 0
    failed = 0

    for name, test_function in tests:
        print(f"\n--- {name} ---")

        try:
            test_function()
            passed += 1

        except Exception as exc:
            failed += 1
            print(f"FAIL: {name}: {exc}")

    print("\n======================================")
    print("          DATABASE TEST RESULTS")
    print("======================================")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(tests)}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
