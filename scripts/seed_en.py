#!/usr/bin/env python3
"""Seed CEFR English concepts from data/seed/en_b1.json into DynamoDB.

Language-agnostic counterpart to seed_n5.py: reads a JSON list of
{unit, idx, head, pos, fr, level} entries (French glosses authored by us),
writes one Concept (source=seed, lang=en) + its recognition Item each.

Drip priority preserves course order: unit*1000 + idx, so unit 1 comes first.

Usage:
    python scripts/seed_en.py --dry-run
    python scripts/seed_en.py --user u_002 [--table language-memory]
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yomu import keys  # noqa: E402
from yomu.ids import concept_id, normalize  # noqa: E402
from yomu.models import Concept, Item  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "seed" / "en_b1.json"
LANG = "en"


def build_concepts() -> list[Concept]:
    entries = json.loads(DATA.read_text())
    now = datetime.now(UTC).isoformat()
    concepts, seen = [], {}
    for e in entries:
        lemma = e["head"].strip()
        normalized = normalize(LANG, lemma, None)
        cid = concept_id(LANG, normalized, e["pos"])
        if cid in seen:
            # Homograph within the seed (same lemma+pos): salt with unit/idx.
            print(f"dup id for {lemma} ({e['pos']}) — salting")
            cid = concept_id(
                LANG, normalized, e["pos"], salt_lemma=f"{lemma}#{e['unit']}.{e['idx']}"
            )
        seen[cid] = lemma
        concepts.append(
            Concept(
                concept_id=cid,
                type="vocab",
                lemma=lemma,
                normalized=normalized,
                reading=None,  # non-JA: no kana reading
                meanings=e["fr"],
                pos=e["pos"],
                level=e["level"],
                source="seed",
                priority=e["unit"] * 1000 + e["idx"],
                created_at=now,
            )
        )
    return concepts


def seed(table_name: str, user_id: str, concepts: list[Concept]) -> None:
    import os

    import boto3

    dynamodb = boto3.resource(
        "dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None
    )
    table = dynamodb.Table(table_name)
    pk = keys.pk(user_id, LANG)
    with table.batch_writer() as batch:
        for c in concepts:
            batch.put_item(Item=c.to_dynamo(pk))
            batch.put_item(
                Item=Item(
                    concept_id=c.concept_id, facet="recognition", priority=c.priority
                ).to_dynamo(pk)
            )
    print(f"seeded {len(concepts)} concepts (+ recognition items) into {table_name} "
          f"under {pk}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default="language-memory")
    parser.add_argument("--user", default="u_002")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    concepts = build_concepts()
    print(f"{len(concepts)} concepts ready")
    if args.dry_run:
        for c in concepts[:12]:
            print(f"  #{c.priority} {c.lemma} [{c.pos}] {c.level} → {'; '.join(c.meanings)}")
        print("  …")
        return
    seed(args.table, args.user, concepts)


if __name__ == "__main__":
    main()
