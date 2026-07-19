#!/usr/bin/env python3
"""One-off local seed: JLPT N5 vocabulary (~700 concepts) into DynamoDB.

Sources (downloaded on first run, cached under data/seed-cache/):
- elzup/jlpt-word-list n5.csv — the N5 word list (expression, reading, English gloss)
- scriptin/jmdict-simplified jmdict-fre — French glosses and part-of-speech tags

Each word becomes a Concept (source=seed, level=N5) plus its `recognition`
Item. Drip priority: JMdict-common words first, then kana order — the CSV has
no frequency data. Words missing from jmdict-fre keep their English gloss
(reported at the end; fix via admin script later).

Usage:
    python scripts/seed_n5.py --dry-run
    python scripts/seed_n5.py --table language-memory --user u_001 [--limit 50]

Requires AWS credentials in the environment (or --dry-run).
"""

import argparse
import csv
import json
import sys
import unicodedata
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yomu import keys  # noqa: E402
from yomu.ids import concept_id, normalize  # noqa: E402
from yomu.models import Concept, Item  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "seed-cache"
N5_CSV_URL = "https://raw.githubusercontent.com/elzup/jlpt-word-list/master/src/n5.csv"
JMDICT_RELEASE_API = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"

# JMdict partOfSpeech tags → our controlled vocabulary.
POS_MAP = {
    "v1": "verb-ichidan",
    "v5aru": "verb-godan", "v5b": "verb-godan", "v5g": "verb-godan",
    "v5k": "verb-godan", "v5k-s": "verb-godan", "v5m": "verb-godan",
    "v5n": "verb-godan", "v5r": "verb-godan", "v5r-i": "verb-godan",
    "v5s": "verb-godan", "v5t": "verb-godan", "v5u": "verb-godan",
    "v5u-s": "verb-godan",
    "vk": "verb-irregular", "vs-i": "verb-irregular", "vs-s": "verb-irregular",
    "vz": "verb-irregular",
    "n": "noun", "n-adv": "noun", "n-t": "noun", "vs": "noun",
    "adj-i": "adj-i", "adj-ix": "adj-i",
    "adj-na": "adj-na",
    "adv": "adverb", "adv-to": "adverb",
    "prt": "particle",
    "pn": "pronoun",
    "ctr": "counter",
    "conj": "conjunction",
    "int": "interjection",
    "adj-pn": "prenominal",
    "exp": "expression",
}
# Nominal-ish tags, used only when no sense carries a primary tag
# (e.g. 青 appears in jmdict-fre only as a "pref" entry).
POS_MAP_WEAK = {
    "adj-no": "noun", "pref": "noun", "suf": "noun",
    "n-pref": "noun", "n-suf": "noun", "num": "noun",
}
POS_FALLBACK = "expression"


def fetch(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "yomu-seed"})
    with urllib.request.urlopen(request) as resp:
        dest.write_bytes(resp.read())
    return dest


def load_n5_rows() -> list[dict[str, str]]:
    path = fetch(N5_CSV_URL, CACHE_DIR / "n5.csv")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_jmdict_fre() -> dict:
    """Download the jmdict-fre zip (release asset name embeds the version)."""
    json_path = CACHE_DIR / "jmdict-fre.json"
    if not json_path.exists():
        with urllib.request.urlopen(
            urllib.request.Request(JMDICT_RELEASE_API, headers={"User-Agent": "yomu-seed"})
        ) as resp:
            release = json.load(resp)
        asset = next(
            a for a in release["assets"]
            if a["name"].startswith("jmdict-fre-") and a["name"].endswith(".json.zip")
        )
        zip_path = fetch(asset["browser_download_url"], CACHE_DIR / asset["name"])
        with zipfile.ZipFile(zip_path) as zf:
            inner = zf.namelist()[0]
            json_path.write_bytes(zf.read(inner))
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def index_jmdict(jmdict: dict) -> dict[tuple[str, str], dict]:
    """(written form, kana reading) → best entry.

    Several JMdict entries can share a written form + reading (homographs);
    prefer the one with French glosses, then the common one, so a rare entry
    never shadows the everyday word.
    """
    index: dict[tuple[str, str], dict] = {}

    def score(entry: dict) -> tuple[int, int, int]:
        return (bool(french_meanings(entry)), is_common(entry), len(entry.get("sense", [])))

    for word in jmdict["words"]:
        kana_texts = [k["text"] for k in word.get("kana", [])]
        written = [k["text"] for k in word.get("kanji", [])] or kana_texts
        for w in written:
            for kana in kana_texts:
                current = index.get((w, kana))
                if current is None or score(word) > score(current):
                    index[(w, kana)] = word
    return index


def french_meanings(entry: dict) -> list[str]:
    meanings: list[str] = []
    for sense in entry.get("sense", []):
        for gloss in sense.get("gloss", []):
            if gloss.get("lang") == "fre" and gloss.get("text"):
                meanings.append(gloss["text"])
    # Dedup, keep order, cap for context economy.
    return list(dict.fromkeys(meanings))[:5]


def jmdict_pos(entry: dict) -> str | None:
    tags = [t for s in entry.get("sense", []) for t in s.get("partOfSpeech", [])]
    for tag in tags:
        if tag in POS_MAP:
            return POS_MAP[tag]
    for tag in tags:
        if tag in POS_MAP_WEAK:
            return POS_MAP_WEAK[tag]
    return None


def is_common(entry: dict) -> bool:
    return any(k.get("common") for k in entry.get("kanji", []) + entry.get("kana", []))


def build_concepts(limit: int | None) -> list[Concept]:
    rows = load_n5_rows()
    jmdict_index = index_jmdict(load_jmdict_fre())
    now = datetime.now(UTC).isoformat()

    enriched = []
    missing_french = []
    seen_lemmas: dict[tuple[str, str], list] = {}
    for row in rows:
        # Some rows list alternatives ("足; 脚", "いい; よい"): keep the first.
        lemma = unicodedata.normalize("NFKC", row["expression"].split(";")[0].strip())
        reading = unicodedata.normalize("NFKC", row["reading"].split(";")[0].strip())
        if (lemma, reading) in seen_lemmas:
            # Duplicate CSV row (e.g. キロ for kilogram and kilometer):
            # merge the meanings into the first occurrence.
            first = seen_lemmas[(lemma, reading)]
            extra = [m.strip() for m in row["meaning"].split(",")]
            first[4] = list(dict.fromkeys(first[4] + extra))[:5]
            continue
        entry = jmdict_index.get((lemma, reading))
        meanings = french_meanings(entry) if entry else []
        if not meanings:
            missing_french.append(lemma)
            meanings = [m.strip() for m in row["meaning"].split(",")][:5]
        pos = (jmdict_pos(entry) if entry else None) or POS_FALLBACK
        common = is_common(entry) if entry else False
        record = [not common, reading, lemma, pos, meanings]
        seen_lemmas[(lemma, reading)] = record
        enriched.append(record)

    # Drip order: common words first, then kana order.
    enriched.sort(key=lambda e: (e[0], e[1]))

    concepts: list[Concept] = []
    seen_ids: dict[str, str] = {}
    for rank, (_, reading, lemma, pos, meanings) in enumerate(enriched, start=1):
        normalized = normalize("ja", lemma, reading)
        cid = concept_id("ja", normalized, pos)
        if cid in seen_ids:
            # Homophone within the seed (same reading + pos, different lemma):
            # salt with the lemma, exactly like a confirm_distinct add.
            print(f"homophone: {lemma} vs {seen_ids[cid]} ({reading}, {pos}) — salting id")
            cid = concept_id("ja", normalized, pos, salt_lemma=lemma)
        seen_ids[cid] = lemma
        concepts.append(
            Concept(
                concept_id=cid,
                type="vocab",
                lemma=lemma,
                normalized=normalized,
                reading=reading,
                meanings=meanings,
                pos=pos,
                level="N5",
                source="seed",
                priority=rank,
                created_at=now,
            )
        )

    if missing_french:
        print(f"⚠ {len(missing_french)} words without French gloss (kept English): "
              f"{'、'.join(missing_french[:10])}{'…' if len(missing_french) > 10 else ''}")
    return concepts[:limit] if limit else concepts


def seed(table_name: str, user_id: str, lang: str, concepts: list[Concept]) -> None:
    import os

    import boto3

    # DYNAMODB_ENDPOINT switches to a local emulator (see scripts/dev_server.py).
    dynamodb = boto3.resource(
        "dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None
    )
    table = dynamodb.Table(table_name)
    pk = keys.pk(user_id, lang)
    with table.batch_writer() as batch:
        for concept in concepts:
            batch.put_item(Item=concept.to_dynamo(pk))
            item = Item(
                concept_id=concept.concept_id,
                facet="recognition",
                priority=concept.priority,
            )
            batch.put_item(Item=item.to_dynamo(pk))
    print(f"seeded {len(concepts)} concepts (+ recognition items) into {table_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default="language-memory")
    parser.add_argument("--user", default="u_001")
    parser.add_argument("--lang", default="ja")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    concepts = build_concepts(args.limit)
    print(f"{len(concepts)} concepts ready")
    if args.dry_run:
        for concept in concepts[:15]:
            print(f"  #{concept.priority:>4} {concept.lemma} ({concept.reading}) "
                  f"[{concept.pos}] {'; '.join(concept.meanings[:2])}")
        print("  …")
        return
    seed(args.table, args.user, args.lang, concepts)


if __name__ == "__main__":
    main()
