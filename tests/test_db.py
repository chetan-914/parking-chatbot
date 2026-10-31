import os

import psycopg
import pytest


DATABASE_DSN = os.getenv("POSTGRES_AGENT_DSN")

pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="POSTGRES_AGENT_DSN is not configured",
)


@pytest.fixture
def db_connection():
    conn = psycopg.connect(DATABASE_DSN)
    try:
        yield conn
    finally:
        conn.close()


def test_database_connection(db_connection):
    with db_connection.cursor() as cur:
        cur.execute("SELECT 1")
        result = cur.fetchone()

    assert result == (1,)


def test_required_tables_exist(db_connection):
    required_tables = {
        "customers",
        "parking_spaces",
        "reservations",
    }

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
        existing_tables = {row[0] for row in cur.fetchall()}

    missing_tables = required_tables - existing_tables

    assert not missing_tables, (
        f"Missing required database tables: {sorted(missing_tables)}"
    )


def test_booking_functions_exist(db_connection):
    required_functions = {
        "create_reservation",
        "cancel_reservation",
    }

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_schema = 'public'
              AND routine_type = 'FUNCTION'
            """
        )
        existing_functions = {row[0] for row in cur.fetchall()}

    missing_functions = required_functions - existing_functions

    assert not missing_functions, (
        f"Missing required database functions: {sorted(missing_functions)}"
    )


def test_parking_spaces_are_seeded(db_connection):
    with db_connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM parking_spaces")
        count = cur.fetchone()[0]

    assert count == 20


def test_parking_space_identifiers_are_unique(db_connection):
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT space_number)
            FROM parking_spaces
            """
        )
        total, distinct_total = cur.fetchone()

    assert total == distinct_total