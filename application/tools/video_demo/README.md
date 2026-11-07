# SinceAI video demo generator

Records a ~2 minute MP4 tour of the application: Plant Director briefing,
ask flow with decision badges (REUSE / BUILD), calculation receipts and CSV
export, Data Steward governance, a Finnish follow-up question and the theme
toggle. One command from the `application/` directory with the project venv:

```powershell
& '..\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt   # once: adds imageio-ffmpeg
& '..\.venv\Scripts\python.exe' -m tools.video_demo.run_all              # real Gemini (~4 min)
& '..\.venv\Scripts\python.exe' -m tools.video_demo.run_all --fast       # canned answers (~2 min)
```

Output lands in `output/sinceai-demo.mp4` (gitignored), 1400x900 H.264.

## How it works

1. `app_offline.py` starts Uvicorn against **mongomock seeded from the data
   pack** (no MongoDB, no writes to Atlas) plus deterministic lived-in state:
   the header meter starts at **76 requests / 19 new charts / 32 without a new
   chart**, the registry holds certified charts with certify/retire
   suggestions, dashboards have pinned tiles, and a pending proposal waits for
   the Data Steward. `random.seed(42)` and pinned `TODAY` keep runs identical.
2. `recorder.cjs` drives the real frontend through a Chrome DevTools Protocol
   **screencast** (frames arrive as the page repaints; a tiny animated pixel
   keeps a steady heartbeat on static screens) while it walks the storyboard
   and asks the three demo questions.
3. `assembler.py` turns the JPEG frames + arrival timestamps into an MP4,
   clamping each gap at 2.2s so loading/Gemini waits stay visible but never
   drag. `run_all.py` verifies the result (meter deltas prove the
   REUSE/BUILD/REUSE story happened, duration sanity check).

## Demo questions and expected decisions

| Question | Decision | Why |
| --- | --- | --- |
| Show net sales month over month | REUSE | matches a seeded certified chart (both `Net Sales` and `Net Sales Growth` mappings are seeded, so Gemini's choice reuses either way) |
| How many units of Xarelto have we shipped by month? | BUILD | new chart registered live; the meter ticks 76 -> 77 during recording |
| Montako Xarelon yksikköä on toimitettu kuukausittain? | REUSE | same chart, answered in Finnish |

## Modes

* **Real (default)**: live Gemini wording. Spec generation is deterministic
  (temperature 0) but wording varies slightly (temperature 0.2) between runs.
* **`--fast`**: replays the specs/answers captured in `responses_fast.json`
  from real gemini-3.5-flash-lite runs. Decisions, fingerprints, charts,
  receipts and CSV exports are still computed for real by the engine - only
  the Gemini calls are replayed. Fully deterministic and instant.

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

`--out PATH`, `--fast`, `--base-url URL`, `--cdp URL`, `--viewport WxH`,
`--port N`, `--keep-frames`. Transient artifacts live in `.work/` (gitignored).

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
