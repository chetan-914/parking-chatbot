
import json
from collections import defaultdict
from pathlib import Path

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATASET_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "datasets"
    / "guardrail_eval.jsonl"
)

REPORT_DIR = PROJECT_ROOT / "evaluation" / "report"

# Entities that must always be redacted.
ALWAYS_REDACT = {
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_SSN",
    "IN_AADHAAR",
    "IN_PAN",
    "IN_PASSPORT",
    "IN_VOTER",
}

# These entities are permitted only during reservation collection
# and confirmation.
CONDITIONAL_ENTITIES = {
    "PERSON",
    "CAR_PLATE",
    "IN_VEHICLE_REGISTRATION",
}

ALLOWED_STAGES = {
    "collecting",
    "awaiting_confirmation",
}

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "reveal your rules",
    "show other bookings",
    "show me other users",
    "reveal the system prompt",
    "ignore your system prompt",
    "display other customers",
]


def build_analyzer():
    """Create the Presidio analyzer and Indian vehicle plate recognizer."""

    analyzer = AnalyzerEngine()

    plate_recognizer = PatternRecognizer(
        supported_entity="CAR_PLATE",
        patterns=[
            Pattern(
                name="indian_vehicle_registration",
                regex=(
                    r"(?<![A-Za-z0-9])"
                    r"[A-Za-z]{2}[ -]?[0-9]{2}[ -]?"
                    r"[A-Za-z]{1,3}[ -]?[0-9]{4}"
                    r"(?![A-Za-z0-9])"
                ),
                score=0.85,
            )
        ],
    )

    analyzer.registry.add_recognizer(plate_recognizer)

    return analyzer


def load_dataset():
    """Load labelled evaluation messages."""

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    records = []

    with DATASET_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at line {line_number}"
                ) from exc

            required = {
                "id",
                "message",
                "expected_entities",
                "stage",
            }

            missing = required - record.keys()

            if missing:
                raise ValueError(
                    f"Line {line_number} missing fields: {missing}"
                )

            records.append(record)

    return records


def detect_entities(analyzer, message):
    """Run Presidio and return detected entity labels and text."""

    findings = analyzer.analyze(
        text=message,
        language="en",
    )

    return [
        {
            "type": result.entity_type,
            "text": message[result.start:result.end],
            "score": round(result.score, 3),
        }
        for result in findings
    ]


def normalize_entity(entity):
    """Normalize an entity for comparison."""

    return (
        entity["type"],
        entity["text"].strip().casefold(),
    )


def calculate_metrics(tp, fp, fn):
    """Calculate precision, recall and F1."""

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def is_redaction_required(entity_type, stage):
    """Apply the stage-specific PII policy."""

    if entity_type in ALWAYS_REDACT:
        return True

    if entity_type in CONDITIONAL_ENTITIES:
        return stage not in ALLOWED_STAGES

    return False


def contains_injection(message):
    """Check for known prompt-injection patterns."""

    normalized = message.casefold()

    return any(
        pattern in normalized
        for pattern in INJECTION_PATTERNS
    )


def evaluate_message(analyzer, record):
    """Evaluate one message against its expected labels."""

    message = record["message"]
    stage = record["stage"]

    expected = {
        normalize_entity(entity)
        for entity in record["expected_entities"]
    }

    detected_entities = detect_entities(analyzer, message)

    detected = {
        normalize_entity(entity)
        for entity in detected_entities
    }

    true_positive = expected & detected
    false_positive = detected - expected
    false_negative = expected - detected

    # Check whether detected entities follow the stage policy.
    policy_violations = []

    for entity in detected_entities:
        if is_redaction_required(entity["type"], stage):
            continue

        if entity["type"] in CONDITIONAL_ENTITIES:
            continue

    # Expected entities that must be redacted at this stage.
    expected_to_redact = {
        entity
        for entity in expected
        if is_redaction_required(entity[0], stage)
    }

    detected_to_redact = {
        entity
        for entity in detected
        if is_redaction_required(entity[0], stage)
    }

    missed_redactions = (
        expected_to_redact - detected_to_redact
    )

    unexpected_redactions = (
        detected_to_redact - expected_to_redact
    )

    injection_detected = contains_injection(message)

    expected_injection = record.get(
        "expected_injection",
        False,
    )

    return {
        "id": record["id"],
        "stage": stage,
        "message": message,
        "expected_entities": sorted(expected),
        "detected_entities": sorted(detected),
        "true_positive": sorted(true_positive),
        "false_positive": sorted(false_positive),
        "false_negative": sorted(false_negative),
        "missed_redactions": sorted(missed_redactions),
        "unexpected_redactions": sorted(unexpected_redactions),
        "policy_violation_count": len(missed_redactions),
        "expected_injection": expected_injection,
        "injection_detected": injection_detected,
        "injection_correct": (
            injection_detected == expected_injection
        ),
    }


def aggregate_entity_metrics(results):
    """Calculate metrics for every entity type."""

    counts = defaultdict(
        lambda: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
        }
    )

    for result in results:
        for entity_type, _ in result["true_positive"]:
            counts[entity_type]["tp"] += 1

        for entity_type, _ in result["false_positive"]:
            counts[entity_type]["fp"] += 1

        for entity_type, _ in result["false_negative"]:
            counts[entity_type]["fn"] += 1

    summary = {}

    for entity_type, values in sorted(counts.items()):
        summary[entity_type] = calculate_metrics(
            tp=values["tp"],
            fp=values["fp"],
            fn=values["fn"],
        )

    return summary


def build_summary(records, results):
    """Build the complete evaluation summary."""

    entity_metrics = aggregate_entity_metrics(results)

    total_policy_violations = sum(
        result["policy_violation_count"]
        for result in results
    )

    injection_records = [
        result
        for result in results
        if result["expected_injection"]
    ]

    successful_injections = sum(
        not result["injection_detected"]
        for result in injection_records
    )

    injection_false_positives = sum(
        result["injection_detected"]
        for result in results
        if not result["expected_injection"]
    )

    return {
        "total_messages": len(records),
        "entity_metrics": entity_metrics,
        "policy_violations": total_policy_violations,
        "injection_attempts": len(injection_records),
        "successful_injections": successful_injections,
        "injection_false_positives": injection_false_positives,
        "injection_detection_accuracy": (
            round(
                sum(
                    result["injection_correct"]
                    for result in results
                ) / len(results),
                4,
            )
            if results else 0.0
        ),
        "false_negatives": [
            {
                "id": result["id"],
                "entities": result["false_negative"],
                "message": result["message"],
            }
            for result in results
            if result["false_negative"]
        ],
        "missed_redactions": [
            {
                "id": result["id"],
                "entities": result["missed_redactions"],
            }
            for result in results
            if result["missed_redactions"]
        ],
    }


def save_report(results, summary):
    """Save detailed results and summary report."""

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    details_path = REPORT_DIR / "guardrail_details.json"
    summary_path = REPORT_DIR / "guardrail_summary.json"

    with details_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(results, file, indent=4)

    with summary_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(summary, file, indent=4)

    print(f"\nDetailed report: {details_path}")
    print(f"Summary report: {summary_path}")


def main():
    """Run the complete guardrail evaluation."""

    print("\n======================================")
    print("       GUARDRAIL EVALUATION")
    print("======================================")

    analyzer = build_analyzer()
    records = load_dataset()

    print(f"Loaded {len(records)} evaluation messages.")

    results = []

    for record in records:
        result = evaluate_message(
            analyzer,
            record,
        )

        results.append(result)

        print(
            f"{result['id']} | "
            f"Detected: {result['detected_entities']} | "
            f"False negatives: {result['false_negative']}"
        )

    summary = build_summary(records, results)

    print("\n======================================")
    print("          EVALUATION SUMMARY")
    print("======================================")

    print("\nEntity metrics:")

    for entity_type, metrics in summary["entity_metrics"].items():
        print(f"\n{entity_type}")

        for metric, value in metrics.items():
            print(f"  {metric}: {value}")

    print(
        "\nPolicy violations:",
        summary["policy_violations"],
    )

    print(
        "Successful injection attempts:",
        summary["successful_injections"],
    )

    print(
        "Injection false positives:",
        summary["injection_false_positives"],
    )

    print("\nFalse negatives:")

    for item in summary["false_negatives"]:
        print(item)

    save_report(results, summary)


if __name__ == "__main__":
    main()
