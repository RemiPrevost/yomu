"""Rule-based, server-composed guidance strings for the review queue.

Plain heuristics over the queue payload — no LLM involved. The client LLM
reads these hints and adapts the lesson accordingly.
"""

from typing import Any

HEAVY_BACKLOG_THRESHOLD = 30
FAILURE_CLUSTER_THRESHOLD = 3


def compose_guidance(
    due_entries: list[dict[str, Any]],
    total_review: int,
    new_served: int,
    drip_exhausted: bool,
) -> str:
    hints: list[str] = []

    leech_lemmas = [
        e["concept"]["lemma"] for e in due_entries if e["memory"]["is_leech"]
    ]
    if leech_lemmas:
        shown = ", ".join(leech_lemmas[:3])
        hints.append(
            f"Leech alert ({shown}): these items keep lapsing — try mnemonic work, "
            "contrastive examples, or a different exercise angle instead of plain recall."
        )

    if total_review > HEAVY_BACKLOG_THRESHOLD and new_served > 0:
        hints.append(
            f"Heavy review backlog ({total_review} due): consider clearing reviews "
            "before introducing the new items."
        )

    failure_counts: dict[str, int] = {}
    for entry in due_entries:
        for exercise_type in entry["memory"]["recent_failures_context"]:
            failure_counts[exercise_type] = failure_counts.get(exercise_type, 0) + 1
    clustered = [
        t for t, n in failure_counts.items() if n >= FAILURE_CLUSTER_THRESHOLD
    ]
    if clustered:
        hints.append(
            f"Recent failures cluster in {', '.join(sorted(clustered))} exercises — "
            "vary the format and re-test those items with easier scaffolding first."
        )

    if drip_exhausted and new_served == 0:
        hints.append(
            "Daily new-item budget is used up — this is a review-only session."
        )

    return " ".join(hints)
