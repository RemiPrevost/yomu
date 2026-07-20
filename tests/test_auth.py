import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from yomu.auth import STATIC_CLIENT_ID, CognitoTokenVerifier

ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_TEST"
CLIENT_ID = "test-client-id"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwksClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=_PRIVATE_KEY.public_key())


def make_token(**overrides) -> str:
    claims = {
        "iss": ISSUER,
        "sub": "cognito-sub-1234",
        "client_id": CLIENT_ID,
        "token_use": "access",
        "scope": "openid email",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture
def verifier():
    return CognitoTokenVerifier(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        static_token="sekret",
        static_user_id="u_001",
        jwks_client=FakeJwksClient(),
    )


def verify(verifier, token):
    return asyncio.run(verifier.verify_token(token))


def test_valid_cognito_access_token(verifier):
    token = verify(verifier, make_token())
    assert token is not None
    assert token.subject == "cognito-sub-1234"
    assert token.client_id == CLIENT_ID
    assert "openid" in token.scopes


def test_static_token_fallback(verifier):
    token = verify(verifier, "sekret")
    assert token is not None
    assert token.subject == "u_001"
    assert token.client_id == STATIC_CLIENT_ID


def test_rejects_wrong_static_token_that_is_not_a_jwt(verifier):
    assert verify(verifier, "wrong") is None


def test_rejects_id_token(verifier):
    # Cognito ID tokens have token_use=id; only access tokens may pass.
    assert verify(verifier, make_token(token_use="id")) is None


def test_rejects_foreign_client(verifier):
    assert verify(verifier, make_token(client_id="other-app")) is None


def test_rejects_expired(verifier):
    assert verify(verifier, make_token(exp=int(time.time()) - 60)) is None


def test_rejects_wrong_issuer(verifier):
    assert verify(verifier, make_token(iss="https://evil.example.com")) is None


def test_rejects_missing_sub(verifier):
    assert verify(verifier, make_token(sub=None)) is None


def test_rejects_tampered_signature(verifier):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": ISSUER, "sub": "x", "client_id": CLIENT_ID, "token_use": "access",
         "exp": int(time.time()) + 3600},
        other_key,
        algorithm="RS256",
    )
    assert verify(verifier, forged) is None


def test_no_static_token_configured():
    verifier = CognitoTokenVerifier(
        issuer=ISSUER, client_id=CLIENT_ID, jwks_client=FakeJwksClient()
    )
    assert verify(verifier, "anything") is None
    assert verify(verifier, make_token()) is not None


def test_user_mapping_roundtrip(repo):
    assert repo.get_user_mapping("cognito-sub-1234") is None
    repo.put_user_mapping("cognito-sub-1234", "u_001")
    assert repo.get_user_mapping("cognito-sub-1234") == "u_001"
