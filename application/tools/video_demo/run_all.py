"""One-command SinceAI video demo generator ("Build Less, Build Better" script).

Orchestrates the full pipeline: dependency checks, app startup on a fresh
deterministic database (incl. the golden-question eval run for the Data
Steward view), CDP screencast recording of the 7-scene storyboard,
MP4 assembly and verification. Default output is <repo>/output/sinceai-demo.mp4
(40-45 s, 1600x900, English UI, cursor overlay + captions per
ignore/target-video-script).

Run from the application directory with the project venv (needs the app's
requirements plus imageio-ffmpeg from requirements-dev.txt):

  python -m tools.video_demo.run_all                # live Gemini, un-rehearsed
  python -m tools.video_demo.run_all --rehearse     # dry-run the scripted questions once
                                                    # against real Gemini (warming llm_cache),
                                                    # then record the fast identical run (recommended)
  python -m tools.video_demo.run_all --fast         # canned responses, zero API calls

Prerequisites:
  * A headless Chrome with CDP on 127.0.0.1:9222, e.g.
      docker run -d --name sinceai-chrome -p 9222:9222 chromedp/headless-shell
  * node + npm (playwright-core, installed automatically via `npm ci`)
  * The Chrome container must be able to reach the app; inside this sandbox
    that is http://172.18.0.1:8000 (docker bridge). With Docker Desktop use
    --base-url http://host.docker.internal:8000.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # application/tools/video_demo
APP = HERE.parents[1]                           # application
ROOT = APP.parent                               # repository root


def http_json(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def check_cdp(cdp: str) -> bool:
    try:
        info = http_json(cdp.rstrip("/") + "/json/version")
        print(f"CDP ok: {info.get('Browser', '?')}")
        return True
    except Exception as e:
        print(f"Chrome CDP endpoint not reachable at {cdp}: {e}", file=sys.stderr)
        print("Start one, e.g.:\n  docker run -d --name sinceai-chrome -p 9222:9222 chromedp/headless-shell",
              file=sys.stderr)
        return False


def ensure_playwright() -> bool:
    if (HERE / "node_modules" / "playwright-core").exists():
        return True
    if not shutil.which("node"):
        print("node/npm not found on PATH", file=sys.stderr)
        return False
    print("installing playwright-core (npm ci)...")
    r = subprocess.run(["npm", "ci"], cwd=HERE)
    if r.returncode == 0:
        return True
    r = subprocess.run(["npm", "install"], cwd=HERE)
    return r.returncode == 0


def ensure_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        print("installing imageio-ffmpeg...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "imageio-ffmpeg"])
        if r.returncode != 0:
            raise RuntimeError("pip install imageio-ffmpeg failed")
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()


def wait_health(port: int, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return http_json(f"http://127.0.0.1:{port}/api/health", timeout=3)
        except Exception as e:
            last = e
            time.sleep(1.0)
    raise RuntimeError(f"app did not become healthy: {last}")


def probe_duration(ffmpeg: str, path: Path) -> float:
    r = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration" in line:
            ts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = ts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true",
                      help="replay canned Gemini responses (deterministic, instant, zero API calls)")
    mode.add_argument("--rehearse", action="store_true",
                     help="dry-run the scripted questions once against real Gemini to warm "
                          "llm_cache, then record the fast identical run (recommended)")
    ap.add_argument("--out", default=str(ROOT / "output" / "sinceai-demo.mp4"))
    ap.add_argument("--base-url", default=os.environ.get("VIDEO_DEMO_BASE_URL", "http://172.18.0.1:8000"),
                    help="origin the Chrome container uses to reach the app")
    ap.add_argument("--cdp", default=os.environ.get("VIDEO_DEMO_CDP", "http://127.0.0.1:9222"))
    ap.add_argument("--viewport", default="1600x900")
    ap.add_argument("--port", type=int, default=int(os.environ.get("VIDEO_DEMO_PORT", "8000")))
    ap.add_argument("--cut-hold", type=float, default=0.5,
                    help="gap seconds across a trimmed wait (assembler --cut-hold)")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    w, h = (int(x) for x in args.viewport.lower().split("x"))
    work = HERE / ".work"
    frames = work / "frames"
    stamps = work / "timestamps.json"
    cuts = work / "cuts.json"
    scenes_path = work / "scenes.json"
    app_log = work / "app.log"
    work.mkdir(parents=True, exist_ok=True)

    if not check_cdp(args.cdp):
        return 2
    if not ensure_playwright():
        return 2
    ffmpeg = ensure_ffmpeg()

    # refuse to record against an app that is not ours (port already serving)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=2)
        print(f"port {args.port} already serves an app; stop it or use --port", file=sys.stderr)
        return 2
    except Exception:
        pass

    # start the app on a fresh deterministic database
    env = {**os.environ, "VIDEO_DEMO_PORT": str(args.port)}
    if args.fast:
        env["VIDEO_DEMO_FAST"] = "1"
    elif args.rehearse:
        env["VIDEO_DEMO_REHEARSE"] = "1"
    app = subprocess.Popen([sys.executable, str(HERE / "app_offline.py")],
                            cwd=str(APP), env=env,
                            stdout=open(app_log, "w"), stderr=subprocess.STDOUT)
    try:
        if app.poll() is not None:
            print(f"app process exited immediately; log tail:\n{app_log.read_text()[-2000:]}",
                  file=sys.stderr)
            return 1
        health = wait_health(args.port)
        print(f"app healthy: model={health.get('model')}")
        meter_before = http_json(f"http://127.0.0.1:{args.port}/api/meter")

        # record
        rec_env = {**os.environ, "DEMO_BASE_URL": args.base_url, "DEMO_CDP": args.cdp,
                   "DEMO_W": str(w), "DEMO_H": str(h),
                   "DEMO_FRAMES": str(frames), "DEMO_STAMPS": str(stamps),
                   "DEMO_CUTS": str(cuts), "DEMO_SCENES": str(scenes_path)}
        r = subprocess.run(["node", str(HERE / "recorder.cjs")], cwd=str(HERE), env=rec_env)
        if r.returncode != 0:
            print("recorder failed; see its output above", file=sys.stderr)
            return 1

        # assemble
        asm_cmd = [sys.executable, str(HERE / "assembler.py"),
                   "--frames", str(frames), "--stamps", str(stamps),
                   "--out", args.out, "--ffmpeg", ffmpeg,
                   "--cut-hold", str(args.cut_hold)]
        if cuts.exists():
            asm_cmd += ["--cuts", str(cuts)]
        r = subprocess.run(asm_cmd)
        if r.returncode != 0:
            return 1

        # verify the script's contract
        meter_after = http_json(f"http://127.0.0.1:{args.port}/api/meter")
        d_req = meter_after["requests"] - meter_before["requests"]
        d_new = meter_after["new_charts"] - meter_before["new_charts"]
        d_handled = meter_after["handled_without_new_chart"] - meter_before["handled_without_new_chart"]
        d_by = {k: meter_after["by_decision"].get(k, 0) - meter_before["by_decision"].get(k, 0)
                for k in ("BUILD", "REUSE", "EXTEND", "ANSWER", "CLARIFY")}
        dur = probe_duration(ffmpeg, Path(args.out))
        recorded = json.loads(scenes_path.read_text()) if scenes_path.exists() else []
        decisions = [s.get("decision") for s in recorded]
        eval_latest = http_json(f"http://127.0.0.1:{args.port}/api/eval/latest")
        registry = http_json(f"http://127.0.0.1:{args.port}/api/registry")
        otif_chart = next((c for c in registry
                           if (c.get("spec") or {}).get("metric") == "On-Time In-Full"
                           and "product" in ((c.get("spec") or {}).get("dimensions") or [])), None)
        checks = {
            "decisions BUILD->REUSE->ANSWER->CLARIFY":
                decisions == ["BUILD", "REUSE", "ANSWER", "CLARIFY"],
            "meter requests +4": d_req == 4,
            "new charts +1 (BUILD)": d_new == 1 and d_by["BUILD"] == 1,
            "REUSE/ANSWER/CLARIFY +1 each":
                d_by["REUSE"] == 1 and d_by["ANSWER"] == 1 and d_by["CLARIFY"] == 1,
            "handled without new chart +2": d_handled == 2,
            "duration 38-52s (target 40-45)": 38 <= dur <= 52,
            "eval run renders in steward view":
                bool(eval_latest and eval_latest.get("summary", {}).get("total")),
            "OTIF chart certified after steward approval":
                bool(otif_chart and otif_chart.get("status") == "certified"
                     and otif_chart.get("use_count", 0) >= 1
                     and len(otif_chart.get("used_by_roles") or []) >= 2),
        }
        print(f"verification: meter {meter_before['requests']}/{meter_before['new_charts']}/"
              f"{meter_before['handled_without_new_chart']} -> {meter_after['requests']}/"
              f"{meter_after['new_charts']}/{meter_after['handled_without_new_chart']}, "
              f"duration={dur:.1f}s")
        for name, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        ok = all(checks.values())
        print(f"verification -> {'OK' if ok else 'UNEXPECTED (check the video)'}")
        print(f"done: {args.out}")
        return 0 if ok else 1
    finally:
        app.terminate()
        try:
            app.wait(timeout=10)
        except subprocess.TimeoutExpired:
            app.kill()
        if not args.keep_frames:
            shutil.rmtree(frames, ignore_errors=True)
            stamps.unlink(missing_ok=True)
            cuts.unlink(missing_ok=True)
            scenes_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
