
from typing import Any


STATIC_TOPICS = {
    "general",
    "booking_process",
    "policy",
    "rules",
    "facilities",
    "payment",
}

DYNAMIC_TOPICS = {
    "prices",
    "hours",
    "availability",
}


def route_intent(state: dict[str, Any]) -> str | list[str]:
    """
    Route the conversation after intent classification.
    """

    intent = state.get("intent", "other")
    stage = state.get("stage", "browsing")
    topics = set(state.get("topics", []))

    # 1. User wants to end the conversation.
    if intent == "end_chat":
        return "farewell"

    # 2. Customer confirms or declines the reservation quote.
    if stage == "awaiting_confirmation":
        if intent == "confirm_yes":
            return "request_admin_approval"

        if intent == "confirm_no":
            return "farewell"

    # 3. Reservation request or correction.
    if intent == "reserve":
        return "extract_fields"

    # 4. Greeting: retrieve the facility overview.
    if intent == "greeting":
        return "retrieve_static"

    # 5. Information request: determine required data stores.
    needs_static = bool(topics & STATIC_TOPICS)
    needs_dynamic = bool(topics & DYNAMIC_TOPICS)

    if needs_static and needs_dynamic:
        return ["retrieve_static", "query_dynamic"]

    if needs_static:
        return "retrieve_static"

    if needs_dynamic:
        return "query_dynamic"

    # 6. Default to static retrieval.
    return "retrieve_static"


def route_after_admin_request(state: dict[str, Any]) -> str:
    """
    Route after sending the administrator approval email.
    """

    status = state.get("admin_approval_status")

    if status == "PENDING":
        return "wait_admin_approval"

    # If sending failed, inform the customer.
    return "respond"


def route_after_admin_approval(state: dict[str, Any]) -> str:
    """
    Route based on the administrator's decision.
    """

    status = state.get("admin_approval_status")

    if status == "APPROVED":
        return "write_booking"

    # REJECTED and UNCLEAR must never reach write_booking.
    return "respond"


def route_after_output(state: dict[str, Any]) -> str:
    """
    Decide whether the conversation should continue or finish.
    """

    if state.get("ended", False):
        return "save_transcript"

    return "human_input"
