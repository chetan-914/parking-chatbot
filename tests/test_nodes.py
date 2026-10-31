from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app import nodes


def test_init_creates_initial_conversation_state():
    result = nodes.init({})

    assert isinstance(result, dict)
    assert result["stage"] == "greeting"
    assert result["turn_count"] == 0
    assert result["ended"] is False
    assert result["messages"]


def test_human_input_adds_user_message():
    state = {
        "messages": [],
        "stage": "collecting",
        "turn_count": 0,
    }

    with patch.object(nodes, "input", return_value="I need parking tomorrow"):
        result = nodes.human_input(state)

    assert isinstance(result, dict)
    assert result["messages"]
    assert isinstance(result["messages"][-1], HumanMessage)
    assert result["messages"][-1].content == "I need parking tomorrow"


def test_farewell_marks_conversation_as_ended():
    state = {
        "messages": [],
        "ended": False,
        "end_reason": None,
    }

    result = nodes.farewell(state)

    assert result["ended"] is True
    assert result["end_reason"]


def test_pii_check_input_masks_sensitive_information():
    state = {
        "messages": [
            HumanMessage(
                content="My name is John Smith and my car number is TS09AB1234"
            )
        ],
        "stage": "collecting",
    }

    with patch.object(
        nodes,
        "mask_text",
        return_value=(
            "My name is <PERSON_1> and my car number is <PLATE_1>",
            {"<PERSON_1>": "John Smith", "<PLATE_1>": "TS09AB1234"},
        ),
    ):
        result = nodes.pii_check_input(state)

    assert isinstance(result, dict)
    assert result["messages"][-1].content != state["messages"][-1].content
    assert "John Smith" not in result["messages"][-1].content
    assert "TS09AB1234" not in result["messages"][-1].content


def test_pii_check_output_restores_local_response():
    state = {
        "messages": [
            AIMessage(content="Hello <PERSON_1>, your vehicle is <PLATE_1>.")
        ],
        "pii_replacements": {
            "<PERSON_1>": "John Smith",
            "<PLATE_1>": "TS09AB1234",
        },
    }

    with patch.object(
        nodes,
        "restore_text",
        return_value="Hello John Smith, your vehicle is TS09AB1234.",
    ):
        result = nodes.pii_check_output(state)

    assert isinstance(result, dict)
    assert result["messages"][-1].content == (
        "Hello John Smith, your vehicle is TS09AB1234."
    )


def test_save_transcript_does_not_expose_raw_pii():
    state = {
        "conversation_id": "test-conversation",
        "messages": [
            HumanMessage(content="My car number is <PLATE_1>"),
            AIMessage(content="I can help with your parking reservation."),
        ],
        "stage": "collecting",
        "pii_replacements": {
            "<PLATE_1>": "TS09AB1234",
        },
    }

    with patch.object(nodes, "save_conversation_transcript") as mock_save:
        nodes.save_transcript(state)

    if mock_save.called:
        saved_data = str(mock_save.call_args)
        assert "TS09AB1234" not in saved_data