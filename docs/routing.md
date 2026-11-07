# Semantic input routing

`POST /api/ask` now has two stages before existing analytics interpretation:

1. `backend/router.py` sends a short, separate classification prompt to
   `ROUTER_MODEL` (default `gemma-4-26b-a4b-it`) with `thinking_level="minimal"`.
   The message, four brief history turns, pending analytics, latest questions and
   bounded unresolved routing context are supplied as untrusted JSON data.
2. `backend/routing.py` validates the classification and chooses a Python branch.
   Neither the classifier nor its free-text ambiguity reason can execute anything.
   If clarification is needed, the classifier also generates one question and
   two or three answers in the same validated response; see
   [generated clarification](clarification-suggestions.md).

The classifier uses the same complete-JSON/code-fence parser as analytics, with
its own strict Pydantic schema, also supplied in the prompt for Gemma. Extra keys, unknown intents/actions, coerced
booleans and inconsistent action/clarification combinations fail closed. A failed
classification makes no conversation, pending-state, registry or counter writes.
Classification makes at most two provider attempts. A transport failure or HTTP
408/500/502/503/504 allows one retry after 0.5 seconds. Each request has an
HTTP timeout controlled by `ROUTER_TIMEOUT_SECONDS` (default 30 seconds, allowed
1–120); SDK retries are disabled to avoid multiplying attempts. The SDK also
sends this timeout as an `X-Server-Timeout` provider deadline. Validation
errors, authentication/configuration errors and quota errors are not retried.
There is no fallback to analytics if classification still fails, and no pending
state/action/counter writes occur between attempts.

| Intent | Python behavior |
| --- | --- |
| `ui_action` | Only `open_briefing` is allowed. Fetch the selected role's current briefing; return cards to Vue, replace the displayed briefing and scroll to it. No metric required. |
| `analytics_request`, `clarification_reply` | Continue the existing analytics engine with original pending constraints. Metric, identifiers, scope, period and implementation checks still precede computation. A clarification without context asks for context. |
| `conversation` | App-owned English/Finnish capability guidance and outstanding questions, without altering pending analytics. |
| `explain_previous` | Repeat the recorded answer and available user-facing decision explanation; do not fabricate causal claims or calculate new values. Missing previous evidence is stated explicitly. |
| `ambiguous`, `mixed` | Ask the classifier-generated clarification with its generated answers; store every unresolved message separately from pending analytics. Subsequent analytics receives the complete unresolved text. |

Opening a briefing and conversational turns preserve both pending analytics and
unresolved routing. Analytics saves or explicit abandonment clear routing context
only after the existing workflow succeeds. Mixed requests never partially execute.
All original messages remain in conversation history. The classifier's internal
fields and ambiguity reason are not rendered as user-facing messages.
Unresolved routing messages are passed to analytics as internal request context;
the current user bubble and stored conversation turn contain only the actual
current message, without repeating earlier messages inside it.

`ROUTER_MODEL` must support the Gemini API and `thinking_level="minimal"`.
The generation model remains separately configurable through `GEMINI_MODEL`.
The router adds no new dependency. Conversation responses intentionally use
recorded evidence and app-owned wording rather than another free-form LLM call.

## Verification

Offline tests use a fake classifier for existing analytics regression tests;
dedicated routing tests exercise strict schema validation, real in-memory
briefing data, state preservation, provider failures and dispatch. The frontend
test executes the actual Vue methods and checks that returned cards replace
stale cards and receive focus; it is not a rendered-browser visual test.

Classifier logs contain intent/timing or exception type/timing, never input
text, pending state or raw provider messages. Schema failures log bounded error
types; clarification failures log fixed reason codes and rejection counts (for
example `missing_changes` or `unsupported_identifier`). These diagnostics never
include rejected values, labels, error messages or untrusted field names.
Both classification and dispatch validate against the original pending request,
including unresolved routing context, rather than treating a country-selection
reply as a new original request. Dispatch uses one supported-value snapshot and
converts validation failures to 503 before writing state or executing actions.
Classification belongs exclusively
to the LLM router; the analytics interpreter handles only analytics specifications
and clarification answers. Python validates scope and implementation support
before any computation.
