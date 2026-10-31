import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph import build_graph


@pytest.fixture
def graph():
    return build_graph()


def test_graph_compiles(graph):
    assert graph is not None


def test_graph_has_expected_nodes(graph):
    expected_nodes = {
        "init",
        "human_input",
        "pii_check_input",
        "router",
        "farewell",
    }

    actual_nodes = set(graph.get_graph().nodes)

    assert expected_nodes.issubset(actual_nodes)


def test_graph_starts_with_initial_state(graph):
    initial_state = {
        "messages": [],
        "stage": "greeting",
        "turn_count": 0,
        "ended": False,
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": "test-start"}},
        interrupt_before=["human_input"],
    )

    assert isinstance(result, dict)
    assert "messages" in result
    assert result["stage"] == "greeting"


def test_graph_preserves_conversation_thread(graph):
    config = {
        "configurable": {
            "thread_id": "test-persistent-thread",
        }
    }

    initial_state = {
        "messages": [HumanMessage(content="Hello")],
        "stage": "greeting",
        "turn_count": 0,
        "ended": False,
    }

    graph.invoke(initial_state, config=config)

    saved_state = graph.get_state(config)

    assert saved_state is not None
    assert saved_state.values


def test_graph_uses_checkpointer(graph):
    assert graph.checkpointer is not None


def test_graph_has_human_input_interrupt(graph):
    graph_state = graph.get_graph()

    assert "human_input" in graph_state.nodes