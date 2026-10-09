#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0", "numpy==2.5.3"]   # pinned: the same versions draw the same bytes
# ///
"""The GIF skill's steps as code (SKILL.md beside this). Needs only uv: it brings Pillow and numpy,
and runs generators and sheet.py with them, telling each where this folder is (BOPPO_GIF), so a
generator keeps working when it or this folder moves. Everything it needs is in this folder.

  gif.py new PATH [OUT]                a starter generator at PATH (not overwritten): the tablet
                                       drawing loaded, the check wired, button 0 lit green for 2 s.
                                       It writes its GIFs to OUT, kept relative to PATH; without
                                       OUT, to gifs/ beside it.
  gif.py check GENERATOR [NAME ...]    GENERATOR --check (only NAMEs, if given), then a contact
                                       sheet of each GIF it wrote to its own folder in
                                       /tmp/gif-check/ (so runs at once don't mix); prints the
                                       check's lines and the sheets' paths. Exit 0 all fine, 1 a GIF
                                       off or a sheet failed (a "<<" line) or the generator failed,
                                       2 it wrote no GIF (or none by a NAME given).
  gif.py run GENERATOR [ARG ...]       GENERATOR for real, from the current directory: it writes
                                       its GIFs where it says (each with a still, NAME.png).
                                       ARGs pass through: NAMEs, or --check.
  gif.py sheet FILE [ARGS ...]         sheet.py: a contact sheet of a GIF or a video (ffmpeg),
                                       frames at times; its own usage with no FILE.
Anything else prints this and exits 3."""
import os, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECKED = pathlib.Path("/tmp/gif-check")
ENV = {**os.environ, "BOPPO_GIF": str(HERE), "PYTHONDONTWRITEBYTECODE": "1"}   # no __pycache__ in a copy

STARTER = '''# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10.1", "numpy"]
# ///
"""<What this draws, and the GIFs it writes by name.>
Buttons are numbered as on the tablet: 0-4 the top row, 5-9 the bottom row (the kid's side).
Run with the boppo-gif skill's gif.py: `gif.py check <this file> [name ...]` writes the GIFs to
/tmp/gif-check/ and checks their length; `gif.py run <this file> [name ...]` writes them for real.
Names pick which GIFs to write; none writes them all."""
import os, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
# the boppo-gif skill, the drawing and the check: where gif.py says, else where it was when this was made
SKILL = pathlib.Path(os.environ.get("BOPPO_GIF", "{skill}"))
sys.path.insert(0, str(SKILL))
import gifcheck
exec((SKILL / "tablet-drawing.py").read_text())   # frame(), add_light(), all_lights(), the colors

FPS = 10                                          # the tablet's; a GIF keeps 100 ms a frame exact
OUT = gifcheck.out(HERE / "{out}")   # where the GIFs go without --check
WANT = sys.argv[1:]

def key(n): return (n // 5, n % 5)                # tablet button number -> the drawing's (row, col)

def lit(on):
    """{{button: (color, strength 0-1)}} -> the drawing's lights, all four of each button's"""
    L = {{}}
    for n, (c, s) in on.items(): all_lights(L, key(n), c, s)
    return L

def gif(name, fr, at=0.0):
    """writes name.gif and its still, name.png (the frame at seconds), then checks the GIF"""
    if WANT and name not in WANT: return
    OUT.mkdir(parents=True, exist_ok=True)
    fr[0].save(OUT / f"{{name}}.gif", save_all=True, append_images=fr[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    fr[min(round(at * FPS), len(fr) - 1)].save(OUT / f"{{name}}.png")
    print(OUT / f"{{name}}.gif", len(fr), "frames")
    gifcheck.check(OUT / f"{{name}}.gif", len(fr), FPS)

def frames(s, f): return [f(i / FPS) for i in range(round(s * FPS))]

gif("starter", frames(2.0, lambda t: frame(lit({{0: (GREEN, 1.0)}}))))
'''


def check(gen, names):
    gen = pathlib.Path(gen).resolve()
    CHECKED.mkdir(parents=True, exist_ok=True)
    mine = pathlib.Path(tempfile.mkdtemp(prefix=f"{gen.stem}-", dir=CHECKED))
    p = subprocess.run([sys.executable, gen, "--check", *names], capture_output=True, text=True,
                       env={**ENV, "GIFCHECK_DIR": str(mine)})
    print(p.stdout, end="", flush=True); print(p.stderr, end="", file=sys.stderr, flush=True)
    if p.returncode:
        print(f"FAIL {gen.name} exited {p.returncode}", file=sys.stderr); return 1
    gifs = sorted(mine.rglob("*.gif"))
    if not gifs:
        print(f"FAIL {gen.name} wrote no GIF to {mine}", file=sys.stderr); return 2
    if missing := [n for n in names if n not in {g.stem for g in gifs}]:
        print(f"FAIL no GIF named {', '.join(missing)}: {gen.name}'s docstring names its GIFs", file=sys.stderr); return 2
    failed = 0
    for g in gifs:
        s = subprocess.run([sys.executable, HERE / "sheet.py", g], capture_output=True, text=True, env=ENV)
        if s.returncode: failed += 1
        print(f"  sheet  {s.stdout.strip()}" if s.returncode == 0 else f"  sheet  {g.name} failed: {s.stderr.strip()} <<")
    return 1 if failed or "<<" in p.stdout else 0


def run(gen, names):
    return subprocess.run([sys.executable, pathlib.Path(gen).resolve(), *names], env=ENV).returncode


def sheet(args):
    return subprocess.run([sys.executable, HERE / "sheet.py", *args], env=ENV).returncode


def new(path, out=None):
    path = pathlib.Path(path).resolve()
    out = os.path.relpath(pathlib.Path(out).resolve(), path.parent) if out else "gifs"
    if path.exists():
        print(f"{path} exists; left as it is", file=sys.stderr); return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER.format(skill=HERE, out=out))
    print(path); return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "check": sys.exit(check(a[1], a[2:]))
    if len(a) >= 2 and a[0] == "run": sys.exit(run(a[1], a[2:]))
    if len(a) >= 1 and a[0] == "sheet": sys.exit(sheet(a[1:]))
    if len(a) in (2, 3) and a[0] == "new": sys.exit(new(*a[1:]))
    print(__doc__.split("\n\n", 1)[1], file=sys.stderr); sys.exit(3)
