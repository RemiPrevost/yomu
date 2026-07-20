from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)
LANG = "ja"


def vocab(lemma: str, reading: str, meaning: str, pos: str = "noun", **kw) -> dict:
    return {
        "type": "vocab",
        "lemma": lemma,
        "reading": reading,
        "meanings": [meaning],
        "pos": pos,
        **kw,
    }


def add_one(service, concept: dict) -> str:
    """Add a concept and return its recognition/grammar item_id."""
    resp = service.add_items(LANG, [concept], now=NOW)
    assert resp["created"], resp
    entry = resp["created"][0]
    return f"{entry['concept_id']}#{entry['facets_created'][0]}"


# ---- add_items ----


class TestAddItems:
    def test_creates_vocab_with_recognition_facet_only(self, service):
        resp = service.add_items(
            LANG,
            [vocab("食べる", "たべる", "manger", pos="verb-ichidan",
                   example={"target": "パンを食べる", "native": "manger du pain"},
                   level="N5")],
            now=NOW,
        )
        assert len(resp["created"]) == 1
        entry = resp["created"][0]
        assert entry["facets_created"] == ["recognition"]
        assert "production" in entry["note"]

    def test_creates_grammar_with_grammar_facet(self, service):
        resp = service.add_items(
            LANG,
            [{"type": "grammar", "lemma": "〜てもいいです",
              "meanings": ["avoir la permission de"], "level": "N5"}],
            now=NOW,
        )
        assert resp["created"][0]["facets_created"] == ["grammar"]

    def test_exact_duplicate_merges_and_appends_example(self, service, repo):
        service.add_items(LANG, [vocab("犬", "いぬ", "chien")], now=NOW)
        resp = service.add_items(
            LANG,
            [vocab("犬", "いぬ", "chien",
                   example={"target": "犬がいます", "native": "il y a un chien"})],
            now=NOW,
        )
        assert not resp["created"]
        assert resp["merged"][0]["action"] == "example appended"

        cid = resp["merged"][0]["concept_id"]
        concept = repo.get_concept("u_test", LANG, cid)
        assert concept.examples[-1]["target"] == "犬がいます"
        assert concept.examples[-1]["source"] == "claude"

    def test_examples_capped_at_five_most_recent(self, service, repo):
        service.add_items(LANG, [vocab("猫", "ねこ", "chat")], now=NOW)
        for i in range(7):
            resp = service.add_items(
                LANG,
                [vocab("猫", "ねこ", "chat",
                       example={"target": f"例文{i}", "native": f"exemple {i}"})],
                now=NOW,
            )
        cid = resp["merged"][0]["concept_id"]
        concept = repo.get_concept("u_test", LANG, cid)
        assert len(concept.examples) == 5
        assert concept.examples[-1]["target"] == "例文6"
        assert concept.examples[0]["target"] == "例文2"

    def test_homophone_needs_confirmation_then_confirm_distinct(self, service):
        service.add_items(LANG, [vocab("橋", "はし", "pont")], now=NOW)

        resp = service.add_items(LANG, [vocab("箸", "はし", "baguettes")], now=NOW)
        assert not resp["created"]
        conflict = resp["needs_confirmation"][0]
        assert conflict["existing"]["lemma"] == "橋"
        assert "confirm_distinct" in conflict["how_to_resolve"]

        resp = service.add_items(
            LANG, [vocab("箸", "はし", "baguettes", confirm_distinct=True)], now=NOW
        )
        assert resp["created"][0]["lemma"] == "箸"

    def test_different_pos_same_reading_is_no_conflict(self, service):
        service.add_items(LANG, [vocab("橋", "はし", "pont")], now=NOW)
        resp = service.add_items(
            LANG,
            [vocab("端", "はし", "bord", pos="expression")],
            now=NOW,
        )
        assert resp["created"]

    def test_invalid_inputs_rejected_individually(self, service):
        resp = service.add_items(
            LANG,
            [
                {"type": "kanji", "lemma": "水", "meanings": ["eau"], "pos": "noun"},
                {"type": "vocab", "lemma": "", "meanings": ["vide"], "pos": "noun"},
                {"type": "vocab", "lemma": "水", "meanings": [], "pos": "noun"},
                {"type": "vocab", "lemma": "水", "meanings": ["eau"], "pos": "nominal"},
                vocab("水", "みず", "eau"),
            ],
            now=NOW,
        )
        assert len(resp["rejected"]) == 4
        assert len(resp["created"]) == 1
        for entry in resp["rejected"]:
            assert entry["reason"]


# ---- get_review_queue ----


class TestReviewQueue:
    def test_new_items_clamped_to_daily_drip(self, service):
        for i in range(8):
            service.add_items(LANG, [vocab(f"語彙{i}", f"ごい{i}", f"mot {i}")], now=NOW)

        queue = service.get_review_queue(LANG, now=NOW)
        assert len(queue["new"]) == 5  # default new_per_day
        assert queue["due"] == []
        assert queue["stats"]["total_backlog"] == 8

        # Concepts carry display data; no second call needed.
        entry = queue["new"][0]
        assert entry["concept"]["lemma"]
        assert entry["concept"]["meanings"]

    def test_stats_exposes_read_only_settings_and_drip_usage(self, service):
        for i in range(8):
            service.add_items(LANG, [vocab(f"語彙{i}", f"ごい{i}", f"mot {i}")], now=NOW)
        queue = service.get_review_queue(LANG, now=NOW)
        stats = queue["stats"]
        assert stats["settings"] == {
            "new_per_day": 5,
            "desired_retention": 0.9,
            "ui_lang": "fr",
        }
        assert stats["new_introduced_today"] == 0
        assert stats["new_remaining_today"] == 5

        # After introducing 3, the remaining drip drops accordingly.
        service.record_result(
            LANG, [{"item_id": e["item_id"], "grade": 3} for e in queue["new"][:3]], now=NOW
        )
        stats2 = service.get_review_queue(LANG, now=NOW)["stats"]
        assert stats2["new_introduced_today"] == 3
        assert stats2["new_remaining_today"] == 2

    def test_max_new_respects_explicit_request(self, service):
        for i in range(4):
            service.add_items(LANG, [vocab(f"単語{i}", f"たんご{i}", f"mot {i}")], now=NOW)
        queue = service.get_review_queue(LANG, max_new=2, now=NOW)
        assert len(queue["new"]) == 2

    def test_drip_counts_items_introduced_earlier_today(self, service):
        for i in range(8):
            service.add_items(LANG, [vocab(f"言葉{i}", f"ことば{i}", f"mot {i}")], now=NOW)

        queue = service.get_review_queue(LANG, now=NOW)
        service.record_result(
            LANG,
            [{"item_id": e["item_id"], "grade": 3} for e in queue["new"][:3]],
            now=NOW,
        )

        # 3 of 5 daily slots used; only 2 left, even across a new "session".
        queue = service.get_review_queue(LANG, now=NOW + timedelta(hours=2))
        assert len(queue["new"]) == 2
        introduced = {e["item_id"] for e in queue["new"]}
        assert len(introduced) == 2

    def test_reviewed_item_reappears_once_learning_step_matures(self, service):
        item_id = add_one(service, vocab("水", "みず", "eau"))
        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)

        # 5 minutes later: the 10-minute learning step has not matured yet.
        queue = service.get_review_queue(LANG, now=NOW + timedelta(minutes=5))
        assert all(e["item_id"] != item_id for e in queue["due"])

        # Afternoon session: the item is due again — same-day re-challenge.
        queue = service.get_review_queue(LANG, now=NOW + timedelta(hours=4))
        assert any(e["item_id"] == item_id for e in queue["due"])

    def test_due_entry_memory_signals(self, service):
        item_id = add_one(service, vocab("火", "ひ", "feu"))
        service.record_result(
            LANG,
            [{"item_id": item_id, "grade": 1,
              "context": {"exercise_type": "listening", "sentence": "火"}}],
            now=NOW,
        )

        queue = service.get_review_queue(LANG, now=NOW + DAY)
        entry = next(e for e in queue["due"] if e["item_id"] == item_id)
        memory = entry["memory"]
        assert memory["reps"] == 1
        assert memory["last_grade"] == 1
        assert memory["recent_failures_context"] == ["listening"]
        assert memory["is_leech"] is False
        assert "stability" not in memory and "difficulty" not in memory

    def test_overdue_first_ordering(self, service):
        early = add_one(service, vocab("一", "いち", "un"))
        late = add_one(service, vocab("二", "に", "deux"))
        service.record_result(LANG, [{"item_id": early, "grade": 3}], now=NOW - 5 * DAY)
        service.record_result(LANG, [{"item_id": late, "grade": 3}], now=NOW - DAY)

        queue = service.get_review_queue(LANG, max_new=0, now=NOW)
        ids = [e["item_id"] for e in queue["due"]]
        assert ids.index(early) < ids.index(late)


# ---- record_result ----


class TestRecordResult:
    def test_first_review_moves_item_out_of_backlog(self, service, repo):
        item_id = add_one(service, vocab("山", "やま", "montagne"))
        assert repo.count_backlog("u_test", LANG) == 1

        resp = service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        entry = resp["recorded"][0]
        assert entry["state"] == "learning"
        assert entry["next_due"] == (NOW + timedelta(minutes=10)).isoformat()
        # A first review is an introduction; the note makes the budget cost
        # visible to the client alongside the production-facet unlock.
        assert "new item introduced" in entry["note"]
        # The recognition item left the backlog, but the successful review
        # unlocked the production facet, which enters it as a new item.
        backlog = repo.query_new_items("u_test", LANG, limit=10)
        assert [i.facet for i in backlog] == ["production"]
        assert resp["session_summary"]["new_introduced_today"] == 1

    def test_unknown_item_rejected_rest_of_batch_proceeds(self, service):
        item_id = add_one(service, vocab("川", "かわ", "rivière"))
        resp = service.record_result(
            LANG,
            [
                {"item_id": "deadbeef0000#recognition", "grade": 3},
                {"item_id": "not-an-item-id", "grade": 3},
                {"item_id": item_id, "grade": 5},
                {"item_id": item_id, "grade": 3},
            ],
            now=NOW,
        )
        assert len(resp["recorded"]) == 1
        assert len(resp["rejected"]) == 3
        reasons = " | ".join(e["reason"] for e in resp["rejected"])
        assert "unknown" in reasons
        assert "grade" in reasons

    def test_premature_grade_logged_but_not_rescheduled(self, service, repo):
        item_id = add_one(service, vocab("空", "そら", "ciel"))
        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        item_before = repo.get_item("u_test", LANG, *item_id.split("#"))

        # Graded again 3 minutes later — before the 10-minute step matured
        # (an LLM retry, or re-testing ahead of the server's schedule).
        resp = service.record_result(
            LANG, [{"item_id": item_id, "grade": 1}], now=NOW + timedelta(minutes=3)
        )
        entry = resp["recorded"][0]
        assert "before due" in entry["note"]

        item_after = repo.get_item("u_test", LANG, *item_id.split("#"))
        assert item_after.stability == item_before.stability
        assert item_after.reps == 1

        logs = repo.query_item_logs("u_test", LANG, *item_id.split("#"))
        assert [log.duplicate for log in logs] == [True, False]

    def test_same_day_re_review_after_step_matures_drives_fsrs(self, service, repo):
        item_id = add_one(service, vocab("海", "うみ", "mer"))
        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        resp = service.record_result(
            LANG, [{"item_id": item_id, "grade": 3}], now=NOW + timedelta(minutes=15)
        )

        entry = resp["recorded"][0]
        assert entry["state"] == "review"
        assert datetime.fromisoformat(entry["next_due"]) > NOW + DAY
        assert repo.get_item("u_test", LANG, *item_id.split("#")).reps == 2

    def test_lazy_production_facet_on_first_success(self, service, repo):
        item_id = add_one(service, vocab("月", "つき", "lune"))
        cid = item_id.split("#")[0]

        resp = service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        assert "production" in resp["recorded"][0]["note"]

        production = repo.get_item("u_test", LANG, cid, "production")
        assert production is not None
        assert production.state == "new"

    def test_no_production_facet_on_failure(self, service, repo):
        item_id = add_one(service, vocab("星", "ほし", "étoile"))
        cid = item_id.split("#")[0]
        service.record_result(LANG, [{"item_id": item_id, "grade": 1}], now=NOW)
        assert repo.get_item("u_test", LANG, cid, "production") is None

        # Unlocks later, once the recognition review succeeds.
        resp = service.record_result(LANG, [{"item_id": item_id, "grade": 2}], now=NOW + DAY)
        assert "production" in resp["recorded"][0].get("note", "")
        assert repo.get_item("u_test", LANG, cid, "production") is not None

    def test_no_production_facet_for_grammar(self, service, repo):
        item_id = add_one(
            service,
            {"type": "grammar", "lemma": "〜ながら", "meanings": ["tout en faisant"]},
        )
        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        cid = item_id.split("#")[0]
        assert repo.get_item("u_test", LANG, cid, "production") is None

    def test_context_is_truncated(self, service, repo):
        item_id = add_one(service, vocab("雨", "あめ", "pluie"))
        service.record_result(
            LANG,
            [{"item_id": item_id, "grade": 3,
              "context": {"sentence": "あ" * 1000, "irrelevant_field": "x"}}],
            now=NOW,
        )
        log = repo.query_item_logs("u_test", LANG, *item_id.split("#"))[0]
        assert len(log.context["sentence"]) == 300
        assert "irrelevant_field" not in log.context

    def test_batch_item_timestamps_match_their_logs_exactly(self, service, repo):
        # Batched results get per-entry microsecond offsets (unique LOG# keys);
        # the item's first/last_review must carry the same offset timestamp so
        # state stays exactly auditable against the logs.
        ids = [add_one(service, vocab(f"色{i}", f"いろ{i}", f"couleur {i}")) for i in range(3)]
        service.record_result(
            LANG, [{"item_id": i, "grade": 3} for i in ids], now=NOW
        )
        for item_id in ids:
            item = repo.get_item("u_test", LANG, *item_id.split("#"))
            log = repo.query_item_logs("u_test", LANG, *item_id.split("#"))[0]
            assert item.last_review == log.reviewed_at
            assert item.first_review == log.reviewed_at
            assert item.due == log.state_after["due"]

    def test_streak_increments_on_consecutive_days_and_resets(self, service, repo):
        item_id = add_one(service, vocab("風", "かぜ", "vent"))

        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW)
        assert repo.get_profile("u_test", LANG).streak_days == 1

        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW + DAY)
        assert repo.get_profile("u_test", LANG).streak_days == 2

        service.record_result(LANG, [{"item_id": item_id, "grade": 3}], now=NOW + 5 * DAY)
        assert repo.get_profile("u_test", LANG).streak_days == 1


# ---- get_progress ----


class TestProgress:
    @pytest.fixture
    def populated(self, service):
        ids = [
            add_one(service, vocab("元気", "げんき", "en forme", pos="adj-na", level="N5")),
            add_one(service, vocab("学校", "がっこう", "école", level="N5")),
            add_one(service, vocab("先生", "せんせい", "professeur", level="N5")),
        ]
        service.record_result(
            LANG,
            [
                {"item_id": ids[0], "grade": 3, "context": {"exercise_type": "translation"}},
                {"item_id": ids[1], "grade": 1, "context": {"exercise_type": "cloze"}},
            ],
            now=NOW - DAY,
        )
        service.record_result(
            LANG,
            [{"item_id": ids[0], "grade": 3, "context": {"exercise_type": "translation"}}],
            now=NOW,
        )
        return ids

    def test_aggregates(self, service, populated):
        progress = service.get_progress(LANG, period_days=30, now=NOW)

        assert progress["reviews_per_day"] == {"2026-07-18": 2, "2026-07-19": 1}
        assert progress["success_rate"]["overall"] == round(2 / 3, 3)
        assert progress["success_rate"]["by_exercise_type"]["translation"]["success_rate"] == 1.0
        assert progress["success_rate"]["by_exercise_type"]["cloze"]["success_rate"] == 0.0
        # 先生 never introduced + the production facet unlocked for 元気.
        assert progress["backlog"]["current"] == 2
        assert progress["backlog"]["introduced_per_day"] == {"2026-07-18": 2}
        # 2 of 3 N5 concepts have a reviewed item.
        assert progress["coverage"]["N5"] == round(2 / 3, 3)

    def test_period_filter_excludes_old_logs(self, service, populated):
        progress = service.get_progress(LANG, period_days=1, now=NOW)
        assert progress["reviews_per_day"] == {"2026-07-19": 1}
