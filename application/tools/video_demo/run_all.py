"""One-command SinceAI video demo generator.

Orchestrates the full pipeline: dependency checks, app startup on a fresh
deterministic database, CDP screencast recording of the storyboard,
MP4 assembly and verification. Default output is <repo>/output/sinceai-demo.mp4.

Run from the application directory with the project venv (needs the app's
requirements plus imageio-ffmpeg from requirements-dev.txt):

  python -m tools.video_demo.run_all              # real Gemini answers (~4 min)
  python -m tools.video_demo.run_all --fast       # canned responses, deterministic (~2 min)

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
    ap.add_argument("--fast", action="store_true",
                    help="replay canned Gemini responses (deterministic, instant)")
    ap.add_argument("--out", default=str(ROOT / "output" / "sinceai-demo.mp4"))
    ap.add_argument("--base-url", default=os.environ.get("VIDEO_DEMO_BASE_URL", "http://172.18.0.1:8000"),
                    help="origin the Chrome container uses to reach the app")
    ap.add_argument("--cdp", default=os.environ.get("VIDEO_DEMO_CDP", "http://127.0.0.1:9222"))
    ap.add_argument("--viewport", default="1400x900")
    ap.add_argument("--port", type=int, default=int(os.environ.get("VIDEO_DEMO_PORT", "8000")))
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    w, h = (int(x) for x in args.viewport.lower().split("x"))
    work = HERE / ".work"
    frames = work / "frames"
    stamps = work / "timestamps.json"
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
                   "DEMO_FRAMES": str(frames), "DEMO_STAMPS": str(stamps)}
        r = subprocess.run(["node", str(HERE / "recorder.cjs")], cwd=str(HERE), env=rec_env)
        if r.returncode != 0:
            print("recorder failed; see its output above", file=sys.stderr)
            return 1

        # assemble
        r = subprocess.run([sys.executable, str(HERE / "assembler.py"),
                            "--frames", str(frames), "--stamps", str(stamps),
                            "--out", args.out, "--ffmpeg", ffmpeg])
        if r.returncode != 0:
            return 1

        # verify
        meter_after = http_json(f"http://127.0.0.1:{args.port}/api/meter")
        d_req = meter_after["requests"] - meter_before["requests"]
        d_new = meter_after["new_charts"] - meter_before["new_charts"]
        d_reuse = (meter_after["by_decision"]["REUSE"] - meter_before["by_decision"]["REUSE"])
        dur = probe_duration(ffmpeg, Path(args.out))
        ok = d_req == 3 and d_new >= 1 and d_reuse >= 2 and dur >= 60
        print(f"verification: meter delta requests={d_req} new_charts={d_new} reuse={d_reuse}, "
              f"duration={dur:.1f}s -> {'OK' if ok else 'UNEXPECTED (check the video)'}")
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


if __name__ == "__main__":
    sys.exit(main())
