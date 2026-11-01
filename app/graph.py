
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.nodes import (
    classify_intent,
    collect_reservation,
    extract_fields,
    farewell,
    human_input,
    init,
    pii_check_input,
    pii_check_output,
    query_dynamic,
    request_admin_approval,
    respond,
    retrieve_static,
    save_transcript,
    wait_admin_approval,
    write_booking,
)

from app.routers import (
    route_after_admin_approval,
    route_after_admin_request,
    route_after_output,
    route_intent,
)

from app.state import ParkingState


def build_graph():
    """Build and compile the parking reservation chatbot graph."""

    builder = StateGraph(ParkingState)

    # Register existing nodes
    builder.add_node("init", init)
    builder.add_node("human_input", human_input)
    builder.add_node("pii_check_input", pii_check_input)
    builder.add_node("classify_intent", classify_intent)

    builder.add_node("retrieve_static", retrieve_static)
    builder.add_node("query_dynamic", query_dynamic)

    builder.add_node("extract_fields", extract_fields)
    builder.add_node("collect_reservation", collect_reservation)

    builder.add_node("write_booking", write_booking)
    builder.add_node("farewell", farewell)
    builder.add_node("respond", respond)

    builder.add_node("pii_check_output", pii_check_output)
    builder.add_node("save_transcript", save_transcript)

    # New administrator agent workflow nodes
    builder.add_node(
        "request_admin_approval",
        request_admin_approval,
    )

    builder.add_node(
        "wait_admin_approval",
        wait_admin_approval,
    )

    # Main conversation flow
    builder.add_edge(START, "init")
    builder.add_edge("init", "human_input")

    builder.add_edge("human_input", "pii_check_input")
    builder.add_edge("pii_check_input", "classify_intent")

    # Route based on customer intent
    builder.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            "retrieve_static": "retrieve_static",
            "query_dynamic": "query_dynamic",
            "extract_fields": "extract_fields",
            "request_admin_approval": "request_admin_approval",
            "farewell": "farewell",
        },
    )

    # Existing retrieval and reservation collection flow
    builder.add_edge("retrieve_static", "respond")
    builder.add_edge("query_dynamic", "respond")

    builder.add_edge("extract_fields", "collect_reservation")
    builder.add_edge("collect_reservation", "respond")

    # Administrator approval workflow
    builder.add_conditional_edges(
        "request_admin_approval",
        route_after_admin_request,
        {
            "wait_admin_approval": "wait_admin_approval",
            "respond": "respond",
        },
    )

    # Continue based on administrator decision
    builder.add_conditional_edges(
        "wait_admin_approval",
        route_after_admin_approval,
        {
            "write_booking": "write_booking",
            "respond": "respond",
        },
    )

    # Booking and farewell
    builder.add_edge("write_booking", "respond")
    builder.add_edge("farewell", "respond")

    # Output privacy check
    builder.add_edge("respond", "pii_check_output")

    # Continue conversation or finish
    builder.add_conditional_edges(
        "pii_check_output",
        route_after_output,
        {
            "human_input": "human_input",
            "save_transcript": "save_transcript",
        },
    )

    builder.add_edge("save_transcript", END)

    # In-memory conversation checkpointing
    memory = MemorySaver()

    return builder.compile(
        checkpointer=memory,
        interrupt_before=["human_input"],
    )


# Compiled graph instance
graph = build_graph()
