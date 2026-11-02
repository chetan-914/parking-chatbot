
import csv
import json
from pathlib import Path
from statistics import mean

from app.retrieval import search_static


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATASET_PATH = (
    PROJECT_ROOT / "evaluation" / "datasets" / "retrieval_eval.jsonl"
)

REPORT_DIR = PROJECT_ROOT / "evaluation" / "report"

K_VALUES = [1, 3, 5]


def load_dataset():
    """Load retrieval evaluation questions from JSONL."""

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Evaluation dataset not found: {DATASET_PATH}"
        )

    records = []

    with DATASET_PATH.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            required_fields = {
                "id",
                "question",
                "relevant_chunk_ids",
            }

            missing = required_fields - record.keys()

            if missing:
                raise ValueError(
                    f"Line {line_number} is missing fields: {missing}"
                )

            records.append(record)

    if not records:
        raise ValueError("Evaluation dataset is empty.")

    return records


def recall_at_k(retrieved, relevant, k):
    """Calculate Recall@K."""

    if not relevant:
        return None

    relevant_found = set(retrieved[:k]) & set(relevant)

    return len(relevant_found) / len(relevant)


def precision_at_k(retrieved, relevant, k):
    """Calculate Precision@K."""

    relevant_found = set(retrieved[:k]) & set(relevant)

    return len(relevant_found) / k


def hit_rate_at_k(retrieved, relevant, k):
    """Calculate whether at least one relevant chunk was retrieved."""

    return float(bool(set(retrieved[:k]) & set(relevant)))


def reciprocal_rank(retrieved, relevant):
    """Calculate reciprocal rank of the first relevant result."""

    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1 / rank

    return 0.0


def evaluate_question(record, k_values, topic_filter):
    """Retrieve chunks and calculate metrics for one question."""

    question = record["question"]
    relevant = set(record["relevant_chunk_ids"])

    topic = record.get("topic") if topic_filter else None

    results = search_static(
        query=question,
        k=max(k_values),
    )

    retrieved = [
        result["chunk_index"]
        for result in results
    ]

    metrics = {}

    for k in k_values:
        metrics[f"recall@{k}"] = recall_at_k(
            retrieved, relevant, k
        )

        metrics[f"precision@{k}"] = precision_at_k(
            retrieved, relevant, k
        )

        metrics[f"hit_rate@{k}"] = hit_rate_at_k(
            retrieved, relevant, k
        )

    metrics["mrr"] = reciprocal_rank(
        retrieved, relevant
    )

    return {
        "id": record["id"],
        "question": question,
        "relevant_chunk_ids": sorted(relevant),
        "retrieved_chunk_ids": retrieved,
        "is_out_of_scope": not bool(relevant),
        **metrics,
    }


def average_metrics(results, k_values):
    """Calculate average metrics across applicable questions."""

    # Out-of-scope questions are excluded from retrieval metrics.
    in_scope = [
        result
        for result in results
        if not result["is_out_of_scope"]
    ]

    if not in_scope:
        return {}

    summary = {}

    for k in k_values:
        summary[f"recall@{k}"] = mean(
            result[f"recall@{k}"]
            for result in in_scope
        )

        summary[f"precision@{k}"] = mean(
            result[f"precision@{k}"]
            for result in in_scope
        )

        summary[f"hit_rate@{k}"] = mean(
            result[f"hit_rate@{k}"]
            for result in in_scope
        )

    summary["mrr"] = mean(
        result["mrr"]
        for result in in_scope
    )

    summary["total_questions"] = len(results)
    summary["in_scope_questions"] = len(in_scope)
    summary["out_of_scope_questions"] = (
        len(results) - len(in_scope)
    )

    return summary


def save_results(results, summary, experiment_name):
    """Save detailed results and aggregate metrics."""

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    details_path = REPORT_DIR / (
        f"retrieval_details_{experiment_name}.csv"
    )

    summary_path = REPORT_DIR / (
        f"retrieval_summary_{experiment_name}.json"
    )

    if results:
        with details_path.open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(results[0].keys()),
            )
            writer.writeheader()
            writer.writerows(results)

    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4)

    print(f"\nDetailed results: {details_path}")
    print(f"Summary metrics: {summary_path}")


def run_experiment(records, experiment_name, topic_filter):
    """Run one retrieval experiment."""

    print(f"\n{'=' * 60}")
    print(f"Experiment: {experiment_name}")
    print(f"Topic filter: {'ON' if topic_filter else 'OFF'}")
    print(f"{'=' * 60}")

    results = []

    for record in records:
        result = evaluate_question(
            record=record,
            k_values=K_VALUES,
            topic_filter=topic_filter,
        )

        results.append(result)

        print(
            f"{result['id']} | "
            f"Retrieved: {result['retrieved_chunk_ids']}"
        )

    summary = average_metrics(results, K_VALUES)

    print("\nEvaluation Summary")

    for metric, value in summary.items():
        if isinstance(value, float):
            print(f"{metric}: {value:.4f}")
        else:
            print(f"{metric}: {value}")

    save_results(
        results,
        summary,
        experiment_name,
    )


def main():
    """Run retrieval evaluation experiments."""

    records = load_dataset()

    print(f"Loaded {len(records)} evaluation questions.")

    # Experiment 1: Without topic filtering
    run_experiment(
        records=records,
        experiment_name="no_topic_filter",
        topic_filter=False,
    )

    # Experiment 2: With topic filtering
    # Records should contain a valid 'topic' field.
    records_with_topics = [
        record
        for record in records
        if record.get("topic")
    ]

    if records_with_topics:
        run_experiment(
            records=records_with_topics,
            experiment_name="with_topic_filter",
            topic_filter=True,
        )
    else:
        print(
            "\nSkipping topic-filter experiment: "
            "no questions contain a topic field."
        )


if __name__ == "__main__":
    main()
