"""Domain entities and their DynamoDB (de)serialization.

All timestamps are ISO 8601 UTC, minute-level scheduling included: `due` is a
full datetime, so an item reviewed in a morning session can legitimately come
back in the afternoon once its FSRS learning step matures.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from yomu import keys

# Facets are an open enum: new values may appear later (kanji_reading, listening).
FACET_RECOGNITION = "recognition"
FACET_PRODUCTION = "production"
FACET_GRAMMAR = "grammar"

TYPE_VOCAB = "vocab"
TYPE_GRAMMAR = "grammar"

STATE_NEW = "new"
STATE_LEARNING = "learning"
STATE_REVIEW = "review"
STATE_RELEARNING = "relearning"

LEECH_LAPSES = 4  # lapses >= 4 → leech signal surfaced in queue payload

POS_VALUES = {
    "verb-ichidan",
    "verb-godan",
    "verb-irregular",
    "noun",
    "adj-i",
    "adj-na",
    "adverb",
    "particle",
    "pronoun",
    "counter",
    "conjunction",
    "interjection",
    "prenominal",
    "expression",
    "grammar",
}


def _num(value: Any) -> Any:
    """boto3 returns numbers as Decimal; expose floats/ints to the domain."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _strip_nones(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Concept:
    concept_id: str
    type: str
    lemma: str
    normalized: str
    meanings: list[str]
    pos: str
    reading: str | None = None
    level: str = "none"
    examples: list[dict[str, str]] = field(default_factory=list)
    source: str = "claude"
    priority: int = 0
    created_at: str = ""

    MAX_EXAMPLES = 5

    def to_dynamo(self, pk: str) -> dict[str, Any]:
        return _strip_nones(
            {
                "PK": pk,
                "SK": keys.concept_sk(self.concept_id),
                "entity": "concept",
                "concept_id": self.concept_id,
                "type": self.type,
                "lemma": self.lemma,
                "normalized": self.normalized,
                "reading": self.reading,
                "meanings": self.meanings,
                "pos": self.pos,
                "level": self.level,
                "examples": self.examples,
                "source": self.source,
                "priority": self.priority,
                "created_at": self.created_at,
            }
        )

    @classmethod
    def from_dynamo(cls, record: dict[str, Any]) -> "Concept":
        return cls(
            concept_id=record["concept_id"],
            type=record["type"],
            lemma=record["lemma"],
            normalized=record["normalized"],
            reading=record.get("reading"),
            meanings=list(record.get("meanings", [])),
            pos=record["pos"],
            level=record.get("level", "none"),
            examples=[dict(e) for e in record.get("examples", [])],
            source=record.get("source", "claude"),
            priority=_num(record.get("priority", 0)),
            created_at=record.get("created_at", ""),
        )

    def display(self) -> dict[str, Any]:
        """The concept payload embedded in queue responses."""
        return _strip_nones(
            {
                "type": self.type,
                "lemma": self.lemma,
                "reading": self.reading,
                "meanings": self.meanings,
                "pos": self.pos,
                "examples": self.examples,
            }
        )


@dataclass
class Item:
    concept_id: str
    facet: str
    state: str = STATE_NEW
    step: int | None = None  # py-fsrs learning-step index; internal, never exposed
    stability: float | None = None
    difficulty: float | None = None
    due: str | None = None  # ISO datetime; unset while state == new
    last_review: str | None = None  # ISO datetime (FSRS elapsed-time input)
    first_review: str | None = None  # ISO datetime, set once; drives the daily drip count
    reps: int = 0
    lapses: int = 0
    priority: int = 0  # drives NEW# queue position; inert once introduced

    @property
    def item_id(self) -> str:
        return keys.item_id(self.concept_id, self.facet)

    @property
    def is_leech(self) -> bool:
        return self.lapses >= LEECH_LAPSES

    def queue_key(self) -> str:
        if self.state == STATE_NEW:
            return keys.queue_key_new(self.priority, self.concept_id)
        assert self.due is not None, "scheduled item must have a due datetime"
        return keys.queue_key_due(self.due)

    def to_dynamo(self, pk: str) -> dict[str, Any]:
        return _strip_nones(
            {
                "PK": pk,
                "SK": keys.item_sk(self.concept_id, self.facet),
                "entity": "item",
                "facet": self.facet,
                "state": self.state,
                "step": self.step,
                "stability": _dec(self.stability),
                "difficulty": _dec(self.difficulty),
                "due": self.due,
                "last_review": self.last_review,
                "first_review": self.first_review,
                "reps": self.reps,
                "lapses": self.lapses,
                "priority": self.priority,
                "queue_key": self.queue_key(),
            }
        )

    @classmethod
    def from_dynamo(cls, record: dict[str, Any]) -> "Item":
        # SK = ITEM#<concept_id>#<facet>
        _, cid, facet = record["SK"].split("#", 2)
        return cls(
            concept_id=cid,
            facet=facet,
            state=record.get("state", STATE_NEW),
            step=_num(record.get("step")),
            stability=_num(record.get("stability")),
            difficulty=_num(record.get("difficulty")),
            due=record.get("due"),
            last_review=record.get("last_review"),
            first_review=record.get("first_review"),
            reps=_num(record.get("reps", 0)),
            lapses=_num(record.get("lapses", 0)),
            priority=_num(record.get("priority", 0)),
        )


@dataclass
class ReviewLog:
    concept_id: str
    facet: str
    reviewed_at: str  # ISO datetime, also part of the SK
    grade: int
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    context: dict[str, str] = field(default_factory=dict)
    duplicate: bool = False

    CONTEXT_FIELDS = ("exercise_type", "sentence", "user_answer", "note")
    CONTEXT_MAX_CHARS = 300

    def to_dynamo(self, pk: str) -> dict[str, Any]:
        return {
            "PK": pk,
            "SK": keys.log_sk(self.concept_id, self.facet, self.reviewed_at),
            "entity": "log",
            "facet": self.facet,
            "reviewed_at": self.reviewed_at,
            "grade": self.grade,
            "state_before": {k: _dec(v) for k, v in self.state_before.items()},
            "state_after": {
                k: (_dec(v) if isinstance(v, float) else v) for k, v in self.state_after.items()
            },
            "context": self.context,
            "duplicate": self.duplicate,
        }

    @classmethod
    def from_dynamo(cls, record: dict[str, Any]) -> "ReviewLog":
        # SK = LOG#<concept_id>#<facet>#<iso_timestamp>
        _, cid, facet, reviewed_at = record["SK"].split("#", 3)
        return cls(
            concept_id=cid,
            facet=facet,
            reviewed_at=reviewed_at,
            grade=_num(record["grade"]),
            state_before={k: _num(v) for k, v in record.get("state_before", {}).items()},
            state_after={k: _num(v) for k, v in record.get("state_after", {}).items()},
            context=dict(record.get("context", {})),
            duplicate=bool(record.get("duplicate", False)),
        )


@dataclass
class Profile:
    desired_retention: float = 0.90
    new_per_day: int = 5
    ui_lang: str = "fr"
    # Streak bookkeeping, maintained on record_result (replayable from logs).
    streak_days: int = 0
    last_active_date: str | None = None

    def to_dynamo(self, pk: str) -> dict[str, Any]:
        return _strip_nones(
            {
                "PK": pk,
                "SK": keys.PROFILE_SK,
                "entity": "profile",
                "desired_retention": _dec(self.desired_retention),
                "new_per_day": self.new_per_day,
                "ui_lang": self.ui_lang,
                "streak_days": self.streak_days,
                "last_active_date": self.last_active_date,
            }
        )

    @classmethod
    def from_dynamo(cls, record: dict[str, Any] | None) -> "Profile":
        if record is None:
            return cls()
        return cls(
            desired_retention=_num(record.get("desired_retention", 0.90)),
            new_per_day=_num(record.get("new_per_day", 5)),
            ui_lang=record.get("ui_lang", "fr"),
            streak_days=_num(record.get("streak_days", 0)),
            last_active_date=record.get("last_active_date"),
        )
