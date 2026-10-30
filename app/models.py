from typing import Literal

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """Structured output returned by the intent classifier."""

    intent: Literal[
        "greeting",
        "info",
        "reserve",
        "confirm_yes",
        "confirm_no",
        "end_chat",
        "other",
    ] = Field(
        description="What the user wants in their latest message."
    )

    topics: list[
        Literal[
            "general",
            "booking_process",
            "policy",
            "rules",
            "facilities",
            "payment",
            "prices",
            "hours",
            "availability",
        ]
    ] = Field(
        default_factory=list,
        description=(
            "Topics the latest message asks about. "
            "Return an empty list if no topic applies."
        ),
    )

    standalone_query: str = Field(
        default="",
        description=(
            "Rewrite the latest message as a self-contained "
            "search query using relevant conversation context."
        ),
    )


class ExtractedFields(BaseModel):
    """Reservation details extracted from a user's message."""

    first_name: str | None = Field(
        default=None,
        description="First name if stated, otherwise null.",
    )

    last_name: str | None = Field(
        default=None,
        description="Last name if stated, otherwise null.",
    )

    car_number: str | None = Field(
        default=None,
        description=(
            "Vehicle registration number if stated, "
            "otherwise null."
        ),
    )

    start: str | None = Field(
        default=None,
        description=(
            "Reservation start as YYYY-MM-DDTHH:MM, "
            "otherwise null."
        ),
    )

    end: str | None = Field(
        default=None,
        description=(
            "Reservation end as YYYY-MM-DDTHH:MM, "
            "otherwise null."
        ),
    )