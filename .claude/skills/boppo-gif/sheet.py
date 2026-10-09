#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10.1"]
# ///
"""A contact sheet: frames of a GIF or a video, each labeled with its time, tiled into one JPEG
small enough for Claude to Read.
  sheet.py <gif|mp4|mov> [t1 t2 ...]   frames at these seconds
  sheet.py <file> --every N            a frame every N seconds, from 0
  sheet.py <file> [-n N]               N frames evenly spaced, the first and the last included (12)
  -o out.jpg                           where it goes, overwritten; without it a new
                                       /tmp/sheet/<name>-<random>.jpg, so runs don't collide
A GIF's frames are picked by time from its own durations (Pillow merges repeated frames, so a
generator's frame indices don't exist in the file); a video's come from ffmpeg, which a video needs
installed. The labels are Pillow's, not ffmpeg's drawtext (not every build has it). Prints the sheet's path.
Runs on its own with uv (it brings Pillow): uv run sheet.py ..., or gif.py sheet ..."""
import io, json, math, os, pathlib, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

LONG = 1600                                  # the sheet's longest side, px: Read scales anything bigger down
STRIP = 26                                   # the label strip under each frame
FONT = ImageFont.load_default(size=18)


def gif_frames(src):
    """a GIF's frames as (start, end) seconds, from the file's own durations: Pillow merges
    repeated frames, so a generator's frame indices don't exist in the file"""
    im = Image.open(src); t, out = 0, []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i); d = im.info.get("duration", 0) / 1000
        out.append((t, t + d)); t += d
    return out


def duration(src):
    """seconds: a GIF's frames added up, a video's from ffprobe"""
    if src.suffix.lower() == ".gif": return gif_frames(src)[-1][1]
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True)
    return float(json.loads(p.stdout or "{}").get("format", {}).get("duration") or 0)


def grab(src, t):
    """the frame showing at t seconds, or None past the end: a GIF's from Pillow, the frame whose
    span holds t; a video's from ffmpeg, seeking the input"""
    if src.suffix.lower() == ".gif":
        spans = gif_frames(src)
        i = next((i for i, (a, b) in enumerate(spans) if a <= t < b), None)
        if i is None: return None
        im = Image.open(src); im.seek(i); return im.convert("RGB")
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                          "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout
    return Image.open(io.BytesIO(out)).convert("RGB") if out else None


def times(args, d):
    if "--every" in args:
        n = float(args[args.index("--every") + 1])
        return [round(i * n, 3) for i in range(int(d / n - 1e-9) + 1)]
    if args and "-n" not in args: return [float(a) for a in args]
    n = int(args[args.index("-n") + 1]) if "-n" in args else 12
    last = max(0.0, d - 0.05)                # the last frame, not past it
    return [round(last * i / (n - 1), 2) for i in range(n)] if n > 1 else [0.0]


def sheet(src, ts, d):
    shots = [(t, grab(src, t)) for t in ts]
    missing = [t for t, im in shots if im is None]
    shots = [(t, im) for t, im in shots if im is not None]
    if not shots: sys.exit(f"no frames: {src} is {d:.2f} s")
    w0, h0 = shots[0][1].size
    cols = min(len(shots), 6, math.ceil(math.sqrt(len(shots) * w0 / h0 * 0.6)) or 1)
    rows = math.ceil(len(shots) / cols)
    k = min(1.0, LONG / (cols * w0), (LONG - rows * STRIP) / (rows * h0))
    w, h = int(w0 * k), int(h0 * k)
    out = Image.new("RGB", (cols * w, rows * (h + STRIP)), (255, 255, 255))
    d_ = ImageDraw.Draw(out)
    for i, (t, im) in enumerate(shots):
        x, y = i % cols * w, i // cols * (h + STRIP)
        out.paste(im.resize((w, h), Image.LANCZOS), (x, y))
        d_.text((x + w / 2, y + h + STRIP / 2), f"{t:.2f} s", font=FONT, fill=(0, 0, 0), anchor="mm")
        d_.line([(x, y), (x, y + h + STRIP)], fill=(255, 255, 255), width=2)
    return out, missing


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"): print(__doc__); sys.exit(2)
    src = pathlib.Path(args.pop(0))
    if not src.exists(): sys.exit(f"no such file: {src}")
    dst = None
    if "-o" in args:
        i = args.index("-o"); dst = pathlib.Path(args[i + 1]); del args[i:i + 2]
    d = duration(src)
    im, missing = sheet(src, times(args, d), d)
    if dst is None:
        pathlib.Path("/tmp/sheet").mkdir(exist_ok=True)
        fd, dst = tempfile.mkstemp(prefix=f"{src.stem}-", suffix=".jpg", dir="/tmp/sheet")
        os.close(fd); dst = pathlib.Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=85)
    print(dst, f"{im.width}x{im.height}, {src.name} is {d:.2f} s"
          + (f"; past the end: {', '.join(f'{t:g}' for t in missing)}" if missing else ""))
