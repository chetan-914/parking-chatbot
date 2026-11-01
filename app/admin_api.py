
import time

from app.admin_agent import AdminDecision, interpret_admin_reply
from app.admin_client import fetch_admin_replies
from app.config import settings


# Avoid processing the same email repeatedly during this process.
_processed_message_ids: set[str] = set()


def check_admin_responses(
    request_id: str,
) -> AdminDecision | None:
    """
    Check the administrator mailbox for a decision on a request.

    Returns:
        AdminDecision: When a matching explicit decision is received.
        None: When no valid decision is available yet.
    """

    try:
        replies = fetch_admin_replies()

        for reply in replies:
            message_id = reply.get("message_id", "")

            if message_id and message_id in _processed_message_ids:
                continue

            if message_id:
                _processed_message_ids.add(message_id)

            subject = reply.get("subject", "")
            body = reply.get("body", "")

            email_content = f"""
Subject: {subject}

{body}
"""

            decision = interpret_admin_reply(
                email_content=email_content,
                expected_request_id=request_id,
            )

            if decision.decision in {"APPROVE", "REJECT"}:
                return decision

    except Exception as exc:
        print(f"Administrator email check failed: {exc}")

    return None


def wait_for_admin_decision(
    request_id: str,
    timeout_seconds: int = 86400,
) -> AdminDecision:
    """
    Wait for the administrator to approve or reject a reservation.

    Checks the mailbox at the configured polling interval.

    Returns UNCLEAR if no valid decision arrives before timeout.
    """

    start_time = time.monotonic()

    poll_interval = max(
        5,
        settings.admin_email_poll_interval,
    )

    print(
        f"Waiting for administrator approval "
        f"for request {request_id}..."
    )

    while time.monotonic() - start_time < timeout_seconds:

        decision = check_admin_responses(request_id)

        if decision is not None:
            print(
                f"Administrator decision received: "
                f"{decision.decision}"
            )
            return decision

        time.sleep(poll_interval)

    return AdminDecision(
        request_id=request_id,
        decision="UNCLEAR",
        reason="Administrator response timed out.",
    )
