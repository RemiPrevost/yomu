"""DynamoDB access for the single `language-memory` table.

Index layout (see SPEC.md §4):
- GSI1 "queue":  PK → queue_key   (sparse: items only)
- GSI2 "dedup":  PK → normalized  (sparse: concepts only)
"""

import os
from collections.abc import Iterator
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

from yomu import keys
from yomu.models import LEECH_LAPSES, Concept, Item, Profile, ReviewLog

GSI1 = "GSI1-queue"
GSI2 = "GSI2-dedup"

_DUE_FLOOR = "DUE#0000-00-00"


class Repository:
    def __init__(self, table_name: str | None = None, dynamodb: Any = None):
        table_name = table_name or os.environ["TABLE_NAME"]
        if dynamodb is None:
            # DYNAMODB_ENDPOINT switches to a local emulator (moto/dynamodb-local).
            dynamodb = boto3.resource(
                "dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None
            )
        self._table = dynamodb.Table(table_name)
        self._client = self._table.meta.client
        self._table_name = table_name

    # ---- profile ----

    def get_profile(self, user_id: str, lang: str) -> Profile:
        resp = self._table.get_item(
            Key={"PK": keys.pk(user_id, lang), "SK": keys.PROFILE_SK}
        )
        return Profile.from_dynamo(resp.get("Item"))

    def put_profile(self, user_id: str, lang: str, profile: Profile) -> None:
        self._table.put_item(Item=profile.to_dynamo(keys.pk(user_id, lang)))

    # ---- user identity mapping ----
    # Auth phase 2: Cognito's `sub` is the external identity. A USERMAP row
    # points it at an internal user_id so pre-Cognito data (u_001) survives;
    # without a row, the sub itself is the user_id (new users).

    def get_user_mapping(self, external_id: str) -> str | None:
        resp = self._table.get_item(Key={"PK": f"USERMAP#{external_id}", "SK": "MAPPING"})
        record = resp.get("Item")
        return record.get("user_id") if record else None

    def put_user_mapping(self, external_id: str, user_id: str) -> None:
        self._table.put_item(
            Item={
                "PK": f"USERMAP#{external_id}",
                "SK": "MAPPING",
                "entity": "usermap",
                "user_id": user_id,
            }
        )

    # ---- concepts ----

    def get_concept(self, user_id: str, lang: str, concept_id: str) -> Concept | None:
        resp = self._table.get_item(
            Key={"PK": keys.pk(user_id, lang), "SK": keys.concept_sk(concept_id)}
        )
        record = resp.get("Item")
        return Concept.from_dynamo(record) if record else None

    def put_concept(self, user_id: str, lang: str, concept: Concept) -> None:
        self._table.put_item(Item=concept.to_dynamo(keys.pk(user_id, lang)))

    def create_concept(self, user_id: str, lang: str, concept: Concept) -> bool:
        """Conditional create; returns False if the concept already exists (lost race)."""
        try:
            self._table.put_item(
                Item=concept.to_dynamo(keys.pk(user_id, lang)),
                ConditionExpression="attribute_not_exists(SK)",
            )
            return True
        except self._client.exceptions.ConditionalCheckFailedException:
            return False

    def find_by_normalized(self, user_id: str, lang: str, normalized: str) -> list[dict[str, Any]]:
        """Dedup lookup on GSI2. Returns the projected concept summaries
        (concept_id, lemma, pos, meanings) for every concept sharing the key."""
        resp = self._table.query(
            IndexName=GSI2,
            KeyConditionExpression=(
                Key("PK").eq(keys.pk(user_id, lang)) & Key("normalized").eq(normalized)
            ),
        )
        return resp.get("Items", [])

    def batch_get_concepts(
        self, user_id: str, lang: str, concept_ids: list[str]
    ) -> dict[str, Concept]:
        """BatchGetItem join used to hydrate queue entries with display data."""
        pk = keys.pk(user_id, lang)
        result: dict[str, Concept] = {}
        unique = list(dict.fromkeys(concept_ids))
        for start in range(0, len(unique), 100):
            request = {
                self._table_name: {
                    "Keys": [
                        {"PK": pk, "SK": keys.concept_sk(cid)}
                        for cid in unique[start : start + 100]
                    ]
                }
            }
            while request:
                resp = self._table.meta.client.batch_get_item(RequestItems=request)
                # The resource-level client on Table returns deserialized values.
                for record in resp.get("Responses", {}).get(self._table_name, []):
                    concept = Concept.from_dynamo(record)
                    result[concept.concept_id] = concept
                request = resp.get("UnprocessedKeys") or None
        return result

    # ---- items ----

    def get_item(self, user_id: str, lang: str, concept_id: str, facet: str) -> Item | None:
        resp = self._table.get_item(
            Key={"PK": keys.pk(user_id, lang), "SK": keys.item_sk(concept_id, facet)}
        )
        record = resp.get("Item")
        return Item.from_dynamo(record) if record else None

    def put_item(self, user_id: str, lang: str, item: Item) -> None:
        """Full put; queue_key is recomputed by Item.to_dynamo on every write."""
        self._table.put_item(Item=item.to_dynamo(keys.pk(user_id, lang)))

    def create_item(self, user_id: str, lang: str, item: Item) -> bool:
        try:
            self._table.put_item(
                Item=item.to_dynamo(keys.pk(user_id, lang)),
                ConditionExpression="attribute_not_exists(SK)",
            )
            return True
        except self._client.exceptions.ConditionalCheckFailedException:
            return False

    def query_due_items(self, user_id: str, lang: str, now: str, limit: int) -> list[Item]:
        """Scheduled items with due <= now, most overdue first (queue_key ascending).

        `now` is an ISO datetime; queue keys are DUE#<iso-datetime> so the
        lexicographic range bound is exact to the minute. An item reviewed in
        the morning legitimately reappears once its learning step matures.
        """
        resp = self._table.query(
            IndexName=GSI1,
            KeyConditionExpression=(
                Key("PK").eq(keys.pk(user_id, lang))
                & Key("queue_key").between(_DUE_FLOOR, keys.queue_key_due(now))
            ),
            Limit=limit,
        )
        return [Item.from_dynamo(r) for r in resp.get("Items", [])]

    def query_new_items(self, user_id: str, lang: str, limit: int) -> list[Item]:
        """Backlog items in drip order (NEW#<priority> ascending)."""
        resp = self._table.query(
            IndexName=GSI1,
            KeyConditionExpression=(
                Key("PK").eq(keys.pk(user_id, lang))
                & Key("queue_key").begins_with("NEW#")
            ),
            Limit=limit,
        )
        return [Item.from_dynamo(r) for r in resp.get("Items", [])]

    def count_due(self, user_id: str, lang: str, now: str) -> int:
        """Reviewable-now count: items with due <= now (ISO datetime)."""
        return self._count(
            Key("PK").eq(keys.pk(user_id, lang))
            & Key("queue_key").between(_DUE_FLOOR, keys.queue_key_due(now))
        )

    def count_reviewed_today(self, user_id: str, lang: str, today: str) -> int:
        """Distinct items whose latest review happened today (UTC date)."""
        return self._count(
            Key("PK").eq(keys.pk(user_id, lang)) & Key("queue_key").begins_with("DUE#"),
            filter_expression=Attr("last_review").begins_with(today),
        )

    def count_backlog(self, user_id: str, lang: str) -> int:
        return self._count(
            Key("PK").eq(keys.pk(user_id, lang)) & Key("queue_key").begins_with("NEW#")
        )

    def count_introduced_today(self, user_id: str, lang: str, today: str) -> int:
        """Items whose first-ever review happened today (UTC date), from the
        write-once first_review stamp. Feeds the new_per_day drip."""
        return self._count(
            Key("PK").eq(keys.pk(user_id, lang)) & Key("queue_key").begins_with("DUE#"),
            filter_expression=Attr("first_review").begins_with(today),
        )

    def query_leeches(self, user_id: str, lang: str) -> list[Item]:
        resp = self._table.query(
            IndexName=GSI1,
            KeyConditionExpression=(
                Key("PK").eq(keys.pk(user_id, lang)) & Key("queue_key").begins_with("DUE#")
            ),
            FilterExpression=Attr("lapses").gte(LEECH_LAPSES),
        )
        return [Item.from_dynamo(r) for r in resp.get("Items", [])]

    def _count(self, key_condition: Any, filter_expression: Any = None) -> int:
        kwargs: dict[str, Any] = {
            "IndexName": GSI1,
            "KeyConditionExpression": key_condition,
            "Select": "COUNT",
        }
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        total = 0
        while True:
            resp = self._table.query(**kwargs)
            total += resp["Count"]
            last = resp.get("LastEvaluatedKey")
            if not last:
                return total
            kwargs["ExclusiveStartKey"] = last

    # ---- review logs ----

    def put_log(self, user_id: str, lang: str, log: ReviewLog) -> None:
        self._table.put_item(Item=log.to_dynamo(keys.pk(user_id, lang)))

    def query_item_logs(
        self, user_id: str, lang: str, concept_id: str, facet: str, limit: int = 10
    ) -> list[ReviewLog]:
        """Most recent logs for one item, newest first (SK timestamps sort)."""
        resp = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(keys.pk(user_id, lang))
                & Key("SK").begins_with(f"LOG#{concept_id}#{facet}#")
            ),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [ReviewLog.from_dynamo(r) for r in resp.get("Items", [])]

    def iter_all_logs(self, user_id: str, lang: str) -> Iterator[ReviewLog]:
        """Every review log for the partition; get_progress aggregates over this."""
        for record in self._iter_sk_prefix(user_id, lang, "LOG#"):
            yield ReviewLog.from_dynamo(record)

    def iter_concepts(self, user_id: str, lang: str) -> Iterator[Concept]:
        """Every concept in the partition (main table, SK begins_with CONCEPT#).
        Used by get_progress for coverage stats; fine at ~1-2k concepts."""
        for record in self._iter_sk_prefix(user_id, lang, "CONCEPT#"):
            yield Concept.from_dynamo(record)

    def iter_items(self, user_id: str, lang: str) -> Iterator[Item]:
        for record in self._iter_sk_prefix(user_id, lang, "ITEM#"):
            yield Item.from_dynamo(record)

    def _iter_sk_prefix(
        self, user_id: str, lang: str, prefix: str
    ) -> Iterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (
                Key("PK").eq(keys.pk(user_id, lang)) & Key("SK").begins_with(prefix)
            )
        }
        while True:
            resp = self._table.query(**kwargs)
            yield from resp.get("Items", [])
            last = resp.get("LastEvaluatedKey")
            if not last:
                return
            kwargs["ExclusiveStartKey"] = last
