"""The studio's Animation: one light animation, a JSON file anything can write (the page, Claude, a
person), and its lights at a moment.

clean() is the one way in: every file the studio reads or writes, and every version Claude writes,
goes through it. Unknown keys go, a number is clamped into its range, a missing value gets its
default, and a block, press or line it can't draw (no color, button 10, ending before it starts) is
left out. The rest of the studio, the drawing included, sees only what clean() made. Its ranges are
FILE's, wide enough that no file the page or a person writes is cut; Claude's versions are cleaned
to CLAUDE's.

SCHEMA is the format, in the words Claude is told it (studio_chat.py); page() is what the page
draws its controls from. A version, one of Claude's, also has
  batch  {"id", "request", "from" (the animation it came from), "n" (its number in the grid),
          "note", "picked" (true once edited)}
"""
import json, math, os, pathlib
from collections import namedtuple

FPS = 10                                          # the tablet's: times are in tenths of a second
BUTTONS = 10                                      # 0-4 the top row, 5-9 the bottom, the kid's side
LIGHTS = ("top", "left", "right", "bottom")       # Boppo's LightDir order: light n*4 + dir
CLOCKWISE = ("top", "right", "bottom", "left")
# Boppo's named colors (rust_boppo_core color.rs), in its order
PALETTE = {
    "RED": (255, 0, 0), "ORANGE": (255, 127, 0), "YELLOW": (255, 255, 0), "CHARTREUSE": (127, 255, 0),
    "GREEN": (0, 255, 0), "SPRING_GREEN": (0, 255, 127), "CYAN": (0, 255, 255), "AZURE": (0, 127, 255),
    "BLUE": (0, 0, 255), "VIOLET": (127, 0, 255), "MAGENTA": (255, 0, 255), "ROSE": (255, 0, 127),
    "PINK": (255, 112, 133), "PURPLE": (127, 0, 127), "TEAL": (0, 127, 127), "WHITE": (255, 255, 255),
}
EFFECTS = {                                       # each one's rule, as SCHEMA says it
    "steady": "",
    "pulse": "breathing from level down to a quarter and back every `every` s",
    "flash": "color then color2 (off if null), each half of `every`",
    "spin": "one light at a time clockwise from the top, a light every `every` / 4 s",
}
LEVEL = (0.05, 1, 1.0)                            # a block's brightness: least, most, and its default
# seconds: an animation's length, least, most and its default, and no time past its most (a start, an
# end, a fade); every: an effect's period, the same; text: a line's characters, at most
Limits = namedtuple("Limits", "seconds every text")
CLAUDE = Limits((0.5, 30, 3.0), (0.1, 10, 1.5), 80)   # a version of Claude's
FILE = Limits((0.5, 600, 3.0), (0.1, 600, 1.5), 500)  # any other file: only so nothing runs away

SCHEMA = f"""An animation is JSON:
{{"seconds": 3.0,
 "blocks": [{{"button": 0, "start": 0.0, "end": 1.0, "color": [0, 255, 0], "level": 1.0,
   "effect": "steady", "every": 1.5, "color2": null, "fade_in": 0.0, "fade_out": 0.0,
   "lights": ["top", "left", "right", "bottom"]}}],
 "presses": [{{"button": 9, "start": 1.0, "end": 1.4}}],
 "captions": [{{"start": 0.0, "end": 1.0, "text": "Pick your color!"}}],
 "still": 1.0}}
- A block lights one button from start to end (seconds). level is brightness, {LEVEL[0]:g} to {LEVEL[1]:g}.
- effect: {"; ".join(k + (f", {v}" if v else "") for k, v in EFFECTS.items())}.
- lights: which of the button's four lights the block lights.
- A block that starts later is drawn over one that started earlier, light by light.
- presses: a button pushed in, from its press to its release. captions: the line being said.
- still: the moment, in seconds, its still picture is taken from.
- Colors: use Boppo's named colors as RGB: {", ".join(f"{k} {list(v)}" for k, v in PALETTE.items())}."""


# ---------- clean: any JSON in, an Animation out -------------------------------------------------
def num(v, lo, hi, default):
    """v as a number in lo..hi, to the hundredth; default when it isn't one"""
    try: v = float(v)
    except (TypeError, ValueError): return default
    return round(min(hi, max(lo, v)), 2) if math.isfinite(v) else default


def button(v):
    try: n = int(v)
    except (TypeError, ValueError, OverflowError): return None
    return n if 0 <= n < BUTTONS else None


def rgb(c):
    """[r, g, b] from three numbers or one of Boppo's color names; None from anything else"""
    if isinstance(c, str): c = PALETTE.get(c.strip().upper().replace(" ", "_"))
    if not isinstance(c, (list, tuple)) or len(c) != 3: return None
    return [int(num(v, 0, 255, 0)) for v in c]


def span(x, longest):
    """an item's start and end, or None when it has no time on the timeline"""
    start, end = num(x.get("start"), 0, longest, None), num(x.get("end"), 0, longest, None)
    return (start, end) if start is not None and end is not None and end > start else None


def objects(v): return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def look(b, limits=FILE):
    """a block's values past its button, time and color (its level, effect, lights...), each its
    default when it has none"""
    longest = limits.seconds[1]
    lights = b.get("lights") if isinstance(b.get("lights"), list) else LIGHTS
    fx = b.get("effect")
    return {"level": num(b.get("level"), *LEVEL), "effect": fx if isinstance(fx, str) and fx in EFFECTS else "steady",
            "every": num(b.get("every"), *limits.every), "color2": rgb(b.get("color2")),
            "fade_in": num(b.get("fade_in"), 0, longest, 0.0), "fade_out": num(b.get("fade_out"), 0, longest, 0.0),
            "lights": [s for s in LIGHTS if s in lights] or list(LIGHTS)}


def batch(b):
    """a version's batch, or None when it has no id to be found by"""
    if not isinstance(b, dict) or not isinstance(b.get("id"), str): return None
    s = lambda k, n: b[k][:n] if isinstance(b.get(k), str) else ""
    return {"id": b["id"], "request": s("request", 120), "from": b["from"] if isinstance(b.get("from"), str) else None,
            "n": int(num(b.get("n"), 0, 99, 0)), "note": s("note", 160), "picked": b.get("picked") is True}


def clean(a, limits=FILE):
    """an Animation the studio can draw, from any JSON object, within limits (FILE, or CLAUDE for one
    of Claude's versions); ValueError from anything else"""
    if not isinstance(a, dict): raise ValueError(f"not an animation: a JSON object is, not {type(a).__name__}")
    seconds, longest = num(a.get("seconds"), *limits.seconds), limits.seconds[1]
    out = {"seconds": seconds, "blocks": [], "presses": [], "captions": [],
           "still": num(a.get("still"), 0, seconds - 1 / FPS, min(1.0, seconds / 2))}
    for b in objects(a.get("blocks")):
        n, t, color = button(b.get("button")), span(b, longest), rgb(b.get("color"))
        if n is not None and t and color: out["blocks"].append({"button": n, "start": t[0], "end": t[1], "color": color, **look(b, limits)})
    for p in objects(a.get("presses")):
        n, t = button(p.get("button")), span(p, longest)
        if n is not None and t: out["presses"].append({"button": n, "start": t[0], "end": t[1]})
    for c in objects(a.get("captions")):
        if (t := span(c, longest)) and isinstance(c.get("text"), str): out["captions"].append({"start": t[0], "end": t[1], "text": c["text"][:limits.text]})
    if b := batch(a.get("batch")): out["batch"] = b
    return out


def read(path):
    """the Animation in a file, cleaned; OSError or ValueError when it has none"""
    return clean(json.loads(pathlib.Path(path).read_text()))


def write(path, a):
    """a cleaned, written whole; what it wrote"""
    a = clean(a); write_text(path, json.dumps(a, indent=1) + "\n")
    return a


def write_text(path, text):
    """a file written whole, so a reader never finds half of it: through a symlink to the file it
    points at, its mode kept (a new one's the umask's, as open() makes it)"""
    path = pathlib.Path(path).resolve()
    tmp = path.with_name(f".{path.stem}.{os.urandom(4).hex()}.tmp")
    try:
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), "w") as f:
            try: os.fchmod(f.fileno(), path.stat().st_mode & 0o7777)
            except FileNotFoundError: pass
            f.write(text)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True); raise


def page():
    """what the page draws its controls from, so it keeps no copy: Boppo's colors, the effects and
    lights, a file's limits, an empty animation and a new block's values"""
    return {"palette": list(PALETTE.items()), "effects": list(EFFECTS), "lights": LIGHTS, "fps": FPS, "buttons": BUTTONS,
            "seconds": FILE.seconds[:2], "level": LEVEL[:2], "every": FILE.every[:2], "text": FILE.text,
            "fresh": clean({}), "block": look({})}


# ---------- playback: an Animation at t seconds ------------------------------------------------
def level_at(b, t):
    """a block's level at t seconds, its fades and effect applied; its color with it"""
    if not b["start"] <= t < b["end"]: return 0.0, None
    k, c, e, every = b["level"], tuple(b["color"]), t - b["start"], b["every"]
    if b["fade_in"] > 0: k *= min(1.0, e / b["fade_in"])
    if b["fade_out"] > 0: k *= min(1.0, (b["end"] - t) / b["fade_out"])
    if b["effect"] == "pulse": k *= 0.25 + 0.75 * (0.5 + 0.5 * math.cos(2 * math.pi * e / every))
    elif b["effect"] == "flash" and (e % every) >= every / 2:
        if not b["color2"]: return 0.0, None
        c = tuple(b["color2"])
    return k, c


def framebuffer(anim, t):
    """the 40 lights at t seconds, Boppo's order (button n, light n*4 + top/left/right/bottom), of
    an Animation clean() made"""
    fb = [(0, 0, 0)] * 40
    for b in sorted(anim["blocks"], key=lambda b: b["start"]):
        k, c = level_at(b, t)
        if k <= 0 or c is None: continue
        lights = b["lights"]
        if b["effect"] == "spin": lights = [CLOCKWISE[int((t - b["start"]) / (b["every"] / 4) + 1e-9) % 4]]
        for side in lights:
            fb[b["button"] * 4 + LIGHTS.index(side)] = tuple(int(v * min(1.0, k)) for v in c)
    return fb
