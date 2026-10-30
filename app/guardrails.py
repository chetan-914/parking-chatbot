import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer import RecognizerResult


@dataclass
class MaskedText:
    """Text with PII replaced by placeholders and a local restoration map."""

    text: str
    replacements: dict[str, str] = field(default_factory=dict)


# Indian registration numbers, including Bharat series.
CAR_NUMBER_PATTERN = (
    r"\b(?:"
    r"[A-Z]{2}[\s-]?[0-9]{2}[\s-]?[A-Z]{1,3}[\s-]?[0-9]{4}"
    r"|"
    r"[0-9]{2}[\s-]?BH[\s-]?[0-9]{4}[\s-]?[A-Z]{1,2}"
    r")\b"
)


@lru_cache(maxsize=1)
def get_analyzer() -> AnalyzerEngine:
    """
    Build and cache the Presidio analyzer.

    The spaCy language model must be installed separately.
    """
    analyzer = AnalyzerEngine()

    car_number_recognizer = PatternRecognizer(
        supported_entity="CAR_NUMBER",
        patterns=[
            Pattern(
                name="indian_vehicle_registration",
                regex=CAR_NUMBER_PATTERN,
                score=0.95,
            )
        ],
        context=["car", "vehicle", "registration", "number", "plate"],
    )

    analyzer.registry.add_recognizer(car_number_recognizer)

    return analyzer


def _find_known_values(
    text: str,
    known_values: Iterable[tuple[str, str]],
) -> list[RecognizerResult]:
    """
    Find explicitly known sensitive values.

    This is useful when a name or car number was already extracted
    from a previous conversation turn.
    """
    results = []

    for value, entity_type in known_values:
        if not value or not value.strip():
            continue

        pattern = re.compile(re.escape(value.strip()), re.IGNORECASE)

        for match in pattern.finditer(text):
            results.append(
                RecognizerResult(
                    entity_type=entity_type,
                    start=match.start(),
                    end=match.end(),
                    score=1.0,
                )
            )

    return results


def _select_non_overlapping(
    results: list[RecognizerResult],
) -> list[RecognizerResult]:
    """
    Select non-overlapping detection results.

    Prefer higher-confidence results, then longer matches.
    """
    ordered = sorted(
        results,
        key=lambda item: (
            -item.score,
            -(item.end - item.start),
            item.start,
        ),
    )

    selected = []

    for candidate in ordered:
        overlaps = any(
            candidate.start < existing.end
            and candidate.end > existing.start
            for existing in selected
        )

        if not overlaps:
            selected.append(candidate)

    return sorted(selected, key=lambda item: item.start)


def mask_text(
    text: str,
    known_names: Iterable[str] | None = None,
    known_car_numbers: Iterable[str] | None = None,
) -> MaskedText:
    """
    Detect and mask PII in text.

    Supported detections include:
    - Person names
    - Phone numbers
    - Email addresses
    - Credit card numbers
    - Indian vehicle registration numbers
    - Explicitly supplied names and car numbers

    The original values remain only in the returned local replacement map.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if not text:
        return MaskedText(text="")

    analyzer = get_analyzer()

    detected = analyzer.analyze(
        text=text,
        language="en",
        entities=[
            "PERSON",
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "CREDIT_CARD",
            "CAR_NUMBER",
        ],
    )

    known_values = [
        (name, "PERSON")
        for name in (known_names or [])
    ]

    known_values.extend(
        (number, "CAR_NUMBER")
        for number in (known_car_numbers or [])
    )

    detected.extend(_find_known_values(text, known_values))

    selected = _select_non_overlapping(detected)

    replacements: dict[str, str] = {}
    masked_text = text
    entity_counts: dict[str, int] = {}

    # Replace from right to left so earlier character positions remain valid.
    for result in reversed(selected):
        original_value = text[result.start:result.end]

        entity_type = result.entity_type
        entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

        placeholder = (
            f"PII_{entity_type}_{entity_counts[entity_type]}"
        )

        replacements[placeholder] = original_value

        masked_text = (
            masked_text[:result.start]
            + placeholder
            + masked_text[result.end:]
        )

    return MaskedText(
        text=masked_text,
        replacements=replacements,
    )


def restore_text(
    text: str,
    replacements: dict[str, str],
) -> str:
    """
    Restore original values in locally generated text.

    Call this only after the LLM response has returned.
    """
    if not text or not replacements:
        return text

    restored = text

    for placeholder, original_value in replacements.items():
        restored = restored.replace(placeholder, original_value)

    return restored


def merge_replacements(
    *replacement_maps: dict[str, str],
) -> dict[str, str]:
    """
    Combine replacement maps from multiple conversation fields.

    Raises an error if a placeholder collision maps to different values.
    """
    merged: dict[str, str] = {}

    for replacement_map in replacement_maps:
        for placeholder, original_value in replacement_map.items():
            if (
                placeholder in merged
                and merged[placeholder] != original_value
            ):
                raise ValueError(
                    f"Conflicting PII placeholder: {placeholder}"
                )

            merged[placeholder] = original_value

    return merged


def mask_customer_details(
    text: str,
    first_name: str | None = None,
    last_name: str | None = None,
    car_number: str | None = None,
) -> MaskedText:
    """
    Convenience wrapper for masking known reservation details.
    """
    known_names = [
        value
        for value in (first_name, last_name)
        if value
    ]

    known_car_numbers = (
        [car_number] if car_number else []
    )

    return mask_text(
        text=text,
        known_names=known_names,
        known_car_numbers=known_car_numbers,
    )