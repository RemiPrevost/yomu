"""MCP server: 4 tools over streamable HTTP (stateless), behind a bearer token.

Runs on Lambda via a Function URL (mangum adapter). Tool descriptions are part
of the product: they are auto-distributed to every connected LLM client and
carry the grading rubric and usage rules.
"""

import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from yomu.repository import Repository
from yomu.service import LanguageMemoryService

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
    # DNS-rebinding protection is for localhost servers; behind a public
    # Function URL the bearer token is the access control, and the Host
    # header is not known until the URL is created.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_service_instance: LanguageMemoryService | None = None


def _service() -> LanguageMemoryService:
    global _service_instance
    if _service_instance is None:
        _service_instance = LanguageMemoryService(
            Repository(os.environ["TABLE_NAME"]),
            user_id=os.environ.get("USER_ID", "u_001"),
        )
    return _service_instance


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


# ---- HTTP wiring (bearer auth + Lambda adapter) ----


class BearerAuthMiddleware:
    """Rejects any request whose Authorization header does not match the
    static token (auth phase 1; Cognito OAuth comes later)."""

    def __init__(self, app: Any):
        self._app = app
        self._token: str | None = None

    def _expected(self) -> str:
        if self._token is None:
            token = os.environ.get("AUTH_TOKEN")
            if not token and os.environ.get("AUTH_TOKEN_PARAM"):
                import boto3

                ssm = boto3.client("ssm")
                token = ssm.get_parameter(
                    Name=os.environ["AUTH_TOKEN_PARAM"], WithDecryption=True
                )["Parameter"]["Value"]
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


def build_app() -> Any:
    """ASGI app with a working lifespan — use this for local serving (uvicorn)."""
    return BearerAuthMiddleware(mcp.streamable_http_app())


def build_handler() -> Any:
    from mangum import Mangum

    app = BearerAuthMiddleware(LambdaSessionManagerStarter(mcp.streamable_http_app(), mcp))
    return Mangum(app, lifespan="off")
