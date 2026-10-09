"""A GIF generator's --check (the boppo-gif skill's). With --check a generator writes its GIFs and
stills to /tmp/gif-check/<its output folder's name>/ instead (under GIFCHECK_DIR if set: gif.py
check gives each run its own), and reads each GIF back:
  seconds  its frames' durations add up to the seconds it was drawn for, frames / FPS: a GIF keeps
           whole hundredths, so 15 fps plays at 60 ms a frame, ~10% fast
  dots     if given, every one of these buttons lit green in the first frame (a target drawn
           without its light is easy to miss by eye)
A line a GIF, "<<" on what's off. In a generator: OUT = gifcheck.out(OUT) before WANT reads argv, and
gifcheck.check(gif, len(frames), FPS, dots) after each save; dots: {button: (x, y)}, its cap's
center in the GIF: cap(project, btn_center, BTN_H, crop) makes the function, crop the
(left, top) the GIF was cut from the drawing at, (0, 0) uncut. Leaves the real output alone, so it runs any time."""
import atexit, os, pathlib, sys
import numpy as np
from PIL import Image

ON = "--check" in sys.argv
if ON: sys.argv.remove("--check")
DIR = pathlib.Path(os.environ.get("GIFCHECK_DIR", "/tmp/gif-check"))
OFF = []


def out(p):
    """where a generator writes: p, or /tmp/gif-check/<its last folder> under --check"""
    if not ON: return p
    d = DIR / pathlib.Path(p).name; d.mkdir(parents=True, exist_ok=True)
    return d


def cap(project, btn_center, top, crop):
    """the drawing's cap() for tablet-drawing.py's tablet, cropped: button n -> its cap's center"""
    def at(n):
        x, y = project(*btn_center(n % 5, n // 5), top)
        return x - crop[0], y - crop[1]
    return at


def seconds(gif):
    im = Image.open(gif); s = 0
    for i in range(im.n_frames):
        im.seek(i); s += im.info.get("duration", 0)
    return s / 1000


def color(im, x, y):
    """the mean color of a cap's middle; the cap is foreshortened, so the ellipse is flat"""
    yy, xx = np.mgrid[:im.shape[0], :im.shape[1]]
    return im[(xx - x) ** 2 + ((yy - y) * 1.6) ** 2 < 14 ** 2].mean(0)


def check(gif, frames, fps, dots=None):
    if not ON: return
    want, got = frames / fps, seconds(gif)
    say = [f"{got:.2f} s of {want:.2f}" + (" <<" if abs(got - want) > max(0.05, 0.01 * want) else "")]
    if dots:
        im = np.asarray(Image.open(gif).convert("RGB")).astype(float)
        dark = [n for n, (x, y) in dots.items()
                if not ((c := color(im, x, y)).max() - c.min() > 20 and c.argmax() == 1)]
        say.append("dots " + ("lit" if not dark else f"{', '.join(map(str, dark))} not green in the first frame <<"))
    if any("<<" in s for s in say): OFF.append(gif)
    print(f"  check  {pathlib.Path(gif).name}: " + ", ".join(say))


@atexit.register
def _summary():
    if ON: print(f"gif-check: {len(OFF)} off" + (f" ({', '.join(pathlib.Path(g).name for g in OFF)})" if OFF else "")
                 + f"; written to {DIR}")
