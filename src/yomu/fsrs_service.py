"""FSRS scheduling, wrapped around py-fsrs.

The server is the only writer of stability/difficulty/due; this module is the
only place that touches py-fsrs. Fuzzing is disabled so that replaying the
review logs (parameter refits, audits) reproduces the exact same state.
"""

from dataclasses import dataclass
from datetime import datetime

from fsrs import Card, Rating, Scheduler, State

from yomu.models import (
    STATE_LEARNING,
    STATE_NEW,
    STATE_RELEARNING,
    STATE_REVIEW,
    Item,
)

_STATE_FROM_FSRS = {
    State.Learning: STATE_LEARNING,
    State.Review: STATE_REVIEW,
    State.Relearning: STATE_RELEARNING,
}
_STATE_TO_FSRS = {v: k for k, v in _STATE_FROM_FSRS.items()}

_schedulers: dict[float, Scheduler] = {}


def _scheduler(desired_retention: float) -> Scheduler:
    if desired_retention not in _schedulers:
        _schedulers[desired_retention] = Scheduler(
            desired_retention=desired_retention, enable_fuzzing=False
        )
    return _schedulers[desired_retention]


def _card_id(item: Item) -> int:
    # py-fsrs wants an int id; derive a stable one so replays are deterministic.
    return int.from_bytes(f"{item.item_id}".encode(), "big") % (2**53)


def _to_card(item: Item, now: datetime) -> Card:
    if item.state == STATE_NEW:
        return Card(card_id=_card_id(item), due=now)
    assert item.last_review is not None and item.due is not None
    return Card(
        card_id=_card_id(item),
        state=_STATE_TO_FSRS[item.state],
        step=item.step,
        stability=item.stability,
        difficulty=item.difficulty,
        due=datetime.fromisoformat(item.due),
        last_review=datetime.fromisoformat(item.last_review),
    )


def is_premature(item: Item, now: datetime) -> bool:
    """A grade recorded before the item is due again must not drive FSRS.

    The queue never serves an item before its due datetime, so a premature
    grade is either an LLM retry of an already-recorded exercise or the LLM
    re-testing on its own initiative — the server owns scheduling, so both
    are logged but do not reschedule. New items (no due yet) are never
    premature. This also makes loops impossible: every FSRS-driving review
    pushes `due` into the future.
    """
    if item.state == STATE_NEW or item.due is None:
        return False
    return now < datetime.fromisoformat(item.due)


@dataclass
class ReviewOutcome:
    item: Item  # updated in place and returned for clarity
    state_before: dict
    state_after: dict


def apply_review(
    item: Item, grade: int, desired_retention: float, now: datetime
) -> ReviewOutcome:
    """Run one FSRS review and update the item's memory state.

    Caller is responsible for the premature check (`is_premature`) — a
    premature grade is logged but must never reach this function.
    """
    state_before = {"stability": item.stability, "difficulty": item.difficulty}

    was_review = item.state == STATE_REVIEW
    card, _ = _scheduler(desired_retention).review_card(
        _to_card(item, now), Rating(grade), review_datetime=now
    )

    item.state = _STATE_FROM_FSRS[card.state]
    item.step = card.step
    item.stability = card.stability
    item.difficulty = card.difficulty
    item.due = card.due.isoformat()
    item.last_review = now.isoformat()
    if item.first_review is None:
        item.first_review = now.isoformat()
    item.reps += 1
    if grade == Rating.Again and was_review:
        item.lapses += 1

    state_after = {
        "stability": item.stability,
        "difficulty": item.difficulty,
        "due": item.due,
    }
    return ReviewOutcome(item=item, state_before=state_before, state_after=state_after)
