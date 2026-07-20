"""MCP server: 4 tools over streamable HTTP (stateless).

Auth: with COGNITO_ISSUER set, the server is an OAuth 2.1 resource server —
Cognito JWTs are validated and the token's `sub` selects the user (mapped
through USERMAP rows). Without it (local dev), a static bearer token guards
everything and the user comes from the USER_ID env var.

Runs on Lambda via a Function URL (mangum adapter). Tool descriptions are part
of the product: they are auto-distributed to every connected LLM client and
carry the grading rubric and usage rules.
"""

import os
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from yomu.auth import CognitoTokenVerifier, resolve_static_token
from yomu.repository import Repository
from yomu.service import LanguageMemoryService

COGNITO_ISSUER = os.environ.get("COGNITO_ISSUER")


def _public_origin() -> str:
    """Origin of the public MCP URL, e.g. https://xxx.lambda-url...on.aws"""
    from urllib.parse import urlsplit

    parts = urlsplit(os.environ["MCP_PUBLIC_URL"])
    return f"{parts.scheme}://{parts.netloc}"


def _auth_config() -> tuple[AuthSettings | None, CognitoTokenVerifier | None]:
    if not COGNITO_ISSUER:
        return None, None
    verifier = CognitoTokenVerifier(
        issuer=COGNITO_ISSUER,
        client_id=os.environ["COGNITO_CLIENT_ID"],
        # Phase-1 static token stays valid as a break-glass / tooling path.
        static_token=resolve_static_token(),
        static_user_id=os.environ.get("USER_ID", "u_001"),
    )
    # The advertised authorization server is THIS server, not Cognito:
    # Cognito publishes no RFC 8414 metadata and its OIDC document neither
    # advertises PKCE (code_challenge_methods_supported) nor public-client
    # token auth ("none"), so MCP clients abort before redirecting. We serve
    # a compliant metadata document ourselves (routes below) whose endpoints
    # point at the Cognito hosted UI.
    settings = AuthSettings(
        issuer_url=_public_origin(),
        resource_server_url=os.environ["MCP_PUBLIC_URL"],
        required_scopes=None,
    )
    return settings, verifier


_auth_settings, _token_verifier = _auth_config()

mcp = FastMCP(
    "language-memory",
    instructions=(
        "Personal spaced-repetition memory for language learning. The server decides "
        "WHAT to review and WHEN (FSRS scheduling); you decide HOW to test each item: "
        "generate varied exercises around the queue, evaluate the user's answers, and "
        "report one grade per item with record_result. Never compute intervals or due "
        "dates yourself. When the user encounters a new word or grammar point worth "
        "remembering, save it with add_items."
    ),
    stateless_http=True,
    json_response=True,
    auth=_auth_settings,
    token_verifier=_token_verifier,
    # DNS-rebinding protection is for localhost servers; behind a public
    # Function URL the bearer/OAuth token is the access control, and the Host
    # header is not known until the URL is created.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

if COGNITO_ISSUER:
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    def _as_metadata() -> dict[str, Any]:
        """RFC 8414 authorization-server metadata, proxied for Cognito.

        issuer must match the AuthSettings issuer_url as serialized into the
        protected-resource metadata (pydantic's AnyHttpUrl appends a trailing
        slash to origin-only URLs), or strict clients reject the document.
        """
        hosted = os.environ["COGNITO_HOSTED_DOMAIN"].rstrip("/")
        return {
            "issuer": str(mcp.settings.auth.issuer_url),
            "authorization_endpoint": f"{hosted}/oauth2/authorize",
            "token_endpoint": f"{hosted}/oauth2/token",
            "userinfo_endpoint": f"{hosted}/oauth2/userInfo",
            "revocation_endpoint": f"{hosted}/oauth2/revoke",
            "jwks_uri": f"{COGNITO_ISSUER}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["openid", "email", "profile"],
        }

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def oauth_authorization_server(request: Request) -> JSONResponse:
        return JSONResponse(_as_metadata())

    # Fallback for clients that try OIDC discovery instead of RFC 8414.
    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
    async def openid_configuration(request: Request) -> JSONResponse:
        return JSONResponse(_as_metadata())


_repo_instance: Repository | None = None
_user_id_cache: dict[str, str] = {}


def _repo() -> Repository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = Repository(os.environ["TABLE_NAME"])
    return _repo_instance


def _service() -> LanguageMemoryService:
    """Service bound to the caller's identity.

    OAuth path: identity is the verified token's subject (Cognito sub or the
    static-token user), mapped through USERMAP so pre-Cognito data is reachable.
    Legacy path (no Cognito configured): USER_ID env var.
    """
    token = get_access_token()
    external = token.subject if token and token.subject else os.environ.get("USER_ID", "u_001")
    if external not in _user_id_cache:
        _user_id_cache[external] = _repo().get_user_mapping(external) or external
    return LanguageMemoryService(_repo(), _user_id_cache[external])


class ReviewResult(BaseModel):
    item_id: str = Field(description="Item identifier exactly as given by get_review_queue")
    grade: int = Field(ge=1, le=4, description="1=Again, 2=Hard, 3=Good, 4=Easy")
    context: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional exercise context: exercise_type (e.g. translation, cloze, "
            "listening, free_production), sentence, user_answer, note"
        ),
    )


class ExampleInput(BaseModel):
    target: str = Field(description="Example sentence in the target language")
    native: str = Field(description="Its translation in the user's language")


class ConceptInput(BaseModel):
    type: str = Field(description="'vocab' or 'grammar'")
    lemma: str = Field(
        description="Dictionary form (e.g. 食べる) or grammar pattern (e.g. 〜てもいいです)"
    )
    reading: str | None = Field(default=None, description="Kana reading (Japanese vocab only)")
    meanings: list[str] = Field(description="Meanings in the user's language (French)")
    pos: str | None = Field(
        default=None,
        description=(
            "Part of speech: verb-ichidan, verb-godan, verb-irregular, noun, adj-i, "
            "adj-na, adverb, particle, pronoun, counter, conjunction, interjection, "
            "prenominal, expression. Omit for grammar points."
        ),
    )
    example: ExampleInput | None = Field(default=None, description="One example sentence")
    level: str | None = Field(default=None, description="JLPT level N5..N1, if known")
    confirm_distinct: bool = Field(
        default=False,
        description="Set true only to resolve a needs_confirmation homophone conflict",
    )


@mcp.tool()
def get_review_queue(
    lang: Annotated[str, Field(description="ISO 639-1 language code, e.g. 'ja'")],
    max_due: Annotated[
        int | None, Field(description="Max due items to return (server caps at 50, default 20)")
    ] = None,
    max_new: Annotated[
        int | None,
        Field(description="Max new items to introduce (server caps to the remaining daily budget)"),
    ] = None,
) -> dict[str, Any]:
    """Start of every review session: returns what to review now.

    `due` items are scheduled reviews, overdue first, with memory signals
    (days_overdue, lapses, is_leech, recent failure patterns) to help you pick
    exercise types. `new` items are never-seen items to introduce, already
    throttled by the user's daily budget — do not ration them further.
    Each entry carries full display data; you never need another call to build
    a lesson. Follow the `guidance` hints when composing the session.

    `stats` also reports read-only context: the user's `settings`
    (new_per_day, desired_retention, ui_lang) and today's drip usage
    (new_introduced_today, new_remaining_today) — use these to explain state
    to the user. They are not changeable through any tool; the server owns
    scheduling, and limit changes are done by the administrator.
    """
    return _service().get_review_queue(lang, max_due=max_due, max_new=max_new)


@mcp.tool()
def record_result(
    lang: Annotated[str, Field(description="ISO 639-1 language code, e.g. 'ja'")],
    results: Annotated[list[ReviewResult], Field(description="One entry per item tested")],
) -> dict[str, Any]:
    """Report review outcomes so the server can reschedule each item (FSRS).

    Grading rubric:
    - 1 Again: could not produce / wrong meaning
    - 2 Hard: produced with hesitation, hint, or minor slip (kana/conjugation)
    - 3 Good: correct
    - 4 Easy: instant, effortless, or used spontaneously (use sparingly)
    One exercise can test several items → grade PER ITEM, not per exercise.

    Call this after each exercise or small batch — do not wait for the end of
    the session. Unknown items are rejected individually; the rest of the
    batch still succeeds. A grade recorded before an item is due again (a
    retry, or re-testing ahead of schedule) is logged but does not reschedule,
    so retries are safe. `next_due` is returned for pedagogy ("we'll see this
    one again in 10 minutes / tomorrow") — it is not writable. Newly learned
    items come back within minutes: if the session is still open when they
    are due, fetch the queue again and re-test them.

    Grade ONLY items that get_review_queue served this session. Grading a
    backlog item the queue did not serve introduces it immediately and
    consumes the daily new-item budget (the response notes it) — do this only
    if the user explicitly asks for extra material. If the session ends
    before every served item was tested, report the untested ones as skipped,
    never as learned.
    """
    return _service().record_result(lang, [r.model_dump() for r in results])


@mcp.tool()
def add_items(
    lang: Annotated[str, Field(description="ISO 639-1 language code, e.g. 'ja'")],
    concepts: Annotated[list[ConceptInput], Field(description="Concepts to save")],
) -> dict[str, Any]:
    """Save new vocab or grammar the user just encountered, so it enters the
    review rotation.

    The server dedupes against existing concepts (an exact match merges
    silently, appending your example). If you get a `needs_confirmation` entry
    it is a homophone conflict: check with the user whether it is really a
    distinct word, then retry that concept with confirm_distinct: true.
    Meanings must be in the user's language (French). For Japanese vocab,
    always provide the kana reading.
    """
    return _service().add_items(lang, [c.model_dump() for c in concepts])


@mcp.tool()
def get_progress(
    lang: Annotated[str, Field(description="ISO 639-1 language code, e.g. 'ja'")],
    period_days: Annotated[int, Field(ge=1, le=365, description="Reporting window in days")] = 30,
) -> dict[str, Any]:
    """Progress report over the recent period: reviews per day, success rates
    by facet and exercise type, leech list, backlog burn-down, JLPT N5
    coverage, and current streak. Use it when the user asks how they are doing
    or to decide what to focus on."""
    return _service().get_progress(lang, period_days=period_days)


# ---- HTTP wiring (auth + Lambda adapter) ----


class BearerAuthMiddleware:
    """Legacy phase-1 gate: rejects any request whose Authorization header
    does not match the static token. Only used when Cognito is NOT
    configured — with Cognito, the MCP SDK's auth middleware (JWT
    verification + protected-resource metadata routes) takes over."""

    def __init__(self, app: Any):
        self._app = app
        self._token: str | None = None

    def _expected(self) -> str:
        if self._token is None:
            token = resolve_static_token()
            if not token:
                raise RuntimeError("no AUTH_TOKEN or AUTH_TOKEN_PARAM configured")
            self._token = token
        return self._token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization") != f"Bearer {self._expected()}":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error": "unauthorized"}',
                    }
                )
                return
        await self._app(scope, receive, send)


class LambdaSessionManagerStarter:
    """Starts the MCP session manager once per Lambda container.

    Mangum cycles the ASGI lifespan around every invocation, but the SDK's
    StreamableHTTPSessionManager can only run() once per instance — so we
    bypass the lifespan entirely (Mangum lifespan="off") and enter run() on
    first request. Mangum keeps a single event loop for the container's
    lifetime, so the manager's task group survives across invocations;
    Lambda containers are frozen and killed, never gracefully shut down,
    so run() is deliberately never exited. Lambda runs one request at a
    time per container, hence no locking.
    """

    def __init__(self, app: Any, server: FastMCP):
        self._app = app
        self._server = server
        self._run_ctx: Any = None  # keep the context alive or GC tears it down

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if self._run_ctx is None:
            self._run_ctx = self._server.session_manager.run()
            await self._run_ctx.__aenter__()
        await self._app(scope, receive, send)


def _wrap_auth(app: Any) -> Any:
    # Cognito mode: the SDK app already carries auth middleware + the
    # /.well-known/oauth-protected-resource route; wrapping it in the static
    # gate would 401 valid OAuth traffic.
    return app if COGNITO_ISSUER else BearerAuthMiddleware(app)


def build_app() -> Any:
    """ASGI app with a working lifespan — use this for local serving (uvicorn)."""
    return _wrap_auth(mcp.streamable_http_app())


def build_handler() -> Any:
    from mangum import Mangum

    app = _wrap_auth(LambdaSessionManagerStarter(mcp.streamable_http_app(), mcp))
    return Mangum(app, lifespan="off")
