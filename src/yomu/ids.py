"""Normalization and deterministic concept IDs.

`normalized` is the dedup key (GSI2 sort key). It is always computed
server-side, never trusted from the LLM.
"""

import hashlib
import unicodedata

_KATAKANA_TO_HIRAGANA = {
    code: code - 0x60
    for code in range(0x30A1, 0x30F7)  # ァ..ヶ → ぁ..ゖ
}


def normalize(lang: str, lemma: str, reading: str | None) -> str:
    """Compute the dedup key for a concept.

    JA: NFKC kana of the dictionary form (from `reading` when present,
    falling back to `lemma` for e.g. grammar patterns), with katakana
    folded to hiragana so コーヒー and こーひー collide.
    Other languages: NFKC lowercased lemma.
    """
    if lang == "ja":
        base = reading or lemma
        return unicodedata.normalize("NFKC", base).translate(_KATAKANA_TO_HIRAGANA)
    return unicodedata.normalize("NFKC", lemma).lower()


def concept_id(lang: str, normalized: str, pos: str, salt_lemma: str | None = None) -> str:
    """First 12 hex chars of SHA-256 over the identity fields.

    `salt_lemma` is set when the caller confirmed a homophone is a distinct
    concept (confirm_distinct); salting with the lemma keeps the ID stable
    while separating it from the existing concept.
    """
    material = f"{normalized}|{pos}|{lang}"
    if salt_lemma is not None:
        material += f"|{salt_lemma}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
