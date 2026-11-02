from typing import Any, Literal
from datetime import datetime

from langgraph.graph import MessagesState


class ParkingState(MessagesState):
    """
    Shared state for the parking reservation chatbot.

    MessagesState provides the `messages` field with LangGraph's
    add_messages reducer.

    All other fields are ordinary state values without reducers.
    """

    # Conversation metadata
    conversation_id: str
    started_at: str

    # Conversation stage:
    # browsing, collecting, awaiting_confirmation
    stage: str

    # Intent classification
    intent: str
    topics: list[str]
    standalone_query: str

    # Reservation details
    # Dates are stored as ISO strings for checkpoint serialization.
    reservation: dict[str, Any]

    # Price and availability information
    quote: dict[str, Any]

    # Retrieved information
    # These are separate because retrieval nodes can run in parallel.
    static_context: str
    dynamic_context: str

    # Instructions for the response-generation node
    directive: str

    # PII and guardrail warning for the CLI.
    # This field must never be sent to the LLM.
    warning: str

    # Booking result
    booking_ref: str

    # Conversation completion
    ended: bool
    end_reason: str

    # Number of user turns
    turn_count: int

    # Administrator approval workflow
    admin_request_id: str | None
    admin_approval_status: Literal[
        "NOT_REQUESTED",
        "PENDING",
        "APPROVED",
        "REJECTED",
        "UNCLEAR",
    ]

    admin_response: str | None
    admin_reason: str | None
    admin_approved_at: datetime | None
    mcp_storage_status: str