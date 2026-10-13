"""The studio's folder: its animations, their exports and their conversations, kept by one set of
rules. studio.py's routes and studio_chat.py's Job go through it; nothing else touches the folder.

  <name>.json        an Animation (animation.py), cleaned on every read and write
  <name>.gif, .png   its export and its still, once exported
  .chat/<name>.json  its conversation with Claude: {"session", "messages"}

A name is letters, digits, spaces and _ . - (NAME); a name that isn't raises ValueError. The
server's threads share one Store, and its writes take turns (its lock).
"""
import json, pathlib, re, threading
import animation
from animation import write_text

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,80}\Z")
NAME_CHARS = re.compile(r"[^A-Za-z0-9 _.-]+")
EXPORTS = (".gif", ".png")                         # an animation's files besides its JSON


class Exists(Exception):
    """a rename onto a name that's taken"""


class Store:
    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.lock = threading.Lock()                   # held by every write; waits only on another one's disk work

    def path(self, name, ext=".json"):
        if not isinstance(name, str) or not NAME.match(name): raise ValueError(f"not a name: {name!r}")
        return self.folder / f"{name}{ext}"

    def chat_path(self, name): return self.folder / ".chat" / f"{self.path(name).stem}.json"

    # ---------- the animations ----------------------------------------------------------------
    def exists(self, name): return self.path(name).exists()

    def list(self):
        """every animation, newest first: {"name", "mtime", "anim" (cleaned; empty when unreadable),
        "gif" (exported)}"""
        out = []
        for p in self.folder.glob("*.json"):
            try: a = animation.read(p)
            except (OSError, ValueError): a = animation.clean({})
            try: mtime = p.stat().st_mtime
            except OSError: continue                   # gone since the glob
            out.append({"name": p.stem, "mtime": mtime, "anim": a, "gif": p.with_suffix(".gif").exists()})
        return sorted(out, key=lambda e: e["mtime"], reverse=True)

    def load(self, name):
        """its Animation, cleaned; FileNotFoundError when there's none, ValueError when unreadable"""
        return animation.read(self.path(name))

    def save(self, name, anim):
        """anim cleaned and written whole; what was written, and its mtime"""
        p = self.path(name)
        with self.lock: return animation.write(p, anim), p.stat().st_mtime

    def delete(self, name):
        """its JSON and its conversation; its exported GIF and still stay"""
        with self.lock:
            self.path(name).unlink(missing_ok=True)
            self.chat_path(name).unlink(missing_ok=True)

    def rename(self, old, new):
        """its JSON, GIF, still and conversation to the new name, and each version that came from it
        told so. The new name is taken when it has a JSON or a conversation; an export there (one a
        delete left) is replaced by old's, as exporting to it would, or stays. Everything is checked
        before anything moves; a move that fails puts back the ones before it. Exists when the new
        name is taken, FileNotFoundError when old has no JSON."""
        src, chat = (self.path(old), self.path(new)), (self.chat_path(old), self.chat_path(new))
        with self.lock:
            if not src[0].exists(): raise FileNotFoundError(f"no animation {old!r}")
            taken = [b for a, b in (src, chat) if b.exists() and not (a.exists() and b.samefile(a))]   # samefile: a change of case
            if taken: raise Exists(f"{new} exists already ({taken[0].name})")
            moves = [src] + [(self.path(old, x), self.path(new, x)) for x in EXPORTS] + [chat]
            done = []
            try:
                for a, b in moves:
                    if a.exists(): a.replace(b); done.append((a, b))
            except OSError:
                for a, b in reversed(done): b.replace(a)
                raise
            for p in self.folder.glob("*.json"):       # its versions still know where they came from, each read as it's written
                try: a = animation.read(p)
                except (OSError, ValueError): continue
                if (a.get("batch") or {}).get("from") == old: a["batch"]["from"] = new; animation.write(p, a)

    def read_all(self):
        """each readable animation's path and Animation; an unreadable one is skipped"""
        out = []
        for p in self.folder.glob("*.json"):
            try: out.append((p, animation.read(p)))
            except (OSError, ValueError): pass
        return out

    def versions(self, batch_id):
        """a Batch's versions, in its order: (n, name, Animation)"""
        vs = [(a["batch"]["n"], p.stem, a) for p, a in self.read_all() if (a.get("batch") or {}).get("id") == batch_id]
        return sorted(vs, key=lambda v: v[0])

    def unique(self, base, limit=60, fallback="version"):
        """base made a name no animation or export has: its odd characters gone, cut to limit, and
        " 2", " 3"... added, the cut leaving room for it"""
        base = re.sub(r"\s+", " ", NAME_CHARS.sub(" ", base)).strip(" .-_")
        cut = lambda s, n: s[:n].rstrip(" .-_") or fallback
        name, i = cut(base, limit), 2
        while any(self.path(name, x).exists() for x in (".json",) + EXPORTS):
            name = f"{cut(base, limit - len(f' {i}'))} {i}"; i += 1
        return name

    # ---------- the conversations ------------------------------------------------------------
    def chat(self, name):
        try: c = json.loads(self.chat_path(name).read_text())
        except (OSError, ValueError): c = None
        return c if isinstance(c, dict) and isinstance(c.get("messages"), list) else {"session": None, "messages": []}

    def save_chat(self, name, chat):
        p = self.chat_path(name)
        with self.lock: p.parent.mkdir(exist_ok=True); write_text(p, json.dumps(chat, indent=1) + "\n")
