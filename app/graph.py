
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
    respond,
    retrieve_static,
    save_transcript,
    write_booking,
)
from app.routers import route_after_output, route_intent
from app.state import ParkingState


def build_graph():
    """Build and compile the parking reservation chatbot graph."""

    builder = StateGraph(ParkingState)

    # Register nodes
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

    # Main conversation flow
    builder.add_edge(START, "init")
    builder.add_edge("init", "human_input")

    builder.add_edge("human_input", "pii_check_input")
    builder.add_edge("pii_check_input", "classify_intent")

    # Route based on detected intent
    builder.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            "retrieve_static": "retrieve_static",
            "query_dynamic": "query_dynamic",
            "extract_fields": "extract_fields",
            "write_booking": "write_booking",
            "farewell": "farewell",
        },
    )

    # Individual branches return to the response node.
    # Keep these as separate edges: list-form edges would wait
    # for all branches to finish.
    builder.add_edge("retrieve_static", "respond")
    builder.add_edge("query_dynamic", "respond")
    builder.add_edge("extract_fields", "collect_reservation")
    builder.add_edge("collect_reservation", "respond")
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
