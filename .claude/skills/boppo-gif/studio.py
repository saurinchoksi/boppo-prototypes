#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10.1", "numpy"]
# ///
"""The studio: a page for drawing a light animation on a timeline, with the tablet drawing
(tablet-drawing.py) drawing every frame, so what it shows is what a generator's GIF shows.

Usage: studio.py [<folder>] [--port N] [--no-open] [--fake-claude <script.json>]
  <folder>  where the animations live, one <name>.json each, and their GIFs once exported
            (<name>.gif and its still <name>.png); default ./studio, made if missing
  --fake-claude  the chat box answered from a script of canned replies, not Claude, fast and the
            same each run (for a demo tour's dry run); studio_claude.py says the script's shape
  Serves http://127.0.0.1:8765/ (only to this computer) and opens it. Ctrl-C stops it.

The chat box along the bottom is Claude, through the Claude Code on this computer (studio_chat.py):
it never changes an animation, it writes versions, a batch of them per request, and the page shows
a batch as a grid. A dot by the chat box says Claude is on; signed out, a Sign in button opens Claude
Code's sign-in in the browser. Without Claude Code the rest of the studio works as before.

An animation is a JSON file anything can write, Claude included: the page picks up a new or
changed one within two seconds. It has a length, blocks (a button's lights from a start to an end,
in a color, a level and an effect), presses, captions and a still; button 0-4 is the top row, 5-9
the bottom row (the kid's side), each left to right. The format is animation.py's, and --help ends
with it: the studio cleans every file it reads or writes with it, a value out of range clamped, a
missing one its default, a block it can't draw left out.
Frames are 10 a second, the tablet's: each frame is a framebuffer of the 40 lights, drawn."""
import errno, importlib.util, io, json, math, os, pathlib, sys, threading, time, traceback, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageDraw, ImageFont

USAGE = __doc__.split("\n\n", 1)[1]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import animation, gifcheck, studio_chat, studio_claude, studio_store
spec = importlib.util.spec_from_file_location("tablet_drawing", HERE / "tablet-drawing.py")
spec.loader.exec_module(drawing := importlib.util.module_from_spec(spec))   # frame(), the drawing's W, H and colors

FPS, LIGHTS = animation.FPS, animation.LIGHTS
ROUNDED = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
SHEET_COLS = 10                                         # frames a row in the page's sprite sheet


def drawn(fb):
    """a framebuffer as the drawing's lights: each light its color's hue at its brightness"""
    lights = {}
    for i, c in enumerate(fb):
        if max(c) > 0:
            lights.setdefault((i // 20, (i // 4) % 5), {})[LIGHTS[i % 4]] = (tuple(int(v * 255 / max(c)) for v in c), max(c) / 255)
    return lights


def font(size):
    try: return ImageFont.truetype(ROUNDED, size)
    except OSError: return ImageFont.load_default(size)


def draw(anim, t):
    """one frame of the animation at t seconds"""
    presses = {}
    for p in anim["presses"]:
        if p["start"] <= t < p["end"]: presses[(p["button"] // 5, p["button"] % 5)] = 1.0
    im = drawing.frame(drawn(animation.framebuffer(anim, t)), presses)
    for c in anim["captions"]:
        if c["start"] <= t < c["end"] and c["text"]:
            size = 40
            while size > 18 and font(size).getlength(c["text"]) > drawing.W - 48: size -= 2
            ImageDraw.Draw(im).text((drawing.W / 2, 28), c["text"], font=font(size), fill=drawing.INK, anchor="mm")
    return im


def frames(anim):
    """every frame of an Animation clean() made"""
    n = max(1, round(anim["seconds"] * FPS))
    return [draw(anim, i / FPS) for i in range(n)]


def sheet(anim):
    """every frame in one PNG, SHEET_COLS a row, for the page to play and scrub"""
    fr = frames(anim)
    rows = math.ceil(len(fr) / SHEET_COLS)
    im = Image.new("RGB", (drawing.W * min(SHEET_COLS, len(fr)), drawing.H * rows), drawing.BG)
    for i, f in enumerate(fr): im.paste(f, ((i % SHEET_COLS) * drawing.W, (i // SHEET_COLS) * drawing.H))
    out = io.BytesIO(); im.save(out, "PNG", compress_level=1)
    return out.getvalue(), len(fr)


def batch_gif(versions, path):
    """a batch as one GIF: its versions side by side at half size, numbered, each looping"""
    tw, th = drawing.W // 2, drawing.H // 2
    cols = len(versions) if len(versions) <= 3 else 2 if len(versions) == 4 else 3
    rows = math.ceil(len(versions) / cols)
    films = [[f.resize((tw, th), Image.LANCZOS) for f in frames(a)] for _, _, a in versions]
    out = []
    for i in range(max(len(f) for f in films)):
        im = Image.new("RGB", (tw * cols, th * rows), drawing.BG); d = ImageDraw.Draw(im)
        for k, ((n, _, _), film) in enumerate(zip(versions, films)):
            x, y = (k % cols) * tw, (k // cols) * th
            im.paste(film[i % len(film)], (x, y))
            d.text((x + 14, y + 10), f"#{n}", font=font(22), fill=drawing.INK)
        out.append(im)
    out[0].save(path, "GIF", save_all=True, append_images=out[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    return len(out)


def export(anim, gif):
    """an animation's GIF and its still, beside each other"""
    data, fr = gif_bytes(anim); gif.write_bytes(data)
    png = gif.with_suffix(".png")
    fr[min(round(anim["still"] * FPS), len(fr) - 1)].save(png, optimize=True)
    print(gif, len(fr), "frames"); gifcheck.check(gif, len(fr), FPS)
    return png, len(fr)


def gif_bytes(anim, width=None):
    """the animation as a GIF, and its frames; width: smaller, for the page's list"""
    fr = frames(anim); out = io.BytesIO()
    if width: fr = [f.resize((width, round(drawing.H * width / drawing.W)), Image.LANCZOS) for f in fr]
    fr[0].save(out, "GIF", save_all=True, append_images=fr[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    return out.getvalue(), fr


class Studio(BaseHTTPRequestHandler):
    store: studio_store.Store
    claude = studio_claude.CLI()                        # or a Fake, --fake-claude
    job = None                                          # the chat's request, running or last run

    def log_message(self, *a): pass

    def send(self, code, body=b"", kind="application/json", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def json(self, obj, code=200): self.send(code, json.dumps(obj).encode())

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def route(self, method):
        from urllib.parse import unquote, parse_qs
        path, _, q = self.path.partition("?")
        parts, query = [unquote(p) for p in path.split("/") if p], parse_qs(q)
        if method == "GET" and not parts:
            page = (HERE / "studio.html").read_text().replace("__FORMAT__", json.dumps(animation.page()).replace("<", "\\u003c"))
            return self.send(200, page.encode(), "text/html; charset=utf-8")
        if method == "GET" and parts == ["favicon.ico"]: return self.send(204)
        if method == "GET" and parts in (["studio-doc.js"], ["studio-timeline.js"], ["studio-session.js"]): return self.send(200, (HERE / parts[0]).read_bytes(), "text/javascript; charset=utf-8")
        store = self.store
        if method == "GET" and parts == ["api", "list"]:
            # the rail's rows: each one's batch, and its timeline as a strip of [button, start, end, color]
            return self.json([{"name": e["name"], "mtime": e["mtime"], "batch": e["anim"].get("batch"), "seconds": e["anim"]["seconds"],
                               "strip": [[b["button"], b["start"], b["end"], b["color"]] for b in e["anim"]["blocks"]],
                               "gif": e["gif"]} for e in store.list()])
        if len(parts) == 3 and parts[:2] == ["api", "anim"]:
            name = parts[2]
            if method == "GET": return self.json(store.load(name)) if store.exists(name) else self.json({"error": "no such"}, 404)
            if method == "PUT":
                _, mtime = store.save(name, self.body())
                return self.json({"saved": str(store.path(name)), "mtime": mtime})
            if method == "DELETE":
                if Studio.job and (held := Studio.job.holds(name)): return self.json({"error": held}, 409)
                store.delete(name); return self.json({"deleted": str(store.path(name))})
        if method == "POST" and len(parts) == 3 and parts[:2] == ["api", "rename"]:
            if Studio.job and (held := Studio.job.holds(parts[2])): return self.json({"error": held}, 409)
            new = self.body()["to"]
            try: store.rename(parts[2], new)
            except studio_store.Exists as e: return self.json({"error": str(e)}, 409)
            except FileNotFoundError as e: return self.json({"error": str(e)}, 404)
            return self.json({"renamed": new, "mtime": store.path(new).stat().st_mtime})
        if method == "POST" and parts == ["api", "frames"]:
            png, n = sheet(animation.clean(self.body()))
            return self.send(200, png, "image/png", [("X-Frames", str(n)), ("X-Cols", str(SHEET_COLS)), ("X-W", str(drawing.W)), ("X-H", str(drawing.H))])
        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "thumb"]:
            width = min(720, max(120, int((query.get("w") or [240])[0])))
            data, _ = gif_bytes(store.load(parts[2]), width)
            return self.send(200, data, "image/gif")
        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "still"]:
            anim = store.load(parts[2])
            width = min(720, max(120, int((query.get("w") or [240])[0])))
            im = draw(anim, anim["still"]).resize((width, round(drawing.H * width / drawing.W)), Image.LANCZOS)
            out = io.BytesIO(); im.save(out, "PNG")
            return self.send(200, out.getvalue(), "image/png")
        if method == "POST" and len(parts) == 3 and parts[:2] == ["api", "export"]:
            gif = store.path(parts[2], ".gif"); png, n = export(animation.clean(self.body()), gif)
            return self.json({"gif": str(gif), "png": str(png), "frames": n})
        if method == "POST" and len(parts) == 3 and parts[:2] == ["api", "export-batch"]:
            versions = store.versions(parts[2])
            if not versions: return self.json({"error": "no such batch"}, 404)
            for _, name, a in versions: export(a, store.path(name, ".gif"))
            title = store.unique("batch " + versions[0][2]["batch"].get("request", ""), limit=70)
            gif = store.path(title, ".gif"); n = batch_gif(versions, gif)
            print(gif, n, "frames, the batch"); gifcheck.check(gif, n, FPS)
            return self.json({"gif": str(gif), "versions": len(versions)})
        # the chat box: whether Claude is ready, then one request at a time
        if method == "GET" and parts == ["api", "claude"]: return self.json(Studio.claude.status())
        if method == "POST" and parts == ["api", "claude", "login"]:
            Studio.claude.login(); return self.json(Studio.claude.status())
        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "chat"]:
            job = Studio.job
            running = job and not job.done and job.owner == parts[2]
            return self.json({**store.chat(parts[2]), "running": bool(running)})
        if method == "POST" and parts == ["api", "chat"]:
            if Studio.job and not Studio.job.done: return self.json({"error": "Claude is still on the last one"}, 409)
            req = self.body()
            if not studio_store.NAME.match(str(req.get("owner", ""))): return self.json({"error": "no animation to talk about"}, 400)
            Studio.job = studio_chat.Job(store, req, Studio.claude); Studio.job.start()
            print(f"chat: {req['owner']}: {req.get('message', '')[:80]}")
            return self.json({"batch": Studio.job.batch})
        if method == "GET" and parts == ["api", "job"]:
            if not Studio.job: return self.json({"error": "no request"}, 404)
            return self.json(Studio.job.state(int((query.get("since") or [0])[0])))
        if method == "POST" and parts == ["api", "job", "stop"]:
            return self.json({"stopped": Studio.job.stop() if Studio.job else True})
        self.json({"error": f"no route {method} {self.path}"}, 404)

    def handle_method(self, method):
        try: self.route(method)
        except Exception as e:
            traceback.print_exc()
            self.json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self): self.handle_method("GET")
    def do_PUT(self): self.handle_method("PUT")
    def do_POST(self): self.handle_method("POST")
    def do_DELETE(self): self.handle_method("DELETE")


def main(a):
    sys.stdout.reconfigure(line_buffering=True)          # its lines show as they happen, piped or not
    if "-h" in a or "--help" in a: print(USAGE + "\n\n" + animation.SCHEMA); return 0
    port = 8765
    if "--port" in a: i = a.index("--port"); port = int(a[i + 1]); del a[i:i + 2]
    if "--fake-claude" in a:
        i = a.index("--fake-claude")
        try: Studio.claude = studio_claude.Fake.load(a[i + 1])
        except (IndexError, OSError, ValueError) as e: print(f"studio: --fake-claude: {e}", file=sys.stderr); return 3
        del a[i:i + 2]
    show = "--no-open" not in a
    a = [x for x in a if x != "--no-open"]
    if len(a) > 1: print(USAGE, file=sys.stderr); return 3
    folder = pathlib.Path(a[0] if a else "studio").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    Studio.store = studio_store.Store(folder)
    try: server = ThreadingHTTPServer(("127.0.0.1", port), Studio)
    except OSError as e:
        if e.errno != errno.EADDRINUSE: raise
        print(f"studio: port {port} is taken, likely by a studio already running: open http://127.0.0.1:{port}/,"
              f" or start this one with --port {port + 1}", file=sys.stderr); return 1
    url = f"http://127.0.0.1:{port}/"
    fake = f", the chat answered from {Studio.claude.source}" if isinstance(Studio.claude, studio_claude.Fake) else ""
    print(f"studio: {url}  animations in {folder}{fake}  (Ctrl-C stops it)", flush=True)
    if show: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("studio: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
