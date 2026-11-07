# Adaptive request intake (grill-me)

The existing `POST /api/ask` endpoint performs intake before calculating or
registering charts. Clear supported requests go directly through the existing
REUSE / EXTEND / ANSWER / BUILD engine. There is no extra mandatory critic call,
agent framework, workflow service or database.

## Interpretation and readiness

`backend/spec.py` requests one structured `Interpretation` from the existing
Gemini specification call. It contains a separate `RequestBrief`, an advisory
ASK / READY / UNSUPPORTED outcome, and a single-metric `ChartSpec`.

The brief retains original intent, business decision, audience, usage, every
requested metric, an accepted first metric, product/market/plant scope, explicit
global/region scope, period, comparison, actual/forecast policy, unresolved terms,
missing information, unsupported capabilities, questions and intake mode.
Unknown values are explicit. Questions have stable field identifiers; at most
two material questions are shown per turn.

`backend/intake.py` is the Python readiness gate. Model READY does not authorize
execution. It checks canonical metrics, identifiers, scope conflicts, unsupported
period/region/comparison/aggregation semantics and unresolved definitions. Invalid
IDs are retained and rejected instead of being removed to broaden the query.
Explicit global scope does not inherit a factory role's default plant filter.
Registered calculations, formulas and source identifiers are unchanged.

Ordinary numerical questions do not need a business-decision/audience interview
or an owner. Explicit new reports/dashboards raise the one-off-versus-recurring
question when unresolved; recurring new assets also need a business decision.
Grill mode explores business decision, usage and recurring audience more deeply.

All requested metrics survive clarification. Only a validated single metric is
executed. A multi-metric request stays pending until the user selects a first
metric/accepts a displayed metric alternative; a model's selected metric cannot
silently approve that narrowing. Budget variance is not forecast variance.

## Conversation state

The existing `conversations` document stores `pending_request`:

```text
original_request
brief                      accumulated RequestBrief
unresolved_questions       IDs, fields and current question text
latest_questions           questions most recently shown (at most two)
alternatives               explicit supported changes awaiting acceptance
draft_spec                 prior dimensions/specification context
```

Short replies such as "monthly, for the management team" continue the original
request. Known answers and the full metric list are retained. Unsupported time
semantics remain blockers until a proposed supported alternative is explicitly
accepted. A generic yes only accepts an alternative when exactly one is pending.
There is no turn counter that forces execution.

While blocked, the engine saves clarification turns but does not compute results,
register charts or increment chart usage. CLARIFY events still appear in the
existing request log/meter. Pending state is cleared after successful handling.
Interpretation/provider/schema failures return HTTP 503 with a localized retry
message and leave pending state untouched.

Use **New conversation** to abandon intake. The frontend sends an ordinary
`/api/ask` request with `abandon_pending=true`, the old `session_id`, and an empty
question before clearing its local state. Conversation history remains stored.
Switching language keeps the current session/pending state. Switching roles also
abandons the old pending request first.

Explicit prefixes such as `New request:`, `Instead`, `Start over`, `Uusi pyyntö`
or `Aloita alusta` replace the pending request without inheriting its scope. The
model cannot discard a pending brief by adding replacement metadata. Conversation
and explanation requests are handled by the LLM router before analytics interpretation;
completed-request follow-ups continue to use the existing interface.

## Commands

Automatic clarification is the default. Within the same endpoint/conversation:

- `/grill-me <request>` starts a fresh request in deeper discovery mode.
- Bare `/grill-me` invites the user to describe the need, without an LLM call.
- Grill mode persists until successful handling, explicit replacement or abandonment.

The command is parsed before interpretation; it is not a new HTTP route.

## Reuse evidence

Intake for a new persistent asset or grill request performs bounded read-only
metadata lookups in the existing chart registry and analytics catalog. Exact
metric, scope, dimensions and available policy metadata must agree before a
registry candidate is marked verified. Catalog candidates remain unverified when
their scope cannot be established. No additional embedding call is required.

The response distinguishes `verified`, `needs_verification`, `none`, `unavailable`
and `not_searched`. `search_failed` records partial failures. A failed search never
becomes a claim that no report exists; even `none` is explicitly a limited metadata
search, not an exhaustive estate audit. Recommendations name only retrieved IDs
and titles. Retrieved titles are rendered as text, not executable HTML.

## API compatibility and cache safety

Existing `decision`, `answer`, `reason`, `spec`, `session_id` and suggestion chips
remain. Clarification adds `brief` and an `intake` object with questions,
limitations, alternatives, reuse evidence, outcome, mode and `pending=true`.
Successful execution reports READY and `pending=false`. The frontend keeps ordinary
text entry and displays limitations/alternatives without another form framework.

Specification-cache identity includes language, model/prompt version, recent
history including answers, complete pending state and intake mode. Exact valid
cache hits remain usable. The older question/role-only outage fallback was removed
because it could apply a different language, scope or unresolved state. Invalid
structured cache/provider output cannot authorize execution. The specification
output budget is capped; pending state is not changed on a failed interpretation.

## Execution limitations

This feature does not implement a dashboard compiler, multi-chart generation,
Power BI/Tableau conversion, arbitrary date filtering, region expansion,
quarterly/yearly aggregation, forecast-only computation or custom comparisons.
Year-over-year growth is not implemented; absent prior-year history is reported
separately from implementation support. Snapshot metrics do not gain monthly
history. Users must explicitly accept a supported alternative rather than receive
a silently substituted result. Source/asset existence and a natural-language
business definition still need human review; this is not production governance.
Clients should serialize requests within one conversation, as the browser does;
this prototype does not add distributed locking for concurrent same-session turns.

## Verification

From the repository root in a separate test terminal:

```powershell
$env:N8N_WEBHOOK_URL = ''
& '.\.venv\Scripts\python.exe' -m pytest -q
node application/tests/frontend/preferences.test.cjs
```

`tests/backend/test_intake.py` uses workbook-seeded mongomock and mocked Gemini,
embeddings and registration calls. It covers direct execution, ambiguity, state
accumulation, explicit narrowing, invalid/global scope, limitations, cache identity,
outages, malformed responses, replacement, abandonment and reuse evidence states.
The Node suite checks language preservation and new-conversation behavior. These
checks do not call live services or verify visual browser layout.
