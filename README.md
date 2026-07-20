# Yomu — Language Memory

A personal spaced-repetition memory service for LLM-driven language learning.
LLM clients (Claude.ai, Claude Desktop) connect via MCP, generate exercises, and
read/write review state. The server owns all scheduling (FSRS via `py-fsrs`).

Full design: [SPEC.md](SPEC.md).

## Layout

```
src/yomu/
  ids.py            normalization (NFKC, katakana→hiragana) + deterministic concept IDs
  keys.py           single-table key builders (PK/SK/queue_key/item_id)
  models.py         Concept / Item / ReviewLog / Profile + DynamoDB (de)serialization
  fsrs_service.py   the only module touching py-fsrs (fuzzing disabled → replayable logs)
  repository.py     DynamoDB access: GSI queries, BatchGetItem join, conditional writes
  service.py        the 4 tool operations (queue, record, add, progress)
  guidance.py       rule-based hints composed into the queue response
  server.py         FastMCP (stateless streamable HTTP) + bearer auth + Lambda wiring
  lambda_handler.py Lambda entrypoint
infra/              CDK app (table + 2 GSIs + Lambda + Function URL)
scripts/            build_lambda.sh, seed_n5.py
tests/              pytest + moto
```

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

### Local environment

One command spins up an in-memory DynamoDB (moto), creates the table, seeds
the first N5 words, and serves the MCP endpoint — no AWS account involved:

```sh
.venv/bin/python scripts/dev_server.py            # 30 seeded words
.venv/bin/python scripts/dev_server.py --seed 0   # empty table
```

Endpoint `http://localhost:8000/mcp`, header `Authorization: Bearer dev`.
Data is lost when the process exits. Inspect interactively with
`npx @modelcontextprotocol/inspector` (transport "Streamable HTTP").

To point the server at a real table instead, set `TABLE_NAME`/`AUTH_TOKEN`
(and optionally `DYNAMODB_ENDPOINT` for dynamodb-local) and run:

```sh
TABLE_NAME=language-memory AUTH_TOKEN=dev .venv/bin/python -c \
  "import uvicorn; from yomu.server import build_app; uvicorn.run(build_app(), port=8000)"
```

## Deploy

One-time: create the bearer token parameter, then bootstrap CDK if needed.

```sh
aws ssm put-parameter --region eu-west-1 --name /yomu/auth-token \
    --type SecureString --value "$(openssl rand -hex 32)"
```

Every deploy:

```sh
./scripts/build_lambda.sh
cd infra && npx aws-cdk@2 deploy
```

The stack outputs `McpEndpoint` — the URL to give to MCP clients.

## Seed (JLPT N5)

```sh
.venv/bin/python scripts/seed_n5.py --dry-run   # inspect first
.venv/bin/python scripts/seed_n5.py             # writes ~717 concepts + items
```

Downloads the N5 list (elzup/jlpt-word-list) and jmdict-fre (French glosses,
POS) on first run, cached under `data/seed-cache/`.

## Auth

Two paths, both active:
- **OAuth (Cognito)** — the real one. The server is an OAuth 2.1 resource
  server; Cognito (user pool `yomu-users`) is the authorization server. The
  token's `sub` is mapped to the internal user_id via a `USERMAP#<sub>` row
  (`scripts/link_user.py`). Users are created by hand:
  ```sh
  aws cognito-idp admin-create-user --user-pool-id <UserPoolId> \
      --username <email> --user-attributes Name=email,Value=<email> Name=email_verified,Value=true
  python scripts/link_user.py <sub> <internal-user-id>
  ```
- **Static bearer** (`/yomu/auth-token` SSM param) — kept as a break-glass and
  tooling fallback; maps to the `USER_ID` env user.

## Connect from Claude.ai

Settings → Connectors → Add custom connector:
- URL: the `McpEndpoint` stack output
- Advanced settings → OAuth Client ID: the `OAuthClientId` stack output
  (no client secret — public client with PKCE, so the client ID is entered
  manually)

First connection opens the Cognito hosted UI: sign in with the invitation
password from email, set a permanent one, done.

Claude Desktop / MCP Inspector work the same way (their localhost OAuth
callbacks are pre-registered on the app client), or with the static bearer.
