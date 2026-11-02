
import fcntl
import json
import logging
import os
import re
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.validators import validate_car_number


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

logger = logging.getLogger("parking-mcp-server")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

RESERVATIONS_FILE = DATA_DIR / "approved_reservations.txt"
JOURNAL_FILE = DATA_DIR / ".reservation_journal.jsonl"
LOCK_FILE = DATA_DIR / ".reservations.lock"

mcp = FastMCP("parking-reservation-storage")


# ---------------------------------------------------------
# Validation
# ---------------------------------------------------------

def validate_text(value: str, field: str) -> str:
    """Validate text fields before writing to storage."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} cannot be empty.")

    value = value.strip()

    # Prevent file-format injection and multiline entries.
    if any(char in value for char in ("|", "\n", "\r")):
        raise ValueError(f"Invalid characters in {field}.")

    return value


def validate_reservation(
    request_id: str,
    name: str,
    car_number: str,
    reservation_period: str,
    approval_time: str,
) -> dict[str, str]:
    """Validate all reservation fields independently."""

    request_id = validate_text(request_id, "Request ID")
    name = validate_text(name, "Name")
    car_number = validate_text(car_number, "Car number")
    reservation_period = validate_text(
        reservation_period,
        "Reservation period",
    )
    approval_time = validate_text(approval_time, "Approval time")

    if len(request_id) > 128:
        raise ValueError("Invalid request ID.")

    # Validate and normalize the Indian vehicle registration.
    car_number = validate_car_number(car_number)

    # Verify the approval timestamp.
    datetime.fromisoformat(approval_time)

    return {
        "request_id": request_id,
        "name": name,
        "car_number": car_number,
        "reservation_period": reservation_period,
        "approval_time": approval_time,
    }


# ---------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------

def load_journal() -> list[dict[str, Any]]:
    """Load previously processed reservation requests."""

    records = []

    if not JOURNAL_FILE.exists():
        return records

    with JOURNAL_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))

    return records


def rebuild_reservation_file(
    records: list[dict[str, Any]],
) -> None:
    """
    Atomically rebuild the readable reservation file.

    The journal is the durable source of truth. This allows
    the text file to be recovered after an interrupted write.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=DATA_DIR,
        delete=False,
    ) as temp_file:

        temp_path = Path(temp_file.name)

        for record in records:
            temp_file.write(
                f"{record['name']} | "
                f"{record['car_number']} | "
                f"{record['reservation_period']} | "
                f"{record['approval_time']}\n"
            )

        temp_file.flush()
        os.fsync(temp_file.fileno())

    os.replace(temp_path, RESERVATIONS_FILE)

    # Persist the directory entry on Linux.
    directory_fd = os.open(DATA_DIR, os.O_RDONLY)

    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


# ---------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------

@mcp.tool()
def save_confirmed_reservation(
    request_id: str,
    name: str,
    car_number: str,
    reservation_period: str,
    approval_time: str,
) -> str:
    """
    Save an administrator-approved parking reservation.

    Args:
        request_id: Unique administrator approval request ID.
        name: Customer's full name.
        car_number: Customer's vehicle registration number.
        reservation_period: Reservation start and end period.
        approval_time: Administrator approval timestamp in ISO format.

    Returns:
        A message indicating whether the reservation was saved.
    """

    try:
        record = validate_reservation(
            request_id=request_id,
            name=name,
            car_number=car_number,
            reservation_period=reservation_period,
            approval_time=approval_time,
        )

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Protect concurrent writes.
        with LOCK_FILE.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            try:
                records = load_journal()

                existing = next(
                    (
                        item
                        for item in records
                        if item["request_id"] == record["request_id"]
                    ),
                    None,
                )

                if existing:
                    # Repair the readable file if a previous operation
                    # was interrupted after the journal was committed.
                    rebuild_reservation_file(records)

                    return (
                        "Reservation was already saved. "
                        f"Request ID: {request_id}"
                    )

                # Journal first: it is the durable source of truth.
                with JOURNAL_FILE.open(
                    "a",
                    encoding="utf-8",
                ) as journal:

                    journal.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )

                    journal.flush()
                    os.fsync(journal.fileno())

                records.append(record)

                # Rebuild the human-readable text file.
                rebuild_reservation_file(records)

                logger.info(
                    "Approved reservation saved. Request ID: %s",
                    request_id,
                )

                return (
                    "Reservation successfully saved. "
                    f"Request ID: {request_id}"
                )

            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    except Exception:
        logger.exception("Reservation storage operation failed")
        raise ValueError("Unable to save the confirmed reservation.")


# ---------------------------------------------------------
# Start MCP server
# ---------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    mcp.run(transport="stdio")
