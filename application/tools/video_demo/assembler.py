"""Assemble CDP screencast frames into an MP4 using frame arrival timestamps.

Usage:
  python assembler.py --frames .work/frames --stamps .work/timestamps.json \
                     --out ../../output/sinceai-demo.mp4
Gap handling: loading/Gemini waits are real demo moments, so gaps are clamped
at 2.2s each - present but never dead air. Output is H.264 yuv420p with
+faststart so the file streams from disk immediately.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def ffmpeg_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", default=str(here / ".work" / "frames"))
    ap.add_argument("--stamps", default=str(here / ".work" / "timestamps.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--max-gap", type=float, default=2.2,
                    help="clamp per-frame gap seconds (default 2.2)")
    args = ap.parse_args()

    frames = Path(args.frames)
    stamps = json.loads(Path(args.stamps).read_text())
    n = len(stamps)
    if n < 10:
        print(f"too few frames: {n}", file=sys.stderr)
        return 1

    lines = ["ffconcat version 1.0"]
    for i, t in enumerate(stamps):
        dur = (stamps[i + 1] - t) / 1000.0 if i + 1 < n else 0.08
        dur = max(0.03, min(dur, args.max_gap))
        lines.append(f"file 'frames/f{i:05d}.jpg'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file 'frames/f{n - 1:05d}.jpg'")
    list_path = frames.parent / "list.txt"
    list_path.write_text("\n".join(lines) + "\n")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_path(args.ffmpeg)
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-vf", "fps=12,format=yuv420p", "-c:v", "libx264", "-crf", "19",
           "-preset", "medium", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, cwd=frames.parent, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:], file=sys.stderr)
        return 1

    probe = subprocess.run([ff, "-i", str(out)], capture_output=True, text=True)
    for line in probe.stderr.splitlines():
        if "Duration" in line or "Stream #0:0" in line:
            print(line.strip())
    print(f"frames: {n}, size: {out.stat().st_size} bytes")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
