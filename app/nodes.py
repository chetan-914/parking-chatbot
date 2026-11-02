import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    get_buffer_string,
)
from langchain_openai import ChatOpenAI

from app.config import settings
from app.db import (
    BookingError,
    free_space_count,
    get_pricing_bands,
    get_working_hours,
    make_booking,
    quote_price,
    save_conversation_log,
)
from app.guardrails import mask_text, restore_text
from app.models import ExtractedFields, IntentResult
from app.prompts import SYSTEM_PROMPT, build_turn_prompt
from app.retrieval import format_search_results, search_static
from app.validators import (
    ValidationError,
    parse_local_datetime,
    validate_car_number,
    validate_name,
    validate_period,
)
from app.admin_client import send_approval_request
from app.admin_api import wait_for_admin_decision

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# LLM
# -------------------------------------------------------------------

def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_key,
    )


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _last_message(state: dict[str, Any], message_type: type):
    for message in reversed(state.get("messages", [])):
        if isinstance(message, message_type):
            return message
    return None


def _reservation(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("reservation") or {})


def _reservation_for_llm(reservation: dict[str, Any]) -> dict[str, Any]:
    """Do not expose original customer details to the LLM."""
    return {
        key: value
        for key, value in reservation.items()
        if not key.startswith("_")
    }


def _current_local_time() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _format_datetime(value: str | datetime | None) -> str:
    if value is None:
        return "not provided"

    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value)
    )
    return parsed.strftime("%d-%m-%Y %H:%M")


def _safe_error_message(exc: Exception) -> str:
    """Avoid returning database or infrastructure details to the user."""
    logger.exception("Parking chatbot operation failed", exc_info=exc)
    return "The service is temporarily unavailable. Please try again."


def _restore_extracted_fields(
    extracted: ExtractedFields,
    replacements: dict[str, str],
) -> dict[str, Any]:
    """Restore locally held PII placeholders after structured extraction."""
    values = extracted.model_dump(exclude_none=True)

    for key, value in values.items():
        if isinstance(value, str):
            values[key] = restore_text(value, replacements)

    return values


def _merge_reservation(
    existing: dict[str, Any],
    new_values: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)

    for key, value in new_values.items():
        if value is not None and value != "":
            merged[key] = value

    return merged


def _get_reminder(reservation: dict[str, Any], stage: str) -> str:
    """Return a reminder when the user asks an information question mid-booking."""
    if stage == "collecting":
        missing = []

        if not reservation.get("start"):
            missing.append("reservation date and time")

        if not reservation.get("end"):
            missing.append("reservation end time")

        if not reservation.get("first_name"):
            missing.append("first name")

        if not reservation.get("last_name"):
            missing.append("last name")

        if not reservation.get("car_number"):
            missing.append("vehicle registration number")

        if missing:
            return "After answering, ask the user for: " + ", ".join(missing)

    if stage == "awaiting_confirmation":
        return "After answering, repeat the reservation confirmation question."

    return ""


def _append_reminder(directive: str, state: dict[str, Any]) -> str:
    reminder = _get_reminder(
        _reservation(state),
        state.get("stage", "browsing"),
    )

    if reminder:
        return f"{directive}\n\n{reminder}"

    return directive


# -------------------------------------------------------------------
# Initialisation and human input
# -------------------------------------------------------------------

def init(state: dict[str, Any]) -> dict[str, Any]:
    """Initialise a new conversation."""
    conversation_id = state.get("conversation_id") or str(uuid.uuid4())

    return {
        "messages": [SystemMessage(content=SYSTEM_PROMPT)],
        "conversation_id": conversation_id,
        "started_at": datetime.now().isoformat(),
        "stage": "browsing",
        "intent": "other",
        "topics": [],
        "standalone_query": "",
        "reservation": {},
        "quote": {},
        "static_context": "",
        "dynamic_context": "",
        "directive": "",
        "warning": "",
        "booking_ref": "",
        "admin_request_id": None,
        "admin_approval_status": "NOT_REQUESTED",
        "admin_response": None,
        "admin_reason": None,
        "ended": False,
        "end_reason": "",
        "turn_count": 0,
    }


def human_input(state: dict[str, Any]) -> dict[str, Any]:
    """No-op node. The CLI supplies the human message before resuming."""
    return {}


# -------------------------------------------------------------------
# Input PII protection
# -------------------------------------------------------------------

def pii_check_input(state: dict[str, Any]) -> dict[str, Any]:
    """
    Mask PII before any LLM or embedding request.

    Original values are held in the local reservation dictionary.
    They are never added to the model-visible message history.
    """
    message = _last_message(state, HumanMessage)

    if message is None:
        return {}

    reservation = _reservation(state)

    try:
        masked = mask_text(str(message.content))

        replacements = dict(
            reservation.get("_pii_replacements", {})
        )
        replacements.update(masked.replacements)

        reservation["_pii_replacements"] = replacements

        warning = ""
        updates: dict[str, Any] = {}

        if masked.replacements:
            warning = (
                "Your message contained sensitive information. "
                "I masked it before processing."
            )

            # Replace the message using its original ID.
            updates["messages"] = [
                HumanMessage(
                    content=masked.text,
                    id=message.id,
                )
            ]

        updates.update({
            "reservation": reservation,
            "static_context": "",
            "dynamic_context": "",
            "directive": "",
            "warning": warning,
            "turn_count": state.get("turn_count", 0) + 1,
        })

        return updates

    except Exception:
        logger.exception("Input privacy check failed")

        return {
            "directive": (
                "The privacy filter is temporarily unavailable. "
                "Ask the user to rephrase without personal information."
            ),
            "warning": (
                "I could not safely process that message. "
                "Please rephrase it without personal details."
            ),
        }


# -------------------------------------------------------------------
# Intent classification
# -------------------------------------------------------------------

def classify_intent(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the latest redacted user message."""
    message = _last_message(state, HumanMessage)

    if message is None:
        return {
            "intent": "other",
            "topics": [],
            "standalone_query": "",
        }

    message_text = str(message.content).strip()

    try:
        classifier = get_llm().with_structured_output(IntentResult)
        result = classifier.invoke([
            SystemMessage(
                content=(
                    "Classify the user's latest message for a parking "
                    "facility assistant. The message may contain PII "
                    "placeholders. Never try to infer their original values."
                )
            ),
            *state.get("messages", []),
        ])

        intent = result.intent

        # Confirmation is valid only after a quote has been presented.
        if (
            intent in {"confirm_yes", "confirm_no"}
            and state.get("stage") != "awaiting_confirmation"
        ):
            intent = "other"

        # The first non-classified turn is treated as a greeting.
        if state.get("turn_count", 0) == 1 and intent == "other":
            intent = "greeting"

        return {
            "intent": intent,
            "topics": result.topics,
            "standalone_query": result.standalone_query or message_text,
        }

    except Exception:
        logger.exception("Intent classification failed")

        return {
            "intent": "other",
            "topics": [],
            "standalone_query": message_text,
        }


# -------------------------------------------------------------------
# Static retrieval
# -------------------------------------------------------------------

def retrieve_static(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve static facility information from Weaviate."""
    query = state.get("standalone_query") or "Parking facility overview"

    try:
        results = search_static(query, k=3)
        context = format_search_results(results)

        if not context:
            directive = (
                "Static facility information is temporarily unavailable. "
                "Explain that you cannot verify the requested information."
            )
        else:
            directive = (
                "Answer the user's latest information question using "
                "only the retrieved static facility information."
            )

        return {
            "static_context": context,
            "directive": _append_reminder(directive, state),
        }

    except Exception:
        logger.exception("Static retrieval failed")

        return {
            "static_context": "",
            "directive": _append_reminder(
                "Static facility information is temporarily unavailable. "
                "Do not invent facility details.",
                state,
            ),
        }


# -------------------------------------------------------------------
# Dynamic PostgreSQL retrieval
# -------------------------------------------------------------------

def query_dynamic(state: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve live facility information.

    Only aggregate availability, working hours and price information
    are included. No customer or reservation records are returned.
    """
    topics = set(state.get("topics", []))
    reservation = _reservation(state)
    lines = []

    try:
        if "hours" in topics:
            requested_date = None

            if reservation.get("start"):
                requested_date = datetime.fromisoformat(
                    reservation["start"]
                ).date()

            if requested_date is None:
                requested_date = _current_local_time().date()

            hours = get_working_hours(requested_date)

            if hours:
                lines.append(
                    f"Working hours: "
                    f"{hours['open_time']} to {hours['close_time']}."
                )
            else:
                lines.append("The facility is closed on that date.")

        if "prices" in topics:
            bands = get_pricing_bands()

            if bands:
                lines.append("Current pricing bands:")

                for band in bands:
                    lines.append(
                        f"{band['band_name']}: "
                        f"₹{band['hourly_rate']} per hour, "
                        f"{band['start_time']} to {band['end_time']}."
                    )

        if "availability" in topics:
            start = reservation.get("start")
            end = reservation.get("end")

            if start and end:
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end)
            else:
                start_dt = _current_local_time().replace(
                    minute=0 if _current_local_time().minute < 30 else 30
                )
                start_dt = start_dt + timedelta(hours=1)
                end_dt = start_dt + timedelta(hours=1)

            available = free_space_count(start_dt, end_dt)

            lines.append(
                f"Available spaces for "
                f"{start_dt:%d-%m-%Y %H:%M} to {end_dt:%H:%M}: "
                f"{available}."
            )

        if not lines:
            lines.append(
                "No dynamic facility information was requested."
            )

        directive = (
            "Answer the user's latest question using the live "
            "PostgreSQL information below. Do not invent values."
        )

        return {
            "dynamic_context": "\n".join(lines),
            "directive": _append_reminder(directive, state),
        }

    except Exception:
        logger.exception("Dynamic data retrieval failed")

        return {
            "dynamic_context": "",
            "directive": _append_reminder(
                "Live facility information is temporarily unavailable. "
                "Explain that you cannot verify the requested information.",
                state,
            ),
        }


# -------------------------------------------------------------------
# Reservation field extraction
# -------------------------------------------------------------------

def extract_fields(state: dict[str, Any]) -> dict[str, Any]:
    """
    Extract reservation fields from the latest redacted message.

    Names and car numbers are restored locally from the PII map.
    The LLM never receives their original values.
    """
    message = _last_message(state, HumanMessage)

    if message is None:
        return {}

    reservation = _reservation(state)
    replacements = reservation.get("_pii_replacements", {})

    try:
        extractor = get_llm().with_structured_output(ExtractedFields)

        result = extractor.invoke([
            SystemMessage(
                content=(
                    "Extract reservation fields from the user's message. "
                    "Return only explicitly stated values. "
                    "Dates must be ISO format YYYY-MM-DDTHH:MM. "
                    "PII placeholders may represent a name or vehicle "
                    "number. Preserve placeholders exactly if extracted. "
                    "Do not guess missing information."
                )
            ),
            *state.get("messages", []),
        ])

        values = _restore_extracted_fields(result, replacements)

        if values.get("first_name"):
            try:
                values["first_name"] = validate_name(values["first_name"])
            except ValidationError:
                values.pop("first_name", None)

        if values.get("last_name"):
            try:
                values["last_name"] = validate_name(values["last_name"])
            except ValidationError:
                values.pop("last_name", None)

        if values.get("car_number"):
            try:
                values["car_number"] = validate_car_number(
                    values["car_number"]
                )
            except ValidationError:
                values.pop("car_number", None)

        for key in ("start", "end"):
            if values.get(key):
                try:
                    values[key] = parse_local_datetime(
                        values[key]
                    ).isoformat(timespec="minutes")
                except ValidationError:
                    values.pop(key, None)

        merged = _merge_reservation(reservation, values)

        return {"reservation": merged}

    except Exception:
        logger.exception("Reservation field extraction failed")

        return {
            "directive": (
                "I could not understand all the reservation details. "
                "Ask the user to provide the details again."
            ),
            "stage": "collecting",
        }


# -------------------------------------------------------------------
# Reservation collection and quote
# -------------------------------------------------------------------

def collect_reservation(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic slot filling, validation and price quotation."""
    reservation = _reservation(state)

    start = reservation.get("start")
    end = reservation.get("end")

    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            validate_period(start_dt, end_dt)

        except ValidationError as exc:
            reservation.pop("start", None)
            reservation.pop("end", None)

            return {
                "reservation": reservation,
                "stage": "collecting",
                "quote": {},
                "directive": (
                    f"The requested period is invalid: {exc.message} "
                    "Ask the user for a new date and time."
                ),
            }

    elif bool(start) != bool(end):
        missing = "end time" if start else "start time"

        return {
            "stage": "collecting",
            "directive": (
                f"The user has supplied only one side of the reservation "
                f"period. Ask for the {missing}."
            ),
        }

    if start and end:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        try:
            available = free_space_count(start_dt, end_dt)

            if available == 0:
                alternatives = []

                for offset in range(30, 181, 30):
                    for direction in (1, -1):
                        candidate_start = (
                            start_dt + timedelta(minutes=offset * direction)
                        )
                        candidate_end = (
                            end_dt + timedelta(minutes=offset * direction)
                        )

                        try:
                            validate_period(candidate_start, candidate_end)
                            count = free_space_count(
                                candidate_start,
                                candidate_end,
                            )

                            if count > 0:
                                alternatives.append(
                                    f"{candidate_start:%H:%M}–"
                                    f"{candidate_end:%H:%M}"
                                )

                            if len(alternatives) >= 3:
                                break

                        except ValidationError:
                            continue

                    if len(alternatives) >= 3:
                        break

                reservation.pop("start", None)
                reservation.pop("end", None)

                alternative_text = (
                    "; ".join(alternatives)
                    if alternatives
                    else "No nearby alternatives were found."
                )

                return {
                    "reservation": reservation,
                    "stage": "collecting",
                    "quote": {},
                    "directive": (
                        "No parking spaces are available for that period. "
                        f"Offer these nearby alternatives: {alternative_text}. "
                        "Ask the user to choose another period."
                    ),
                }

        except Exception:
            logger.exception("Availability check failed")

            return {
                "directive": (
                    "I could not check availability right now. "
                    "Ask the user to try again shortly."
                ),
                "stage": "collecting",
            }

    if reservation.get("car_number"):
        try:
            reservation["car_number"] = validate_car_number(
                reservation["car_number"]
            )
        except ValidationError:
            reservation.pop("car_number", None)

            return {
                "reservation": reservation,
                "stage": "collecting",
                "directive": (
                    "The vehicle registration number is invalid. "
                    "Ask the user to enter a valid Indian registration "
                    "number, for example TS09AB1234."
                ),
            }

    if not reservation.get("start") or not reservation.get("end"):
        return {
            "reservation": reservation,
            "stage": "collecting",
            "directive": (
                "Ask the user for the reservation date, start time "
                "and end time."
            ),
        }

    missing = []

    for key, label in (
        ("first_name", "first name"),
        ("last_name", "last name"),
        ("car_number", "vehicle registration number"),
    ):
        if not reservation.get(key):
            missing.append(label)

    if missing:
        return {
            "reservation": reservation,
            "stage": "collecting",
            "directive": (
                "Ask the user to provide the following missing details: "
                + ", ".join(missing)
                + "."
            ),
        }

    try:
        start_dt = datetime.fromisoformat(reservation["start"])
        end_dt = datetime.fromisoformat(reservation["end"])

        # Compute the quote using PostgreSQL, not the LLM.
        price = quote_price(start_dt, end_dt)
        available = free_space_count(start_dt, end_dt)

        if available <= 0:
            reservation.pop("start", None)
            reservation.pop("end", None)

            return {
                "reservation": reservation,
                "stage": "collecting",
                "quote": {},
                "directive": (
                    "No spaces are currently available for that period. "
                    "Ask the user to choose another time."
                ),
            }

        quote = {
            "total_price": price,
            "free_spaces": available,
        }

        return {
            "reservation": reservation,
            "quote": quote,
            "stage": "awaiting_confirmation",
            "directive": (
                "Present the reservation summary and ask the user to "
                "confirm or decline. Include the customer's name, vehicle "
                "number, date, start time, end time and exact total price "
                f"of ₹{price}. Do not book yet."
            ),
        }

    except Exception:
        logger.exception("Reservation quotation failed")

        return {
            "stage": "collecting",
            "directive": (
                "I could not calculate the reservation price right now. "
                "Ask the user to try again."
            ),
        }


# -------------------------------------------------------------------
# Administrator approval request
# -------------------------------------------------------------------

def request_admin_approval(state: dict[str, Any]) -> dict[str, Any]:
    """
    Send the reservation details to the administrator for approval.

    This node runs only after the customer confirms the quotation.
    It does not create a booking.
    """

    reservation = _reservation(state)

    if state.get("admin_approval_status") == "APPROVED":
        return {
            "directive": "The administrator has already approved this request."
        }

    if state.get("admin_approval_status") == "PENDING":
        return {
            "directive": "Your reservation request is already awaiting administrator approval."
        }

    required_fields = (
        "first_name",
        "last_name",
        "car_number",
        "start",
        "end",
    )

    if any(not reservation.get(field) for field in required_fields):
        return {
            "admin_approval_status": "UNCLEAR",
            "directive": (
                "The reservation details are incomplete. "
                "Please collect all required details again."
            ),
        }

    if state.get("stage") != "awaiting_confirmation":
        return {
            "directive": (
                "The reservation has not been confirmed by the customer. "
                "Do not send an approval request."
            )
        }

    request_id = (
        state.get("admin_request_id") or str(uuid.uuid4())
    )

    quote = state.get("quote", {})

    # These details are sent directly to the administrator.
    # They are not passed to the LLM.
    reservation_details = {
        "Customer name": (
            f"{reservation['first_name']} {reservation['last_name']}"
        ),
        "Vehicle registration": reservation["car_number"],
        "Start time": _format_datetime(reservation["start"]),
        "End time": _format_datetime(reservation["end"]),
        "Estimated price": f"₹{quote.get('total_price', 'Not available')}",
        "Available spaces": quote.get("free_spaces", "Not available"),
    }

    try:
        send_approval_request(
            request_id=request_id,
            reservation_details=reservation_details,
        )

        logger.info(
            "Reservation approval request sent. Request ID: %s",
            request_id,
        )

        return {
            "admin_request_id": request_id,
            "admin_approval_status": "PENDING",
            "admin_response": None,
            "admin_reason": None,
            "stage": "awaiting_admin_approval",
            "directive": (
                "Your reservation request has been sent to the "
                "administrator for approval. Explain that the booking "
                "is not confirmed yet and that the customer will be "
                "informed after the administrator responds."
            ),
        }

    except Exception:
        logger.exception("Could not send administrator approval request")

        return {
            "admin_request_id": request_id,
            "admin_approval_status": "UNCLEAR",
            "stage": "awaiting_confirmation",
            "directive": (
                "I could not send your reservation request to the "
                "administrator. No booking has been created. "
                "Apologise and ask the customer to try again."
            ),
        }


def wait_admin_approval(state: dict[str, Any]) -> dict[str, Any]:
    """
    Wait for the administrator's email response.

    Booking creation is not performed in this node.
    """

    request_id = state.get("admin_request_id")

    if not request_id:
        return {
            "admin_approval_status": "UNCLEAR",
            "directive": (
                "There is no administrator approval request ID. "
                "The reservation cannot proceed."
            ),
        }

    try:
        decision = wait_for_admin_decision(request_id)

        status = decision.decision

        if status == "APPROVE":
            return {
                "admin_approval_status": "APPROVED",
                "admin_response": "APPROVE",
                "admin_reason": decision.reason,
                "stage": "awaiting_admin_booking",
                "directive": (
                    "The administrator has approved the reservation. "
                    "Proceed with the booking operation."
                ),
            }

        if status == "REJECT":
            return {
                "admin_approval_status": "REJECTED",
                "admin_response": "REJECT",
                "admin_reason": decision.reason,
                "stage": "browsing",
                "ended": True,
                "end_reason": "admin_rejected",
                "directive": (
                    "The administrator has rejected the reservation. "
                    "Politely inform the customer that the reservation "
                    "could not be approved. Do not create a booking."
                ),
            }

        return {
            "admin_approval_status": "UNCLEAR",
            "admin_response": "UNCLEAR",
            "admin_reason": decision.reason,
            "stage": "awaiting_confirmation",
            "directive": (
                "The administrator's decision could not be confirmed. "
                "Inform the customer that the reservation is not confirmed "
                "and that no booking has been created."
            ),
        }

    except Exception:
        logger.exception("Administrator approval processing failed")

        return {
            "admin_approval_status": "UNCLEAR",
            "directive": (
                "The administrator's response could not be processed. "
                "No booking has been created."
            ),
        }
    

# -------------------------------------------------------------------
# Booking write
# -------------------------------------------------------------------

def write_booking(state: dict[str, Any]) -> dict[str, Any]:
    """Revalidate and write a confirmed booking through PostgreSQL."""
    if state.get("admin_approval_status") != "APPROVED":
        return {
            "directive": (
                "The booking cannot be created because administrator "
                "approval has not been received."
            )
        }

    reservation = _reservation(state)

    try:
        start = datetime.fromisoformat(reservation["start"])
        end = datetime.fromisoformat(reservation["end"])

        validate_period(start, end)

        booking_ref = make_booking(
            first_name=reservation["first_name"],
            last_name=reservation["last_name"],
            car_number=reservation["car_number"],
            start=start,
            end=end,
            conversation_id=state["conversation_id"],
        )

        return {
            "booking_ref": booking_ref,
            "ended": True,
            "end_reason": "booked",
            "stage": "browsing",
            "directive": (
                "The booking was successful. Confirm the reservation, "
                f"provide booking reference {booking_ref}, and mention "
                f"the quoted total of ₹{state.get('quote', {}).get('total_price')}."
                " Say goodbye."
            ),
            "admin_approval_status": "APPROVED",
        }

    except ValidationError as exc:
        return {
            "stage": "collecting",
            "reservation": {
                **reservation,
                "start": None,
                "end": None,
            },
            "quote": {},
            "directive": (
                f"The reservation period is no longer valid: {exc.message} "
                "Ask the user for another period."
            ),
        }

    except BookingError as exc:
        code = getattr(exc, "code", "BOOKING_FAILED")

        if code in {
            "NO_SPACE_AVAILABLE",
            "INVALID_PERIOD",
            "PAST_START",
            "TOO_FAR",
            "MULTI_DAY",
            "NOT_ON_GRID",
            "BAD_DURATION",
            "OUTSIDE_HOURS",
        }:
            return {
                "stage": "collecting",
                "reservation": {
                    **reservation,
                    "start": None,
                    "end": None,
                },
                "quote": {},
                "directive": (
                    "The booking could not be completed because the "
                    "space is no longer available or the period is invalid. "
                    "Apologise and ask the user to choose another period."
                ),
            }

        logger.exception("Booking failed")
        return {
            "directive": (
                "I could not complete the booking. No confirmation "
                "has been issued. Ask the user to try again."
            )
        }

    except Exception:
        logger.exception("Unexpected booking failure")

        return {
            "directive": (
                "I could not complete the booking right now. "
                "Please try again."
            )
        }


# -------------------------------------------------------------------
# Farewell
# -------------------------------------------------------------------

def farewell(state: dict[str, Any]) -> dict[str, Any]:
    """End the conversation without creating a booking."""
    reservation_in_progress = bool(
        state.get("reservation")
    )

    return {
        "ended": True,
        "end_reason": (
            "cancelled" if reservation_in_progress else "goodbye"
        ),
        "reservation": {},
        "quote": {},
        "directive": (
            "Say a brief goodbye. If a reservation was in progress, "
            "clearly explain that no booking was made."
        ),
    }


# -------------------------------------------------------------------
# Response generation
# -------------------------------------------------------------------

def respond(state: dict[str, Any]) -> dict[str, Any]:
    """
    Generate the user-facing response.

    Reservation confirmation summaries are generated locally
    so that actual customer PII is never sent to the LLM.
    """

    directive = state.get("directive", "")
    static_context = state.get("static_context", "")
    dynamic_context = state.get("dynamic_context", "")

    # Generate reservation confirmation locally.
    if (
        state.get("stage") == "awaiting_confirmation"
        and state.get("quote")
    ):
        reservation = _reservation(state)
        quote = state.get("quote", {})

        try:
            start = datetime.fromisoformat(reservation["start"])
            end = datetime.fromisoformat(reservation["end"])

            full_name = (
                f"{reservation.get('first_name', '')} "
                f"{reservation.get('last_name', '')}"
            ).strip()

            car_number = reservation.get("car_number", "")

            total_price = float(quote["total_price"])

            summary = f"""Please review your parking reservation:

- **Name:** {full_name}
- **Vehicle:** {car_number}
- **Date:** {start.strftime("%B %d, %Y")}
- **Time:** {start.strftime("%I:%M %p").lstrip("0")}–{end.strftime("%I:%M %p").lstrip("0")}
- **Total:** ₹{total_price:,.2f}

Would you like to confirm or decline?"""

            return {
                "messages": [AIMessage(content=summary)]
            }

        except Exception:
            logger.exception("Could not generate reservation summary")

            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I couldn't prepare your reservation summary. "
                            "Please try again."
                        )
                    )
                ]
            }

    # Normal LLM response for all other conversation turns.
    turn_prompt = build_turn_prompt(
        directive=directive,
        static_context=static_context,
        dynamic_context=dynamic_context,
    )

    messages = [
        message
        for message in state.get("messages", [])
        if not isinstance(message, SystemMessage)
    ]

    try:
        response = get_llm().invoke(
            messages + [SystemMessage(content=turn_prompt)]
        )

        return {"messages": [response]}

    except Exception:
        logger.exception("Response generation failed")

        return {
            "messages": [
                AIMessage(
                    content=(
                        "I'm sorry, but I couldn't prepare a response "
                        "right now. Please try again."
                    )
                )
            ]
        }


# -------------------------------------------------------------------
# Output PII protection
# -------------------------------------------------------------------

def pii_check_output(state: dict[str, Any]) -> dict[str, Any]:
    """
    Protect assistant output while allowing the customer's own
    reservation details to be displayed.
    """

    message = _last_message(state, AIMessage)

    if message is None:
        return {}

    reservation = _reservation(state)

    allowed_values = {
        value
        for key, value in reservation.items()
        if key in {"first_name", "last_name", "car_number"}
        and isinstance(value, str)
        and value
    }

    try:
        # Explicitly provide known reservation PII to the masker.
        masked = mask_text(
            str(message.content),
            known_names=[
                reservation.get("first_name", ""),
                reservation.get("last_name", ""),
            ],
            known_car_numbers=[
                reservation.get("car_number", ""),
            ],
        )

        safe_text = masked.text

        # Restore only the current customer's own reservation details.
        for placeholder, original in masked.replacements.items():
            if original in allowed_values:
                safe_text = safe_text.replace(placeholder, original)

        if safe_text != str(message.content):
            return {
                "messages": [
                    AIMessage(
                        content=safe_text,
                        id=message.id,
                    )
                ],
                "warning": (
                    "Part of my reply was removed by the privacy filter."
                ),
            }

        return {}

    except Exception:
        logger.exception("Output privacy check failed")

        return {
            "messages": [
                AIMessage(
                    content=(
                        "I couldn't safely prepare that response. "
                        "Please try again."
                    ),
                    id=message.id,
                )
            ],
            "warning": (
                "The privacy filter blocked part of the response."
            ),
        }


# -------------------------------------------------------------------
# Transcript persistence
# -------------------------------------------------------------------

def save_transcript(state: dict[str, Any]) -> dict[str, Any]:
    """
    Save a redacted transcript.

    The conversation log must never contain names or vehicle numbers.
    """
    transcript = get_buffer_string(
        [
            message
            for message in state.get("messages", [])
            if not isinstance(message, SystemMessage)
        ]
    )

    reservation = _reservation(state)

    try:
        masked = mask_text(
            transcript,
            known_names=[
                reservation.get("first_name", ""),
                reservation.get("last_name", ""),
            ],
            known_car_numbers=[
                reservation.get("car_number", ""),
            ],
        )

        save_conversation_log(
            conversation_id=state["conversation_id"],
            transcript=masked.text,
            end_reason=state.get("end_reason", "goodbye"),
            turn_count=state.get("turn_count", 0),
            started_at=datetime.now()
        )

    except Exception:
        # Do not expose transcript contents or PII in logs.
        logger.exception("Could not save conversation transcript")

    return {
        "reservation": {},
        "quote": {},
    }