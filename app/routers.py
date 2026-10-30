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

    Possible destinations:
        retrieve_static
        query_dynamic
        extract_fields
        write_booking
        farewell

    Static and dynamic retrieval can run in parallel.
    """
    intent = state.get("intent", "other")
    stage = state.get("stage", "browsing")
    topics = set(state.get("topics", []))

    # 1. User wants to end the conversation.
    if intent == "end_chat":
        return "farewell"

    # 2. Handle confirmation responses only at the confirmation stage.
    if stage == "awaiting_confirmation":
        if intent == "confirm_yes":
            return "write_booking"

        if intent == "confirm_no":
            return "farewell"

    # 3. Reservation request or correction.
    if intent == "reserve":
        return "extract_fields"

    # 4. Greeting: retrieve the facility overview.
    if intent == "greeting":
        return "retrieve_static"

    # 5. Information request: determine which data stores are needed.
    needs_static = bool(topics & STATIC_TOPICS)
    needs_dynamic = bool(topics & DYNAMIC_TOPICS)

    if needs_static and needs_dynamic:
        return ["retrieve_static", "query_dynamic"]

    if needs_static:
        return "retrieve_static"

    if needs_dynamic:
        return "query_dynamic"

    # 6. Default to static retrieval for unclear or general questions.
    return "retrieve_static"


def route_after_output(state: dict[str, Any]) -> str:
    """
    Decide whether the conversation should continue or finish.

    The graph pauses before human_input for the next user message.
    Completed conversations are sent to save_transcript.
    """
    if state.get("ended", False):
        return "save_transcript"

    return "human_input"