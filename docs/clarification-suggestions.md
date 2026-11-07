# Generated clarification workflow

Every `/api/ask` message first goes through the LLM classifier. When it needs
clarification, the same classifier response contains one natural-language question
and two or three contextual answers. The question and answers are generated
together, in the selected language. There are no starter-question lists, preset
answer catalogues, or canned briefing-card questions.

The JSON contains a `clarification` object with `question` (`id`, `field`, `text`)
and `suggestions` (`label`, `answer`, private `changes`). Python attaches every
nested answer to its parent question; the model need not duplicate question IDs.
The public API exposes only `question_id`, `label` and `answer` for each choice.
Metric IDs remain in private metadata; localized metric names are supplied to the
model for visible text.

Python validates the complete response with Pydantic before updating any state:

- Exactly one question and two or three non-empty answers.
- References belong to the current question; invalid/stale references cannot apply.
- Proposed changes match the question's subject.
- Metric and scope identifiers exist in the current supported data.
- A market-only question cannot clear product or plant filters.
- An explicit requested metric cannot be replaced by an unrelated suggestion.
- Internal schema names do not appear in visible questions or answers.

The model proposes structured changes; it never executes them. Clicking a choice
submits its generated answer through `/api/ask` using the same session, role and
language. Python recognizes the current validated choice and applies only its
permitted changes. All other scope, time, actual/forecast and implementation
constraints still pass the existing readiness gate before computation. An explicit
metric choice resolves its corresponding metric/definition questions, including
old unresolved wording, while unrelated unsupported capabilities remain blocked.

Classifier clarifications are stored with unresolved routing context without
changing pending analytics or counters. Original and current user messages are
kept separate in the display and conversation history. If Python later discovers
additional analytics requirements, the same classifier model writes the next
question and two or three answers using those final requirements as context.
This optional generation call has one attempt, at most 1200 output tokens and a
10-20 second provider deadline. On failure the required clarification remains
available without fabricated suggestions. Classifier failures execute nothing and
leave pending state unchanged.

Vue shows generated choices below the input only for the latest active question.
Labels use text interpolation. Typing, submission, language change, completion,
and abandonment clear stale choices. No static examples or card-to-chat prompts
are displayed as fallback. Manual text entry remains available.

Offline tests cover the API workflow, natural generated wording, matching parent
question IDs, the two-or-three count, provider failures, scope preservation,
unsupported requirements, resolving metric choices, stale choices and click
submission. UI tests execute Vue methods in a browser harness, not a visual browser.
A synthetic live check also confirmed a Finnish classifier question and three
validated, generated answers. No production data was used for that check.
