"""Application logic behind the four MCP tools.

The server owns all scheduling decisions; the LLM client only generates
exercises and reports grades. Everything here is deterministic given `now`,
which is injectable for tests.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from yomu import fsrs_service, keys
from yomu.guidance import compose_guidance
from yomu.ids import concept_id as make_concept_id
from yomu.ids import normalize
from yomu.models import (
    FACET_GRAMMAR,
    FACET_PRODUCTION,
    FACET_RECOGNITION,
    POS_VALUES,
    STATE_NEW,
    TYPE_GRAMMAR,
    TYPE_VOCAB,
    Concept,
    Item,
    ReviewLog,
)
from yomu.repository import Repository

MAX_DUE_CEILING = 50
DEFAULT_MAX_DUE = 20
POS_GRAMMAR = "grammar"  # default pos for grammar-point concepts
# JLPT (Japanese) and CEFR (European languages) proficiency bands.
LEVELS = {"N5", "N4", "N3", "N2", "N1", "A1", "A2", "B1", "B2", "C1", "C2", "none"}
SUCCESS_GRADE = 2  # grade >= 2 means the item was recalled (Hard is still a success)
EXAMPLE_FIELD_MAX_CHARS = 500


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LanguageMemoryService:
    def __init__(self, repo: Repository, user_id: str):
        self._repo = repo
        self._user = user_id

    # ---- get_review_queue ----

    def get_review_queue(
        self,
        lang: str,
        max_due: int | None = None,
        max_new: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or _utcnow()
        today = now.date().isoformat()
        profile = self._repo.get_profile(self._user, lang)

        due_limit = min(max_due if max_due is not None else DEFAULT_MAX_DUE, MAX_DUE_CEILING)
        introduced_today = self._repo.count_introduced_today(self._user, lang, today)
        remaining_drip = max(0, profile.new_per_day - introduced_today)
        new_limit = min(max_new, remaining_drip) if max_new is not None else remaining_drip

        due_items = self._repo.query_due_items(
            self._user, lang, now.isoformat(), max(due_limit, 0)
        )
        new_items = (
            self._repo.query_new_items(self._user, lang, new_limit) if new_limit > 0 else []
        )

        concepts = self._repo.batch_get_concepts(
            self._user, lang, [i.concept_id for i in due_items + new_items]
        )

        due_entries = []
        for item in due_items:
            concept = concepts.get(item.concept_id)
            if concept is None:  # orphaned item; never fail the queue over it
                continue
            due_entries.append(
                {
                    "item_id": item.item_id,
                    "facet": item.facet,
                    "concept": concept.display(),
                    "memory": self._memory_signals(lang, item, now),
                }
            )

        new_entries = [
            {
                "item_id": item.item_id,
                "facet": item.facet,
                "concept": concepts[item.concept_id].display(),
            }
            for item in new_items
            if item.concept_id in concepts
        ]

        total_review = self._repo.count_due(self._user, lang, now.isoformat())
        stats = {
            "total_review": total_review,
            "total_backlog": self._repo.count_backlog(self._user, lang),
            "streak_days": profile.streak_days,
            # Read-only settings + today's drip usage, so the tutor can explain
            # state to the user (e.g. "tu es à 10 nouveaux mots/jour, il t'en
            # reste 3"). These are NOT writable via MCP by design — the server
            # owns scheduling; changing them is an admin action.
            "settings": {
                "new_per_day": profile.new_per_day,
                "desired_retention": profile.desired_retention,
                "ui_lang": profile.ui_lang,
            },
            "new_introduced_today": introduced_today,
            "new_remaining_today": remaining_drip,
        }

        return {
            "session_date": today,
            "due": due_entries,
            "new": new_entries,
            "stats": stats,
            "guidance": compose_guidance(
                due_entries,
                total_review=total_review,
                new_served=len(new_entries),
                drip_exhausted=remaining_drip == 0,
            ),
        }

    def _memory_signals(self, lang: str, item: Item, now: datetime) -> dict[str, Any]:
        """Derived signals only — raw stability/difficulty never reach the LLM."""
        recent_logs = self._repo.query_item_logs(
            self._user, lang, item.concept_id, item.facet, limit=10
        )
        failed_types = {
            log.context["exercise_type"]
            for log in recent_logs
            if log.grade == 1 and log.context.get("exercise_type")
        }
        days_overdue = 0
        if item.due:
            days_overdue = max(0, (now - datetime.fromisoformat(item.due)).days)
        return {
            "days_overdue": days_overdue,
            "reps": item.reps,
            "lapses": item.lapses,
            "last_grade": recent_logs[0].grade if recent_logs else None,
            "is_leech": item.is_leech,
            "recent_failures_context": sorted(failed_types),
        }

    # ---- record_result ----

    def record_result(
        self, lang: str, results: list[dict[str, Any]], now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or _utcnow()
        today = now.date().isoformat()
        profile = self._repo.get_profile(self._user, lang)

        recorded: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for index, result in enumerate(results):
            # Distinct timestamp per batch entry (two grades for the same item
            # in one call must not collide on the LOG# sort key). Used as the
            # review time everywhere so item and log timestamps match exactly.
            reviewed_at = now + timedelta(microseconds=index)
            outcome = self._record_one(lang, result, profile, reviewed_at)
            (recorded if "next_due" in outcome else rejected).append(outcome)

        if recorded:
            self._bump_streak(lang, profile, today)

        return {
            "recorded": recorded,
            "rejected": rejected,
            "session_summary": {
                "reviewed_today": self._repo.count_reviewed_today(self._user, lang, today),
                "remaining_due": self._repo.count_due(self._user, lang, now.isoformat()),
                "new_introduced_today": self._repo.count_introduced_today(
                    self._user, lang, today
                ),
            },
        }

    def _record_one(
        self,
        lang: str,
        result: dict[str, Any],
        profile: Any,
        reviewed_at: datetime,
    ) -> dict[str, Any]:
        raw_id = result.get("item_id", "")
        try:
            cid, facet = keys.parse_item_id(str(raw_id))
        except ValueError:
            return {
                "item_id": str(raw_id),
                "reason": "malformed item_id (expected <concept_id>#<facet>)",
            }

        grade = result.get("grade")
        if not isinstance(grade, int) or isinstance(grade, bool) or not 1 <= grade <= 4:
            return {"item_id": raw_id, "reason": "grade must be an integer between 1 and 4"}

        item = self._repo.get_item(self._user, lang, cid, facet)
        if item is None:
            return {"item_id": raw_id, "reason": "unknown item_id"}

        context = self._clean_context(result.get("context"))

        if fsrs_service.is_premature(item, reviewed_at):
            snapshot = {"stability": item.stability, "difficulty": item.difficulty}
            self._repo.put_log(
                self._user,
                lang,
                ReviewLog(
                    concept_id=cid,
                    facet=facet,
                    reviewed_at=reviewed_at.isoformat(),
                    grade=grade,
                    state_before=snapshot,
                    state_after={**snapshot, "due": item.due},
                    context=context,
                    duplicate=True,
                ),
            )
            return {
                "item_id": item.item_id,
                "next_due": item.due,
                "state": item.state,
                "note": "graded before due — logged, did not reschedule",
            }

        was_new = item.state == STATE_NEW
        review = fsrs_service.apply_review(item, grade, profile.desired_retention, reviewed_at)
        self._repo.put_item(self._user, lang, item)
        self._repo.put_log(
            self._user,
            lang,
            ReviewLog(
                concept_id=cid,
                facet=facet,
                reviewed_at=reviewed_at.isoformat(),
                grade=grade,
                state_before=review.state_before,
                state_after=review.state_after,
                context=context,
            ),
        )

        entry = {"item_id": item.item_id, "next_due": item.due, "state": item.state}
        notes = []
        if was_new:
            # Surface the cost in-band: introductions via record_result (items
            # the queue never served) still consume the daily new-item budget.
            notes.append("new item introduced — counts toward today's new-item budget")
        if (
            facet == FACET_RECOGNITION
            and grade >= SUCCESS_GRADE
            and self._unlock_production(lang, cid)
        ):
            notes.append("production facet unlocked for this concept")
        if notes:
            entry["note"] = "; ".join(notes)
        return entry

    def _unlock_production(self, lang: str, cid: str) -> bool:
        """Lazy production facet: created on the first successful recognition
        review of a vocab concept. The conditional write makes it idempotent."""
        concept = self._repo.get_concept(self._user, lang, cid)
        if concept is None or concept.type != TYPE_VOCAB:
            return False
        production = Item(
            concept_id=cid, facet=FACET_PRODUCTION, priority=concept.priority
        )
        return self._repo.create_item(self._user, lang, production)

    @staticmethod
    def _clean_context(context: Any) -> dict[str, str]:
        if not isinstance(context, dict):
            return {}
        return {
            field: str(context[field])[: ReviewLog.CONTEXT_MAX_CHARS]
            for field in ReviewLog.CONTEXT_FIELDS
            if context.get(field) is not None
        }

    def _bump_streak(self, lang: str, profile: Any, today: str) -> None:
        if profile.last_active_date == today:
            return
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        continued = profile.last_active_date == yesterday
        profile.streak_days = profile.streak_days + 1 if continued else 1
        profile.last_active_date = today
        self._repo.put_profile(self._user, lang, profile)

    # ---- add_items ----

    def add_items(
        self, lang: str, concepts: list[dict[str, Any]], now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or _utcnow()
        response: dict[str, list] = {
            "created": [],
            "merged": [],
            "needs_confirmation": [],
            "rejected": [],
        }
        for concept_input in concepts:
            kind, payload = self._add_one(lang, concept_input, now)
            response[kind].append(payload)
        return response

    def _add_one(
        self, lang: str, c: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any]]:
        reason = self._validate_concept_input(c)
        if reason:
            return "rejected", {"your_input": c, "reason": reason}

        ctype = c["type"]
        lemma = str(c["lemma"]).strip()
        reading = str(c["reading"]).strip() if c.get("reading") else None
        pos = c.get("pos") or (POS_GRAMMAR if ctype == TYPE_GRAMMAR else None)
        confirm_distinct = bool(c.get("confirm_distinct", False))
        normalized = normalize(lang, lemma, reading)
        example = self._clean_example(c.get("example"))

        hits = self._repo.find_by_normalized(self._user, lang, normalized)
        exact = next((h for h in hits if h.get("lemma") == lemma), None)
        if exact:
            return "merged", self._merge_example(lang, exact["concept_id"], c, example)

        same_pos = [h for h in hits if h.get("pos") == pos]
        if same_pos and not confirm_distinct:
            existing = same_pos[0]
            return "needs_confirmation", {
                "your_input": c,
                "existing": {
                    "concept_id": existing["concept_id"],
                    "lemma": existing.get("lemma"),
                    "pos": existing.get("pos"),
                    "meanings": list(existing.get("meanings", [])),
                },
                "reason": "same reading and pos, different lemma",
                "how_to_resolve": "retry with confirm_distinct: true if this is a distinct word",
            }

        cid = make_concept_id(
            lang, normalized, pos, salt_lemma=lemma if confirm_distinct else None
        )
        concept = Concept(
            concept_id=cid,
            type=ctype,
            lemma=lemma,
            normalized=normalized,
            reading=reading if lang == "ja" and ctype == TYPE_VOCAB else None,
            meanings=[str(m) for m in c["meanings"]],
            pos=pos,
            level=c.get("level") or "none",
            examples=[example] if example else [],
            source="claude",
            priority=0,  # claude-added words come from real usage: introduce soon
            created_at=now.isoformat(),
        )
        if not self._repo.create_concept(self._user, lang, concept):
            # Lost a race / idempotent retry: same deterministic ID already there.
            return "merged", self._merge_example(lang, cid, c, example)

        facet = FACET_GRAMMAR if ctype == TYPE_GRAMMAR else FACET_RECOGNITION
        self._repo.create_item(
            self._user, lang, Item(concept_id=cid, facet=facet, priority=concept.priority)
        )
        payload = {"concept_id": cid, "lemma": lemma, "facets_created": [facet]}
        if ctype == TYPE_VOCAB:
            payload["note"] = (
                "production facet will be created after the first successful "
                "recognition review"
            )
        return "created", payload

    def _merge_example(
        self, lang: str, cid: str, c: dict[str, Any], example: dict[str, str] | None
    ) -> dict[str, Any]:
        concept = self._repo.get_concept(self._user, lang, cid)
        action = "already known, nothing to add"
        if concept and example and not any(
            e.get("target") == example["target"] for e in concept.examples
        ):
            # Cap at the N most recent examples (context economy + 400KB limit).
            concept.examples = (concept.examples + [example])[-Concept.MAX_EXAMPLES :]
            self._repo.put_concept(self._user, lang, concept)
            action = "example appended"
        return {
            "concept_id": cid,
            "lemma": concept.lemma if concept else c.get("lemma"),
            "your_input": c,
            "action": action,
        }

    @staticmethod
    def _validate_concept_input(c: dict[str, Any]) -> str | None:
        if not isinstance(c, dict):
            return "concept must be an object"
        ctype = c.get("type")
        if ctype not in (TYPE_VOCAB, TYPE_GRAMMAR):
            return "type must be 'vocab' or 'grammar' (kanji is not enabled yet)"
        if not str(c.get("lemma") or "").strip():
            return "lemma is required"
        meanings = c.get("meanings")
        if not isinstance(meanings, list) or not meanings:
            return "meanings must be a non-empty list of strings"
        pos = c.get("pos") or (POS_GRAMMAR if ctype == TYPE_GRAMMAR else None)
        if pos not in POS_VALUES:
            return f"pos must be one of: {', '.join(sorted(POS_VALUES))}"
        level = c.get("level")
        if level is not None and level not in LEVELS:
            return f"level must be one of: {', '.join(sorted(LEVELS))}"
        return None

    @staticmethod
    def _clean_example(example: Any) -> dict[str, str] | None:
        if not isinstance(example, dict):
            return None
        target = example.get("target")
        native = example.get("native")
        if not target or not native:
            return None
        return {
            "target": str(target)[:EXAMPLE_FIELD_MAX_CHARS],
            "native": str(native)[:EXAMPLE_FIELD_MAX_CHARS],
            "source": "claude",
        }

    # ---- get_progress ----

    def get_progress(
        self, lang: str, period_days: int = 30, now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or _utcnow()
        today = now.date()
        # period_days=1 means "today only".
        since = (today - timedelta(days=period_days - 1)).isoformat()
        profile = self._repo.get_profile(self._user, lang)

        reviews_per_day: dict[str, int] = {}
        introduced_per_day: dict[str, int] = {}
        by_facet: dict[str, dict[str, int]] = {}
        by_exercise_type: dict[str, dict[str, int]] = {}
        total = successes = 0

        for log in self._repo.iter_all_logs(self._user, lang):
            log_date = log.reviewed_at[:10]
            if log_date < since or log.duplicate:
                continue
            reviews_per_day[log_date] = reviews_per_day.get(log_date, 0) + 1
            if log.state_before.get("stability") is None:
                introduced_per_day[log_date] = introduced_per_day.get(log_date, 0) + 1
            success = log.grade >= SUCCESS_GRADE
            total += 1
            successes += success
            self._tally(by_facet, log.facet, success)
            self._tally(by_exercise_type, log.context.get("exercise_type", "unknown"), success)

        leeches = self._repo.query_leeches(self._user, lang)
        leech_concepts = self._repo.batch_get_concepts(
            self._user, lang, [i.concept_id for i in leeches]
        )

        return {
            "period_days": period_days,
            "reviews_per_day": dict(sorted(reviews_per_day.items())),
            "success_rate": {
                "overall": round(successes / total, 3) if total else None,
                "by_facet": self._rates(by_facet),
                "by_exercise_type": self._rates(by_exercise_type),
            },
            "leeches": [
                {
                    "item_id": item.item_id,
                    "lemma": leech_concepts[item.concept_id].lemma,
                    "facet": item.facet,
                    "lapses": item.lapses,
                }
                for item in leeches
                if item.concept_id in leech_concepts
            ],
            "backlog": {
                "current": self._repo.count_backlog(self._user, lang),
                "introduced_per_day": dict(sorted(introduced_per_day.items())),
            },
            "coverage": self._coverage(lang),
            "streak_days": profile.streak_days,
        }

    @staticmethod
    def _tally(bucket: dict[str, dict[str, int]], key: str, success: bool) -> None:
        stats = bucket.setdefault(key, {"reviews": 0, "successes": 0})
        stats["reviews"] += 1
        stats["successes"] += success

    @staticmethod
    def _rates(bucket: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "reviews": stats["reviews"],
                "success_rate": round(stats["successes"] / stats["reviews"], 3),
            }
            for key, stats in sorted(bucket.items())
        }

    def _coverage(self, lang: str) -> dict[str, Any]:
        """Share of concepts reviewed at least once, per proficiency band.

        Language-agnostic: reports whatever levels exist for this user (N5…
        for Japanese, A1…C2 for CEFR languages), so English works unchanged.
        """
        by_level: dict[str, set[str]] = {}
        for c in self._repo.iter_concepts(self._user, lang):
            if c.level and c.level != "none":
                by_level.setdefault(c.level, set()).add(c.concept_id)
        if not by_level:
            return {}
        seen = {
            item.concept_id
            for item in self._repo.iter_items(self._user, lang)
            if item.reps > 0
        }
        return {
            level: round(len(cids & seen) / len(cids), 3)
            for level, cids in sorted(by_level.items())
        }
