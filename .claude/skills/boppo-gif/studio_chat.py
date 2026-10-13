"""Claude in the studio: the chat box's half on the server (studio.py routes to it).

A request goes to Claude (studio_claude.py: the Claude Code on this computer, `claude -p` on its own
login with no tools at all, or a scripted fake): Claude answers in text, studio_reply.py reads the
versions it describes, and the Job writes them into the studio's folder (studio_store.py), so
nothing else on the computer is touched. Claude never changes an animation; it makes versions,
grouped in a batch under the request.

Each animation keeps its conversation in the store (Claude Code's session id and the messages the
page shows); a version starts with a copy of the conversation it came from.
"""
import json, threading, time, traceback
import animation, studio_claude, studio_reply

TIMEOUT = 300                                      # s; a request still running then is stopped, its retry included
STOP_WAIT = 15                                     # s; a stop waits that long for the chat to be saved
MODELS = ("sonnet", "opus")
SYSTEM = f"""You design light animations for the Boppo tablet with a game designer, inside their \
GIF studio. You have no tools: you answer in text, and the studio turns your answer into animations.

The tablet: ten round buttons in two rows of five. Buttons 0-4 are the top row, 5-9 the bottom \
row (the kid's side), each left to right. Each button has four lights: top, left, right, bottom. \
Frames run at 10 a second, the tablet's rate, so times are in tenths of a second.

{animation.SCHEMA}

The rules:
1. You never change the animation that is open. You make versions of it (or new animations, when \
asked to start from scratch), and the designer picks.
2. How many: one version, unless alternatives are asked for or implied ("try a few", "some \
options", "versions"); then 3, or the number asked for, at most 6.
3. When the request doesn't say what to change ("more fun", "better", "make it pop"), ask first: \
one to three short questions, each ending with 2 to 4 short examples in parentheses, and no \
versions that turn. The designer types the answers in one message. Otherwise make the versions \
straight away.
4. Only what the format above can do. When an idea needs something it can't (a light gliding \
smoothly between buttons, say), make the closest it can, and say in one line what it couldn't.
5. "This", "these" and "here" mean the selected blocks or the playhead the message gives you. \
"#2" means version 2 of the batch on screen.

Answer in this shape, nothing else:
- First, when you make versions: <batch size="N"/>
- One or two plain sentences for the designer, no markdown.
- Each version: <version name="two or three words" note="one line on what it varies">{{the whole \
animation JSON}}</version>. No double quotes inside name or note.
- Or, to ask, each question in its own: <question>The question? (an example, another, a third)</question>
"""


# ---------- what Claude is told with each message ------------------------------------------------
def bare(anim): return {k: v for k, v in anim.items() if k != "batch"}


def prompt(store, req):
    anim, sel = req.get("anim") or {}, req.get("selection") or {}
    lines = [f'The open animation, "{req.get("name")}":', json.dumps(bare(anim))]
    if sel.get("items"):
        lines.append(f'Selected ({sel.get("kind")}): {json.dumps(sel["items"])}')
    else: lines.append("Nothing selected.")
    lines.append(f'Playhead: {float(req.get("playhead") or 0):.1f} s')
    if req.get("grid"):
        vs = store.versions(req["grid"])
        if vs:
            lines.append(f'On screen, the batch from "{vs[0][2]["batch"].get("request", "")}":')
            lines += [f'#{n} "{name}" ({a["batch"].get("note", "")}): {json.dumps(bare(a))}' for n, name, a in vs]
    lines.append(f'The designer says: {req.get("message", "")}')
    return "\n".join(lines)


# ---------- a request, running ---------------------------------------------------------------------
class Job:
    """one message to Claude: its versions written as they arrive, its events for the page"""

    def __init__(self, store, req, claude):
        self.store, self.req, self.claude = store, req, claude
        self.owner = req["owner"]
        self.model = req.get("model") if req.get("model") in MODELS else MODELS[0]
        self.batch = time.strftime("%Y%m%d-%H%M%S")
        self.request = (req.get("request") or req.get("message") or "")[:120]
        self.events, self.lock, self.finished = [], threading.Lock(), threading.Event()
        self.reply, self.versions = studio_reply.Reply(), []
        self.claude_run, self.stopped, self.timed_out = None, False, False

    @property
    def done(self): return self.finished.is_set()

    def written(self): return [v for v in self.versions if v]

    def holds(self, name):
        """why name can't be renamed or deleted yet (None when it can): running, it saves the owner's
        conversation and its versions' at the end, under the names they had"""
        if self.done or (name != self.owner and name not in self.versions): return None
        what = f"a request about {name}" if name == self.owner else f"the request that made {name}"
        return f"Claude is still on {what}: rename or delete it once that's done, or stopped"

    def emit(self, **e):
        with self.lock: self.events.append(e)

    def state(self, since):
        with self.lock:
            return {"owner": self.owner, "batch": self.batch, "events": self.events[since:],
                    "next": len(self.events), "reply": self.reply.visible(), "done": self.done}

    def stop(self, wait=STOP_WAIT):
        """ends the request; returns once its conversation is saved, or wait s on (False then)"""
        with self.lock:
            self.stopped = True; run = self.claude_run
        if run: run.stop()
        return self.finished.wait(wait)

    def timeout(self):
        with self.lock:
            self.timed_out = True; run = self.claude_run
        if run: run.stop()

    def start(self): threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try: self.talk()
        except studio_claude.Unavailable as e: self.emit(type="error", text=str(e))
        except Exception as e:
            traceback.print_exc(); self.emit(type="error", text=f"{type(e).__name__}: {e}")
        finally:
            self.finished.set(); self.emit(type="done")

    def talk(self):
        chat = self.store.chat(self.owner)
        chat["messages"].append({"role": "you", "text": self.req.get("message", "")})
        text = prompt(self.store, self.req)
        watchdog = threading.Timer(TIMEOUT, self.timeout); watchdog.start()   # one budget for both tries
        try:
            session, error = self.ask(text, chat.get("session"))
            if error and chat.get("session") and not self.reply.text and not self.stopped and not self.timed_out:
                # its session is gone (another computer, a cleared ~/.claude): start again, told the gist
                gist = "\n".join(f'{m["role"]}: {m["text"]}' for m in chat["messages"][-11:-1])
                session, error = self.ask(f"Earlier in this conversation:\n{gist}\n\n{text}", None)
        finally: watchdog.cancel()
        if self.timed_out and not self.stopped: error = f"Stopped after {TIMEOUT / 60:g} minutes."
        if error: self.emit(type="error", text=error)
        questions = self.reply.questions()
        if questions: self.emit(type="questions", questions=questions, request=self.request)
        listed = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))   # answered by typing, in one message
        chat["messages"].append({"role": "claude", "text": "\n".join(t for t in (self.reply.visible(done=True), listed) if t)
                                 or ("(stopped)" if self.stopped else ""),
                                 "batch": self.batch if self.written() else None,
                                 "versions": len(self.written()), "questions": questions or None,
                                 "error": error})
        if session: chat["session"] = session
        self.store.save_chat(self.owner, chat)
        for name in self.written(): self.store.save_chat(name, chat)   # a version carries on its conversation

    def ask(self, text, session):
        """one run of Claude; its session id, kept when it went well or said something (a run that
        failed before a word has a new, empty one), and an error, if any"""
        if self.stopped or self.timed_out: return None, None
        run = self.claude.ask(text, session=session, model=self.model, system=SYSTEM)
        with self.lock:
            self.claude_run = run; late = self.stopped or self.timed_out
        if late: run.stop()                             # a stop that came while it started
        said = len(self.reply.text)
        try:
            for delta in run:
                with self.lock: found = self.reply.feed(delta)
                for kind, x in found:
                    if kind == "size": self.emit(type="batch", id=self.batch, size=x, request=self.request)
                    else: self.write(x)
        finally: run.stop()
        error = None if self.stopped or self.timed_out else run.error
        return (run.session if not error or len(self.reply.text) > said else None), error

    def write(self, v):
        if v["anim"] is None:
            self.versions.append(None)
            return self.emit(type="error", text=f"Version {v['n']} didn't come out readable ({v['error']}); skipped.")
        v["anim"]["batch"] = {"id": self.batch, "request": self.request, "from": self.owner, "n": v["n"], "note": v["note"]}
        name = self.store.unique(v["name"] or f"{self.owner} {v['n']}")
        self.versions.append(name)                      # held before it's on disk: see holds()
        anim, _ = self.store.save(name, v["anim"])
        self.emit(type="version", name=name, n=v["n"], note=anim["batch"]["note"])
