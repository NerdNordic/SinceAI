# SinceAI video demo generator

Records a ~45s MP4 pitch ("Build Less, Build Better", storyboard in
`SCRIPT.md`): title card, four roles asking questions in plain language
(BUILD / REUSE / ANSWER / CLARIFY badges), and the Data Steward certifying
the reused chart with test results proving repeatability. One command from
the `application/` directory with the project venv:

```powershell
& '..\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt      # once: adds imageio-ffmpeg
& '..\.venv\Scripts\python.exe' -m tools.video_demo.run_all                 # real Gemini (~4 min)
& '..\.venv\Scripts\python.exe' -m tools.video_demo.run_all --rehearse      # dry-run Gemini, then record (~4-5 min)
& '..\.venv\Scripts\python.exe' -m tools.video_demo.run_all --fast         # canned answers (~2 min)
```

Output lands in `../../../output/sinceai-demo.mp4` (gitignored), 1600x900
H.264 at 12fps, with a cursor overlay, click ripples, top captions and
title/end cards.

## How it works

1. `app_offline.py` starts Uvicorn against **mongomock seeded from the data
   pack** (no MongoDB, no writes to Atlas) plus deterministic lived-in state:
   the header meter starts at **76 requests / 19 new charts / 32 without a new
   chart**, the registry holds certified charts, and the eval run (40/40
   passed, 39/40 consistent, 0 guesses) is seeded into `eval_runs` for the
   steward's QA section. `random.seed(42)` and pinned `TODAY` keep runs
   identical.
2. `recorder.cjs` drives the real frontend through a Chrome DevTools Protocol
   **screencast** (frames arrive as the page repaints; a tiny animated pixel
   keeps a heartbeat on static screens, and mouse nudges keep the end cards
   emitting damage) while it walks the 7-scene storyboard in `SCRIPT.md` -
   glides, click ripples, captions at the top, cards, and the four scripted
   questions.
3. `assembler.py` turns the JPEG frames + arrival timestamps into an MP4,
   clamping each gap at 2.2s, compressing trimmed wait windows to
   `--cut-hold`, and temporally downsampling to `--fps` (default 12).
4. `run_all.py` verifies the result end-to-end: the decision sequence
   BUILD->REUSE->ANSWER->CLARIFY, meter deltas 76/19/32 -> 80/20/34, exactly
   one new chart, +2 handled without a new chart, the eval run in the
   steward view, the OTIF chart certified with use_count >= 1 and 2 roles,
   and duration 38-52s.

### Loading-state trimming

The recorder **pauses the screencast during known waits** after a short
"skeleton taste" and resumes when the content is ready; the pause windows are
written to `.work/cuts.json` and the assembler compresses exactly those gaps
to `--cut-hold` (default 0.5s - one beat on the last frame, then content):

| Wait | Skeleton kept visible |
| --- | --- |
| Chat answers ("Gemini tulkitsee…") | ~1s of the real thinking state, then cut (answers that arrive sooner are never trimmed) |
| Initial page load | ~0.3s flash |
| Role switches | ~0.3s flash |
| Language/preview switches | ~0.25s flash |

The taste durations are constants at the call sites in `recorder.cjs`
(`trimLoad(...)` / `trimChat(...)`), so they are easy to tune.

## Demo questions and expected decisions

Wordings are stability-probed against real gemini-3.5-flash-lite
(3/3 deterministic for the first three; the fourth is ~2/3 and is what the
`--rehearse` retry loop is for):

| Question | Decision | Why |
| --- | --- | --- |
| Show OTIF by product for this year (shift supervisor) | BUILD | new chart registered live; the meter ticks 76 -> 77 during recording |
| Näytä OTIF tuotteittain tältä vuodelta (plant director) | REUSE | same chart via the Finnish mapping, answered in English |
| What is our forecast variance right now? (finance controller) | ANSWER | one-off number, no new chart (the script's "this year?" wording would BUILD instead) |
| Show employee satisfaction by month (country manager) | CLARIFY | unsupported metric - SinceAI asks instead of guessing |

## Modes

* **Real (default)**: live Gemini wording. Decisions are deterministic
  (spec temperature 0) but wording varies slightly between runs.
* **`--rehearse`**: before recording, the launcher runs every scripted
  question in-process against real Gemini (up to 6 attempts per question,
  clearing the cached spec doc and restoring the pre-question state between
  attempts) so the recorded run hits warm `llm_cache` entries and the
  expected decision sequence is guaranteed; the state is restored afterwards.
* **`--fast`**: replays the specs/answers captured in `responses_fast.json`
  from real gemini-3.5-flash-lite runs (the launcher also self-checks them
  via the same dry-run). Decisions, fingerprints, charts, receipts and CSV
  exports are still computed for real by the engine - only the Gemini calls
  are replayed. Fully deterministic and instant.

## Prerequisites

* The app venv with `requirements.txt` + `requirements-dev.txt` installed
  (`imageio-ffmpeg` supplies the encoder).
* Node.js/npm for `playwright-core` (`run_all.py` runs `npm ci` automatically
  on first use; `node_modules/` here is gitignored).
* A headless Chrome exposing CDP on `127.0.0.1:9222`:

  ```
  docker run -d --name sinceai-chrome -p 9222:9222 chromedp/headless-shell
  ```

* The Chrome container must reach the app. The default `--base-url`
  `http://172.18.0.1:8000` is the docker-bridge host address on Linux; with
  Docker Desktop (Windows/macOS) pass `--base-url http://host.docker.internal:8000`.
  `VIDEO_DEMO_BASE_URL` can set it permanently.

## Useful flags

`--out PATH`, `--fast`, `--rehearse`, `--base-url URL`, `--cdp URL`,
`--viewport WxH` (default 1600x900), `--port N`, `--fps N`,
`--cut-hold SECONDS`, `--keep-frames`. Transient artifacts live in `.work/`
(gitignored).

## Using your real chart registry

Export the registry from a running local app (`GET /api/registry`) to a file
and point the launcher at it - the synthetic charts are then replaced by the
real ones:

```
set VIDEO_DEMO_REGISTRY_JSON=C:\path\to\registry.json
python -m tools.video_demo.run_all
```

## Notes and limits

* Atlas itself is unreachable from the sandboxed recorder environment (the
  egress proxy terminates TLS and drops the MongoDB wire protocol), so the
  app runs on the seeded offline database. All numbers come from the same
  data pack, so the figures match.
* Vector search (similar charts / related reports panels) requires Atlas
  search indexes and stays hidden in the offline mode; the rest of the flow,
  including REUSE, is plain database logic and works unchanged.
* Google Fonts is blocked in the sandbox; the UI falls back to system fonts.
  A `net::ERR_NAME_NOT_RESOLVED` console message during recording is this and
  is harmless.
* `recorder.cjs` requires the Chrome container's CDP endpoint; Playwright's
  built-in `recordVideo` does not work over `connectOverCDP`, hence the
  manual screencast pipeline.
* CDP screencast pauses (the trim windows) stop the heartbeat animation
  until the next input-driven repaint - that is why the recorder nudges the
  mouse on static end/title cards.
