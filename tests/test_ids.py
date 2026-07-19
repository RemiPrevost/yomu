from yomu.ids import concept_id, normalize


def test_ja_normalize_prefers_reading():
    assert normalize("ja", "食べる", "たべる") == "たべる"


def test_ja_normalize_falls_back_to_lemma():
    # Grammar patterns have no reading.
    assert normalize("ja", "〜てもいいです", None) == "〜てもいいです"


def test_ja_normalize_folds_katakana_to_hiragana():
    assert normalize("ja", "コーヒー", "コーヒー") == normalize("ja", "コーヒー", "こーひー")


def test_ja_normalize_applies_nfkc():
    # Half-width katakana normalizes to full-width, then folds to hiragana.
    assert normalize("ja", "コーヒー", "ｺｰﾋｰ") == "こーひー"


def test_other_lang_normalize_lowercases_lemma():
    assert normalize("de", "Haus", None) == "haus"


def test_concept_id_is_deterministic_12_hex():
    a = concept_id("ja", "たべる", "verb-ichidan")
    assert a == concept_id("ja", "たべる", "verb-ichidan")
    assert len(a) == 12
    int(a, 16)  # valid hex


def test_concept_id_varies_with_pos_and_lang():
    base = concept_id("ja", "はし", "noun")
    assert base != concept_id("ja", "はし", "particle")
    assert base != concept_id("ko", "はし", "noun")


def test_concept_id_salted_for_confirmed_homophones():
    bridge = concept_id("ja", "はし", "noun")
    chopsticks = concept_id("ja", "はし", "noun", salt_lemma="箸")
    assert bridge != chopsticks
    # Salting is stable too.
    assert chopsticks == concept_id("ja", "はし", "noun", salt_lemma="箸")
