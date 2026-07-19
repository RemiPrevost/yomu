import os

import boto3
import pytest
from moto import mock_aws

from yomu.repository import Repository
from yomu.service import LanguageMemoryService
from yomu.table_schema import create_table

TABLE_NAME = "language-memory-test"

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")


@pytest.fixture
def repo():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
        create_table(dynamodb, TABLE_NAME)
        yield Repository(TABLE_NAME, dynamodb)


@pytest.fixture
def service(repo):
    return LanguageMemoryService(repo, user_id="u_test")
