"""DynamoDB table definition for local/test environments.

Mirrors the CDK stack (infra/stacks/language_memory_stack.py) — keep the two
in sync. Used by the test suite (moto) and scripts/dev_server.py; never called
in production, where CDK owns the table.
"""

from typing import Any

from yomu.repository import GSI1, GSI2


def create_table(dynamodb: Any, table_name: str) -> Any:
    return dynamodb.create_table(
        TableName=table_name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "queue_key", "AttributeType": "S"},
            {"AttributeName": "normalized", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI1,
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "queue_key", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "state",
                        "facet",
                        "due",
                        "reps",
                        "lapses",
                        "last_review",
                        "first_review",
                    ],
                },
            },
            {
                "IndexName": GSI2,
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "normalized", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": ["lemma", "pos", "meanings", "concept_id"],
                },
            },
        ],
    )
