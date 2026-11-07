#!/usr/bin/env python3
"""Prepare a local/public reference video for actual viewing; no AI/ASR calls."""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr[-1800:] or f"Command failed: {args[0]}")
    return result


def stamp(seconds):
    return f"{int(seconds)//60:02}:{seconds%60:05.2f}"


def prepare(source, out, interval):
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("--interval must be positive and finite")
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            raise RuntimeError(f"Install {command} first")
    from PIL import Image, ImageDraw
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    if source.startswith(("https://", "http://")):
        if not shutil.which("yt-dlp"):
            raise RuntimeError("Install yt-dlp for URL input")
        run(["yt-dlp", "--ignore-config", "--no-playlist", "--no-progress",
             "--retries", "1", "--fragment-retries", "1", "--abort-on-unavailable-fragments",
             "--socket-timeout", "30", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
             "-o", str(out / "source.%(ext)s"), "--", source])
        candidates = [p for p in out.glob("source.*") if p.suffix not in (".part", ".ytdl", ".temp")]
        if len(candidates) != 1:
            raise RuntimeError("Expected one complete downloaded source; inspect the output")
        video = candidates[0]
    else:
        original = Path(source).resolve(strict=True)
        video = out / ("source" + original.suffix)
        shutil.copy2(original, video)
    info = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", str(video)]).stdout)
    streams = info["streams"]
    if not any(s["codec_type"] == "video" for s in streams):
        raise RuntimeError("The source has no video stream")
    duration = float(info["format"]["duration"])
    container_duration = duration
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Invalid media duration")
    audio = any(s["codec_type"] == "audio" for s in streams)
    if audio:
        run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0",
             "-ac", "1", "-ar", "16000", str(out / "audio.wav")])
    # Full decode: detect scene changes and fail on corrupt video instead of
    # reporting only a playable prefix as a complete reference.
    cuts_result = run(["ffmpeg", "-hide_banner", "-xerror", "-i", str(video),
                       "-map", "0:v:0", "-vf", "select='gt(scene,0.25)',showinfo",
                       "-an", "-f", "null", "-"])
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", cuts_result.stderr)]
    # Container duration may extend beyond the last real video frame (for
    # example, low-FPS or longer audio). Choose actual decoded video timestamps.
    frame_info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                 "-show_frames", "-show_entries", "frame=best_effort_timestamp_time",
                                 "-of", "json", str(video)]).stdout)
    start_time = float(info["format"].get("start_time", 0))
    stream_ends = [float(s.get("start_time", start_time)) + float(s["duration"]) - start_time
                   for s in streams if s.get("duration") not in (None, "N/A")]
    if stream_ends:
        duration = max(stream_ends)
    actual = sorted({max(0, float(f["best_effort_timestamp_time"]) - start_time)
                     for f in frame_info["frames"] if "best_effort_timestamp_time" in f})
    if not actual:
        raise RuntimeError("No timestamped video frames were decoded")
    requested = [actual[0] + i * interval for i in range(math.ceil((actual[-1] - actual[0]) / interval))]
    # FFmpeg normalizes input PTS here; showinfo cuts are already relative.
    requested.extend(cuts)
    times = {actual[min(bisect.bisect_left(actual, t), len(actual) - 1)]
             for t in requested if actual[0] <= t <= actual[-1]}
    times.update((actual[0], actual[-1]))
    frames_dir = out / "frames"
    frames_dir.mkdir()
    records = []
    for index, time in enumerate(sorted(times)):
        target = frames_dir / f"{index:04}.jpg"
        run(["ffmpeg", "-v", "error", "-ss", f"{max(0, time - 0.00005):.6f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=960:960:force_original_aspect_ratio=decrease",
             "-q:v", "2", str(target)])
        if not target.is_file():
            raise RuntimeError(f"Could not decode a requested frame at {time}")
        records.append({"time": time, "file": str(target.relative_to(out))})
    sheets = []
    for start in range(0, len(records), 25):
        batch = records[start:start + 25]
        sheet = Image.new("RGB", (5 * 240, math.ceil(len(batch) / 5) * 275), "#1B2027")
        draw = ImageDraw.Draw(sheet)
        for n, row in enumerate(batch):
            with Image.open(out / row["file"]) as frame:
                frame.thumbnail((230, 240))
                x = (n % 5) * 240 + (240 - frame.width) // 2
                y = (n // 5) * 275
                sheet.paste(frame, (x, y))
            draw.text(((n % 5) * 240 + 8, y + 246), stamp(row["time"]), fill="#FFD60A")
        name = f"sheet-{start//25 + 1:02}.jpg"
        sheet.save(out / name, quality=92)
        sheets.append(name)
    digest = hashlib.sha256()
    with video.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    manifest = {"source": source, "source_file": video.name, "sha256": digest.hexdigest(),
                "duration": duration, "container_duration": container_duration,
                "has_audio": audio, "interval": interval,
                "video_first_frame": actual[0], "video_last_frame": actual[-1],
                "scene_changes": cuts, "frames": records, "sheets": sheets,
                "status": "prepared; not yet viewed or transcribed"}
    (out / "media.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"directory": str(out), "duration": duration, "frames": len(records),
                      "sheets": sheets, "has_audio": audio}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("prepare")
    p.add_argument("source")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--interval", type=float, default=2)
    args = parser.parse_args()
    if args.command == "doctor":
        import importlib.util
        print(json.dumps({**{c: bool(shutil.which(c)) for c in ("ffmpeg", "ffprobe", "yt-dlp")},
                          "Pillow": importlib.util.find_spec("PIL") is not None}))
    else:
        prepare(args.source, args.out, args.interval)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, ImportError) as error:
        print(f"Reference preparation stopped: {error}", file=sys.stderr)
        sys.exit(1)
