
import csv
import json
import time
import uuid

from pathlib import Path
from statistics import mean

from langchain_core.messages import HumanMessage

from app.graph import graph


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "evaluation" / "report"

WARMUP_RUNS = 3

# Information questions for the initial latency benchmark.
# Add more questions as the knowledge base grows.
TEST_QUESTIONS = [
    "How do I reserve a parking space?",
    "What information is required for a reservation?",
    "Can I cancel my reservation?",
    "Where is the parking facility located?",
    "What facilities are available?",
    "Do you provide electric vehicle charging?",
    "Are accessible parking spaces available?",
    "What are the vehicle rules?",
    "How can I contact support?",
    "What payment methods are accepted?",
    "What are the parking hours?",
    "What is the price per hour?",
    "Is parking available today?",
    "How many spaces are currently free?",
    "Can I book a space for tomorrow?",
    "What is the maximum booking duration?",
    "Can I book for two hours?",
    "Can I reserve a space in advance?",
    "What happens if all spaces are occupied?",
    "How does the booking confirmation work?",
]


def percentile(values, percent):
    """Calculate a percentile using linear interpolation."""

    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percent / 100

    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)

    fraction = position - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def create_conversation():
    """Create a fresh conversation and initialize the graph."""

    thread_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    graph.invoke(
        {
            "conversation_id": conversation_id,
        },
        config=config,
    )

    return config


def execute_turn(config, question):
    """Send one user message and measure end-to-end execution time."""

    graph.update_state(
        config,
        {
            "messages": [
                HumanMessage(content=question)
            ]
        },
        as_node="human_input",
    )

    start_time = time.perf_counter()

    # Resume graph execution until the next input interrupt.
    for _ in graph.stream(
        None,
        config=config,
        stream_mode="values",
    ):
        pass

    elapsed = time.perf_counter() - start_time

    return elapsed


def summarize_latency(latencies):
    """Calculate latency statistics in milliseconds."""

    if not latencies:
        return {}

    values_ms = [
        value * 1000
        for value in latencies
    ]

    return {
        "count": len(values_ms),
        "mean_ms": round(mean(values_ms), 2),
        "p50_ms": round(percentile(values_ms, 50), 2),
        "p95_ms": round(percentile(values_ms, 95), 2),
        "max_ms": round(max(values_ms), 2),
    }


def save_results(results, summary):
    """Save latency details and summary."""

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = REPORT_DIR / "latency_details.csv"
    json_path = REPORT_DIR / "latency_summary.json"

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "question_id",
                "question",
                "latency_ms",
                "is_warmup",
            ],
        )

        writer.writeheader()
        writer.writerows(results)

    with json_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(summary, file, indent=4)

    print(f"\nDetailed results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")


def run_latency_evaluation():
    """Run the latency benchmark."""

    print("\n======================================")
    print("       CHATBOT LATENCY EVALUATION")
    print("======================================")

    config = create_conversation()

    results = []
    measured_latencies = []

    total_runs = WARMUP_RUNS + len(TEST_QUESTIONS)

    for index in range(total_runs):
        is_warmup = index < WARMUP_RUNS

        # Reuse the test questions for warm-up runs.
        question = TEST_QUESTIONS[index % len(TEST_QUESTIONS)]

        print(
            f"\nRunning {index + 1}/{total_runs}: "
            f"{question}"
        )

        try:
            elapsed = execute_turn(config, question)

            latency_ms = round(elapsed * 1000, 2)

            results.append({
                "question_id": index + 1,
                "question": question,
                "latency_ms": latency_ms,
                "is_warmup": is_warmup,
            })

            if not is_warmup:
                measured_latencies.append(elapsed)

            label = "WARM-UP" if is_warmup else "MEASURED"

            print(
                f"Latency: {latency_ms:.2f} ms "
                f"({label})"
            )

        except Exception as exc:
            print(f"Error during question {index + 1}: {exc}")

    summary = summarize_latency(measured_latencies)

    print("\n======================================")
    print("           LATENCY SUMMARY")
    print("======================================")

    if summary:
        for metric, value in summary.items():
            print(f"{metric}: {value}")
    else:
        print("No successful measurements were recorded.")

    save_results(results, summary)


if __name__ == "__main__":
    run_latency_evaluation()
