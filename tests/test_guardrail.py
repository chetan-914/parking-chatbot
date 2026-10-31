import pytest

from app.guardrails import mask_text, restore_text


@pytest.mark.parametrize(
    "pii_value",
    [
        "John Smith",
        "TS09AB1234",
        "john.smith@example.com",
        "+91 9876543210",
    ],
)
def test_pii_is_masked_and_restored(pii_value):
    original_text = f"Customer details: {pii_value}"

    masked_text, replacements = mask_text(original_text)

    assert isinstance(masked_text, str)
    assert isinstance(replacements, dict)

    # Sensitive information must not remain in the masked text.
    assert pii_value not in masked_text

    # Original information must be recoverable locally.
    restored_text = restore_text(masked_text, replacements)

    assert restored_text == original_text


def test_multiple_pii_entities_are_masked():
    original_text = (
        "My name is John Smith. "
        "My vehicle number is TS09AB1234. "
        "Email: john.smith@example.com. "
        "Phone: +91 9876543210."
    )

    masked_text, replacements = mask_text(original_text)

    assert "John Smith" not in masked_text
    assert "TS09AB1234" not in masked_text
    assert "john.smith@example.com" not in masked_text
    assert "+91 9876543210" not in masked_text

    restored_text = restore_text(masked_text, replacements)

    assert restored_text == original_text


def test_mask_text_with_no_pii():
    original_text = "I want to check parking availability tomorrow."

    masked_text, replacements = mask_text(original_text)

    assert masked_text == original_text
    assert isinstance(replacements, dict)


def test_empty_text():
    masked_text, replacements = mask_text("")

    assert masked_text == ""
    assert isinstance(replacements, dict)


def test_restore_text_with_empty_replacements():
    original_text = "Parking is available."

    restored_text = restore_text(original_text, {})

    assert restored_text == original_text