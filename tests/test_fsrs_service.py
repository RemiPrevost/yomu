from datetime import UTC, datetime, timedelta

from yomu.fsrs_service import apply_review, is_premature
from yomu.models import (
    FACET_RECOGNITION,
    STATE_LEARNING,
    STATE_NEW,
    STATE_RELEARNING,
    STATE_REVIEW,
    Item,
)

NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
RETENTION = 0.9


def new_item() -> Item:
    return Item(concept_id="abc123def456", facet=FACET_RECOGNITION, priority=3)


def test_first_review_enters_learning_with_minute_step():
    item = new_item()
    outcome = apply_review(item, 3, RETENTION, NOW)

    assert item.state == STATE_LEARNING
    assert item.reps == 1
    assert item.lapses == 0
    assert item.stability is not None and item.difficulty is not None
    # First Good lands on the 10-minute learning step.
    assert item.due == (NOW + timedelta(minutes=10)).isoformat()
    assert item.last_review == NOW.isoformat()
    assert item.first_review == NOW.isoformat()
    assert outcome.state_before == {"stability": None, "difficulty": None}
    assert outcome.state_after["due"] == item.due


def test_first_review_stamp_is_write_once():
    item = new_item()
    apply_review(item, 3, RETENTION, NOW)
    apply_review(item, 3, RETENTION, NOW + timedelta(minutes=15))
    assert item.first_review == NOW.isoformat()


def test_queue_key_flips_from_new_to_due_on_first_review():
    item = new_item()
    assert item.queue_key() == "NEW#00003#abc123def456"
    apply_review(item, 3, RETENTION, NOW)
    assert item.queue_key() == f"DUE#{item.due}"


def test_same_day_second_good_graduates_to_review_state():
    item = new_item()
    apply_review(item, 3, RETENTION, NOW)
    apply_review(item, 3, RETENTION, NOW + timedelta(minutes=12))

    assert item.state == STATE_REVIEW
    assert item.reps == 2
    # Interval is now on the scale of days, not minutes.
    assert datetime.fromisoformat(item.due) > NOW + timedelta(days=1)


def test_again_on_review_item_lapses_and_relearns():
    item = new_item()
    apply_review(item, 3, RETENTION, NOW)
    apply_review(item, 3, RETENTION, NOW + timedelta(minutes=12))
    assert item.state == STATE_REVIEW

    apply_review(item, 1, RETENTION, NOW + timedelta(days=10))
    assert item.state == STATE_RELEARNING
    assert item.lapses == 1


def test_again_while_learning_is_not_a_lapse():
    item = new_item()
    apply_review(item, 1, RETENTION, NOW)
    assert item.state == STATE_LEARNING
    assert item.lapses == 0


def test_scheduling_is_deterministic():
    due_datetimes = set()
    for _ in range(5):
        item = new_item()
        apply_review(item, 3, RETENTION, NOW)
        apply_review(item, 3, RETENTION, NOW + timedelta(days=1))
        apply_review(item, 4, RETENTION, NOW + timedelta(days=5))
        due_datetimes.add(item.due)
    assert len(due_datetimes) == 1  # fuzzing disabled → replayable


def test_premature_before_due_not_after():
    item = new_item()
    assert not is_premature(item, NOW)  # new items are never premature

    apply_review(item, 3, RETENTION, NOW)  # due at +10 minutes
    assert is_premature(item, NOW + timedelta(seconds=30))  # LLM retry
    assert is_premature(item, NOW + timedelta(minutes=9))
    assert not is_premature(item, NOW + timedelta(minutes=10))
    assert not is_premature(item, NOW + timedelta(hours=5))  # afternoon session


def test_new_item_state_constant_is_ours():
    assert new_item().state == STATE_NEW
