# Language Memory — Specification

A personal spaced-repetition memory service for LLM-driven language learning.
Claude clients (Claude.ai, Claude Desktop) connect via MCP, generate exercises,
and read/write review state. The server owns all scheduling logic (FSRS). Personal
project, single developer, a handful of users eventually.

## 1. Problem and division of labor

LLMs are excellent language tutors (exercise generation, evaluation, explanation)
but have no durable memory: they loop on the same exercises and cannot track what
was learned, failed, or never tested.

Division of labor (core architectural principle):

- **Server (this project)**: decides WHAT to review and WHEN. Runs FSRS. Owns all
  memory state. Deterministic, trusted bookkeeping.
- **LLM client**: decides HOW to test items. Generates varied exercises around the
  queue the server provides, evaluates answers, maps them to grades, reports
  results back. Never computes intervals or dates.

## 2. Stack (decided, do not revisit)

- **AWS, region eu-west-1**, personal account
- **DynamoDB**, single table, on-demand billing, point-in-time recovery ON
- **One Lambda** (Python 3.12+) serving MCP over streamable HTTP, stateless mode
- **Lambda Function URL** (no API Gateway for now)
- **FSRS via `py-fsrs`** (official library; never implement the math by hand)
- **MCP Python SDK** (FastMCP-style tool definitions)
- **CDK in Python** for all infrastructure
- **Auth phase 1**: static bearer token checked in the Lambda (env var / SSM).
  **Auth phase 2 (implemented 2026-07-20)**: Cognito user pool as OAuth 2.1
  authorization server (hosted UI, code + PKCE; client ID entered manually in
  claude.ai's connector settings). The server publishes its own RFC 8414
  authorization-server metadata pointing at the Cognito hosted UI, validates
  access-token JWTs (JWKS), and maps `sub` → internal user_id via USERMAP rows;
  the static token remains as a tooling/break-glass fallback.
- Seeding: one-off local Python script (JLPT N5 list, ~800 concepts), not infrastructure
- Estimated cost: < $1/month

## 3. Domain model

### Granularity: concept vs item

- A **concept** is the pedagogical unit (a word or grammar point). Carries display
  data. No FSRS state.
- An **item** is a reviewable facet of a concept. FSRS schedules items, not concepts.
- Facets at launch: `recognition` (target lang → native) and `production`
  (native → target lang) for vocab; single `grammar` facet for grammar points.
  Facet is an open enum (later: `kanji_reading`, `listening`).
- **Lazy production facet**: when a vocab concept is created, only the `recognition`
  item is created. The `production` item is created after the first successful
  recognition review (server-side rule in record_result).

### FSRS essentials

- Per-item memory state: stability (S, days for retrievability to fall to 90%),
  difficulty (D, 1–10). Retrievability R decays over time as a function of S.
- Grades: 1=Again, 2=Hard, 3=Good, 4=Easy.
- Next due = the datetime R is predicted to hit desired retention (default
  0.90, per-user profile setting). Scheduling is minute-granular: py-fsrs
  learning steps (1 min, 10 min) are kept as-is, so a new item reviewed in a
  morning session legitimately comes back in the afternoon one. (Revised
  2026-07-19; originally day-granular.)
- Item states: new / learning / review / relearning (py-fsrs native).
- New-item introduction is server-throttled: `new_per_day` (default 5), counted
  from logs so multiple sessions per day do not exceed the drip.

## 4. DynamoDB schema

Table: `language-memory`. Partition key shared by all entities:

```
PK = USER#<user_id>#LANG#<lang>        e.g. USER#u_001#LANG#ja
```

user_id is an opaque stable ID from day one (e.g. u_001), NOT a name, so the
Cognito migration is a mapping. lang is ISO 639-1.

### Concept — SK = CONCEPT#<concept_id>

| field | notes |
|---|---|
| concept_id | deterministic: first 12 hex of SHA-256(normalized + pos + lang). If confirm_distinct (homophone case): salt with lemma. |
| type | vocab \| grammar \| kanji (kanji unused at launch) |
| lemma | display/dictionary form, e.g. 食べる, or pattern 〜てもいいです for grammar |
| normalized | dedup key, GSI2 sort key. JA: kana of dictionary form, NFKC. Other langs: lowercased lemma. Computed SERVER-SIDE, never trusted from the LLM. |
| reading | kana reading (human-facing; null for non-JA and grammar) |
| meanings | list of strings in user's ui_lang |
| pos | controlled vocab: verb-ichidan, verb-godan, noun, adj-i, adj-na, adverb, particle, expression, ... |
| level | N5..N1 \| none |
| examples | list of {target, native, source}; capped at 5 most recent (400KB item limit + context economy). Keys are GENERIC target/native, not ja/fr. |
| source | seed \| claude |
| priority | int; drip order while never introduced (seed: list order; claude-added: low number = soon). Inert after introduction. |
| created_at | ISO timestamp |

### Item — SK = ITEM#<concept_id>#<facet>

Skinny: FSRS state machine only. Display data comes from the concept
(BatchGetItem join in code).

| field | notes |
|---|---|
| facet | recognition \| production \| grammar |
| state | new \| learning \| review \| relearning |
| stability, difficulty | floats, null until first review. ONLY the server writes these, via py-fsrs. |
| due | ISO datetime UTC (minute granularity). Unset for state=new. |
| last_review | ISO datetime (FSRS input: elapsed time) |
| first_review | ISO datetime, written once at the first-ever review; drives the daily drip count |
| reps, lapses | lifetime counters. lapses >= 4 → leech signal surfaced in queue payload. |
| queue_key | GSI1 sort key, maintained on every write: `DUE#<iso-datetime>` for scheduled items (ISO sorts lexicographically), `NEW#<priority zero-padded to 5>#<concept_id>` for backlog items. Reviewing a new item rewrites NEW#→DUE#. |

### ReviewLog — SK = LOG#<concept_id>#<facet>#<iso_timestamp>

Append-only, never updated. Ground truth; Item is a projection of it.

| field | notes |
|---|---|
| grade | 1–4 |
| state_before | {stability, difficulty} |
| state_after | {stability, difficulty, due} |
| context | {exercise_type, sentence, user_answer, note} — all optional, LLM-provided, truncated server-side (~300 chars/field) |
| duplicate | bool flag: graded before the item was due again (LLM retry or ahead-of-schedule re-test) → logged but did not drive FSRS |

Snapshots make the system re-schedulable (replay logs when FSRS parameters
improve, or fit personal parameters after ~1000 reviews).

### Profile — SK = PROFILE

| field | default |
|---|---|
| desired_retention | 0.90 |
| new_per_day | 5 |
| ui_lang | fr |

### GSI1 — queue index (sparse: Items only)

PK = table PK, SK = queue_key. Projection: keys + state, facet, due, reps, lapses,
last_review, first_review.

- Due query: `queue_key BETWEEN "DUE#0000-00-00" AND "DUE#<now-iso-datetime>"` → overdue-first
- Backlog query: `begins_with(queue_key, "NEW#") LIMIT n` → drip order
- Drip count: `begins_with(queue_key, "DUE#")` filtered on `begins_with(first_review, <today>)`

### GSI2 — dedup index (sparse: Concepts only)

PK = table PK, SK = normalized. Projection: keys + lemma, pos, meanings, concept_id.
Queried by add_items before any concept write.

## 5. MCP tool contract (4 tools, no more)

Design rules: server owns all scheduling; responses carry enough display data
that the LLM never needs a second call to build a lesson; errors are structured,
actionable, and never fail a whole batch; grading rubric lives in the tool
DESCRIPTION in the MCP schema (auto-distributed to every client).

Grading rubric (put verbatim in record_result description). Grades the
QUALITY OF PRODUCTION, not just final correctness — correct meaning is
necessary for 3/4 but not sufficient:
- 1 Again: could not produce / wrong meaning.
- 2 Hard: meaning right BUT hesitation / self-correction / hint needed / a
  written-form slip (kana where kanji expected, okurigana, conjugation,
  particle, misspelling, missing accent) — grade 2 even if ultimately correct.
- 3 Good: correct AND clean — first try, no hesitation, hint, or slip.
- 4 Easy: instant, effortless, or used spontaneously (use sparingly).
When unsure between two grades, pick the lower one. One exercise can test
several items → grade PER ITEM, not per exercise. (Rubric tightened 2026-07-23
after observing systematic over-grading — the model rewarded correct substance
and rationalised away hesitation/kana slips that the rubric assigns to Hard.)

### get_review_queue

Request: `{lang, max_due?, max_new?}`. Server clamps to ceilings and to the
remaining daily drip (new_per_day minus already introduced today, from logs).

Response:
```json
{
  "session_date": "2026-07-19",
  "due": [{
    "item_id": "a3f9e1#production",
    "facet": "production",
    "concept": {"type","lemma","reading","meanings","pos","examples"},
    "memory": {
      "days_overdue": 0, "reps": 6, "lapses": 2, "last_grade": 2,
      "is_leech": false, "recent_failures_context": ["listening"]
    }
  }],
  "new":  [{ "item_id", "facet", "concept": {...} }],
  "stats": {"total_review": 148, "total_backlog": 652, "streak_days": 4},
  "guidance": "server-composed natural-language hints (rule-based)"
}
```

Key decisions:
- `memory` exposes DERIVED signals (days_overdue, is_leech,
  recent_failures_context = distinct exercise_types of recent failed logs).
  Raw stability/difficulty floats are NOT exposed to the LLM.
- `guidance` is generated from simple server rules (leech → suggest mnemonic
  work; heavy overdue backlog → suggest skipping new items; facet failure
  patterns → suggest exercise types).

### record_result

Request (batched):
```json
{"lang": "ja", "results": [{
  "item_id": "a3f9e1#production",
  "grade": 1,
  "context": {"exercise_type","sentence","user_answer","note"}
}]}
```

Response:
```json
{
  "recorded": [{"item_id","next_due","state"}],
  "rejected": [{"item_id","reason"}],
  "session_summary": {"reviewed_today","remaining_due","new_introduced_today"}
}
```

Server rules:
- Unknown item_id → rejected entry with reason; rest of batch proceeds.
- Grade recorded BEFORE the item is due again (now < due) → accepted, logged
  with duplicate=true, does NOT drive FSRS. Covers LLM retries and
  ahead-of-schedule re-tests; loop-proof because every FSRS-driving review
  pushes due into the future, and the queue never serves an item early.
- On first successful recognition review of a vocab concept → create the
  production item (lazy facet rule).
- next_due returned for pedagogy ("on la reverra demain") but is not writable.

### add_items

Request:
```json
{"lang": "ja", "concepts": [{
  "type","lemma","reading","meanings","pos",
  "example": {"target","native"}, "level",
  "confirm_distinct": false
}]}
```

Server computes normalized from reading (JA) or lemma (others). Three outcomes
per concept:

```json
{
  "created": [{"concept_id","lemma","facets_created":["recognition"],"note"}],
  "merged":  [{"concept_id","lemma","your_input","action":"example appended"}],
  "needs_confirmation": [{
    "your_input": {...}, "existing": {...},
    "reason": "same reading and pos, different lemma",
    "how_to_resolve": "retry with confirm_distinct: true"
  }]
}
```

- Exact lemma match on GSI2 hit → merged silently (append example, capped at 5).
- Same normalized+pos but DIFFERENT lemma (homophones: 橋/箸 both はし) →
  needs_confirmation. Retry with confirm_distinct → create with lemma-salted ID.
- New concepts get source=claude, priority = low number (introduced soon).

### get_progress

Request: `{lang, period_days}`. Returns aggregates from logs: reviews/day,
success rate by facet and by exercise_type, leech list, backlog burn-down,
N5 coverage %. Read-only, one Query over LOG# rows.

### Deliberately absent tools

NO update_concept, delete_item, set_due_date, update_profile. LLM write access
to scheduling/content mutation is an invitation to corrupt state. Corrections
happen via a small admin script. Tools can be added later; they cannot easily
be un-taught to connected clients.

## 6. Implementation order

1. CDK skeleton: table + 2 GSIs + Lambda + Function URL + IAM + PITR
2. FSRS service layer (`py-fsrs`) with unit tests on state transitions,
   queue_key maintenance, lazy production facet, duplicate-grade idempotency,
   drip counting
3. Repository layer: the two GSI queries + BatchGetItem join + conditional
   writes for dedup
4. MCP layer (Python SDK, streamable HTTP, stateless) exposing the 4 tools,
   bearer-token check
5. N5 seed script (local, batch-write ~800 concepts with priority from
   frequency order; jmdict-derived list)
6. Connect as custom connector in Claude.ai, iterate on tool descriptions
   and the guidance rules based on real lessons

## 7. Deferred decisions (recorded, not forgotten)

- Cognito OAuth for multi-user (phase 2); user_id mapping prepared
- kanji type and additional facets (kanji_reading, listening)
- Personal FSRS parameter fitting once ~1000 reviews are logged
- Whether Easy (grade 4) is exposed to the LLM at all, or collapsed to 3 grades
- get_progress UI beyond chat (a web page, someday, maybe never)

## 8. Conventions

- All timestamps ISO 8601 UTC, including `due` (minute-granular scheduling);
  "today" boundaries (drip, streak) are UTC days
- Example objects use generic keys {target, native}, never language codes
- ui_lang for meanings and user-facing strings: French (per profile)
- Code, comments, commits: English
