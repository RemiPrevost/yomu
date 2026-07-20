"""Auth phase 2: Cognito as OAuth 2.1 authorization server.

The MCP server is the OAuth *resource server*: it validates Cognito-issued
JWT access tokens (RS256, keys from the pool's JWKS endpoint) and exposes the
token's `sub` as the caller identity. The phase-1 static bearer token remains
accepted as a fallback so local dev and the MCP Inspector keep working
without a browser flow.
"""

import hmac
import os
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

STATIC_CLIENT_ID = "static-token"


def resolve_static_token() -> str | None:
    """Phase-1 bearer: AUTH_TOKEN env directly, or fetched once from SSM."""
    token = os.environ.get("AUTH_TOKEN")
    if not token and os.environ.get("AUTH_TOKEN_PARAM"):
        import boto3

        token = boto3.client("ssm").get_parameter(
            Name=os.environ["AUTH_TOKEN_PARAM"], WithDecryption=True
        )["Parameter"]["Value"]
    return token or None


class CognitoTokenVerifier(TokenVerifier):
    """Validates Cognito access tokens; also accepts the static fallback token.

    Cognito specifics: access tokens carry the app client in a `client_id`
    claim (not `aud`) and are marked `token_use: "access"` — ID tokens must
    not be accepted here.
    """

    def __init__(
        self,
        issuer: str,
        client_id: str,
        static_token: str | None = None,
        static_user_id: str = "u_001",
        jwks_client: Any = None,
    ):
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._static_token = static_token
        self._static_user_id = static_user_id
        # Lazy: the JWKS fetch must not run at import/cold-start time.
        self._jwks_client = jwks_client

    def _jwks(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(
                f"{self._issuer}/.well-known/jwks.json", cache_keys=True
            )
        return self._jwks_client

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._static_token and hmac.compare_digest(token, self._static_token):
            return AccessToken(
                token=token,
                client_id=STATIC_CLIENT_ID,
                scopes=[],
                subject=self._static_user_id,
            )

        try:
            signing_key = self._jwks().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                # Cognito access tokens have no aud claim; binding is checked
                # via the client_id claim below.
                options={"verify_aud": False},
            )
        except jwt.PyJWTError:
            return None

        if claims.get("token_use") != "access":
            return None
        if claims.get("client_id") != self._client_id:
            return None
        sub = claims.get("sub")
        if not sub:
            return None

        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=(claims.get("scope") or "").split(),
            expires_at=claims.get("exp"),
            subject=sub,
            claims=claims,
        )
