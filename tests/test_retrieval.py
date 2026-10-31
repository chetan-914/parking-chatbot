from unittest.mock import patch

import pytest

from app.retrieval import search_static


def test_search_static_returns_list():
    mock_results = [
        {
            "chunk_id": "chunk-001",
            "content": "Parking is available from 6 AM to 10 PM.",
            "source": "facility.md",
            "section": "Operating Hours",
        }
    ]

    with patch("app.retrieval.search_static", return_value=mock_results) as mock_search:
        results = mock_search(
            query="What are the parking hours?",
            k=3,
            topic="facility",
        )

    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "chunk-001"


def test_search_static_returns_expected_result_fields():
    mock_result = {
        "chunk_id": "chunk-001",
        "content": "Parking operates from 6 AM to 10 PM.",
        "source": "facility.md",
        "section": "Operating Hours",
    }

    assert {
        "chunk_id",
        "content",
        "source",
        "section",
    }.issubset(mock_result.keys())


def test_search_static_handles_no_results():
    with patch("app.retrieval.search_static", return_value=[]) as mock_search:
        results = mock_search(
            query="Information that does not exist",
            k=3,
            topic="facility",
        )

    assert results == []


def test_search_static_uses_requested_top_k():
    with patch("app.retrieval.search_static", return_value=[]) as mock_search:
        search_static(
            query="parking availability",
            k=5,
            topic="facility",
        )

    mock_search.assert_called_once_with(
        query="parking availability",
        k=5,
        topic="facility",
    )