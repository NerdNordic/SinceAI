# Demo storyboard - "Build Less, Build Better"

Source: `ignore/target-video-script`. 1600x900, English UI, dark theme,
~40-45s target (verification gate 38-52s). Every click shows the green
ripple; the cursor glides between elements, never teleports.

| # | Scene | Role / view | Action | Caption (top bar) |
| --- | --- | --- | --- | --- |
| 1 | Title card | - | 2.5s hold | *(no caption - "SinceAI" / "Build less. Build better." card)* |
| 2 | Ask in plain language | Shift supervisor (vuoropaallikko) -> Conversation | select role, ask "Show OTIF by product for this year" -> BUILD badge + receipt shown + scrolled | "A shift supervisor asks a question in plain language." |
| 3 | Reuse beats rebuild | Plant director (tehtaan_johtaja) -> Conversation | ask "Näytä OTIF tuotteittain tältä vuodelta" (Finnish) -> REUSE badge, meter "handled without a new chart" highlighted | "The director asks the same in Finnish - and it's handled without building a new chart." |
| 4 | Governed answers | Finance controller (finance_controller) -> Conversation | ask "What is our forecast variance right now?" -> ANSWER badge (one-off number, no chart) | "The finance controller gets a one-off answer with no new chart at all." |
| 5 | Honest limits | Country manager (country_manager_fi) -> Conversation | ask "Show employee satisfaction by month" -> CLARIFY badge (missing dimension question) | "When data is missing, SinceAI asks instead of guessing." |
| 6 | Steward cleanliness + test results | Data steward (data_steward) -> Governance | registry -> propose certification for the reused OTIF chart -> approve -> audit log -> QA section (40/40 passed, 39/40 consistent, 0 guesses) | "Nothing ships twice, and nothing ships unverified. Test results prove the answers stay repeatable." |
| 7 | End card | - | ~3s hold | *(no caption - "Build less. Build better." card)* |

## Expected state changes (verification contract)

* Decision sequence exactly **BUILD -> REUSE -> ANSWER -> CLARIFY**.
* Header meter 76/19/32 -> **80/20/34** (requests +4, new charts +1,
  handled-without-new-chart +2).
* Exactly one new chart registered (S2). S3 overwrites the registry title
  to "On-Time In-Full by Product YTD"; S4 is a one-off answer; S5 is a
  clarification request.
* After the steward approves, the OTIF-by-product chart is certified with
  use_count >= 1 and used by >= 2 roles.
* The latest eval run (40/40 passed, 39/40 consistent, 0/4 guesses) renders
  in the QA section.

## Pacing rules (per the script)

* Clicks: ~100ms pause before, ~150ms after; typing 25ms/char.
* Hold each decision badge >= 1.5s (including the glide to it).
* Receipt (S2) ~2s; meter/audit/QA moments 1.2-2.5s; smooth-scroll, no jumps.
* Captions sit at the top (below the sticky header) so they never cover the
  element being explained - especially the ask input during typing.
* Loading/thinking states are trimmed to a short taste (~1s chat skeleton,
  ~0.3s loads) - see README.

## Quality checklist (checked on the rendered video)

- [x] Total duration 38-52s (last run: 47.6s)
- [x] All 12 click moments show the green ripple (~2-3 frames each)
- [x] Cursor overlay follows every glide; captions at top, never over the input
- [x] Title/end cards render fully dark ~2.5s / ~3s
- [x] Meter visibly ticks 76/19/32 -> 80/20/34 across scenes 2-5
- [x] BUILD/REUSE/ANSWER/CLARIFY badges all linger long enough to read
