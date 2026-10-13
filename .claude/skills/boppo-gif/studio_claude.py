"""Claude, as the studio's chat sees it: a port with two adapters.

  claude.ask(text, session, model, system) -> a Run: iterate it for the reply's text as it arrives;
      then run.session (to resume next time) and run.error (None when it went well or was stopped).
      run.stop() ends it early, from any thread. Unavailable when no Claude can answer at all.
  claude.status() -> {"state": "on" | "signed-out" | "signing-in" | "missing" | "unknown", ...}
  claude.login()  -> starts a sign-in, where there is one

CLI is the Claude Code on this computer (`claude -p`, on its own login, no tools). Fake replays a
script of canned replies, for the tests and for `studio.py --fake-claude <script.json>`:
  [reply, ...]  each request takes the next; a reply is its text, or
  {"text": "...", "error": "...", "delay": s before each piece (0.02), "piece": characters (40)}
  An "error" with no text is a failed run (an expired session, say); with no replies left, a run
  fails saying so. A run not stopped has a session, failed or not, as `claude -p`'s result does.
"""
import collections, json, os, pathlib, queue, shutil, signal, subprocess, tempfile, threading, time

STATUS_TIMEOUT = 15                                # s; `claude auth status` takes well under one
LOGIN_TIMEOUT = 300                                # s; a sign-in not finished then is stopped
EXIT_TIMEOUT = 10                                  # s; claude -p exits once its output closes
DRAIN = 3                                          # s; a stopped or exited run's output read that much longer
WORKDIR = pathlib.Path(tempfile.gettempdir()) / "boppo-studio-claude"   # no CLAUDE.md above it


class Unavailable(Exception):
    """no Claude to ask: the text says why, for the designer"""


# ---------- the real one: claude -p ------------------------------------------------------------
class CLI:
    def __init__(self): self.login_proc = None

    def exe(self): return shutil.which("claude")

    def status(self):
        """from Claude Code's own `claude auth status`"""
        exe = self.exe()
        if not exe: return {"state": "missing"}
        try:
            d = json.loads(subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True,
                                          timeout=STATUS_TIMEOUT).stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            return {"state": "unknown", "detail": f"{type(e).__name__}: {e}"}
        if d.get("loggedIn"): return {"state": "on", "plan": d.get("subscriptionType")}
        return {"state": "signing-in" if self.login_proc and self.login_proc.poll() is None else "signed-out"}

    def login(self):
        """Claude Code's sign-in (`claude auth login`), which opens the browser and waits for it"""
        exe = self.exe()
        if not exe or (self.login_proc and self.login_proc.poll() is None): return
        WORKDIR.mkdir(exist_ok=True)
        self.login_proc = p = subprocess.Popen([exe, "auth", "login"], cwd=WORKDIR, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def wait():
            try: p.wait(LOGIN_TIMEOUT)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
        threading.Thread(target=wait, daemon=True).start()

    def ask(self, text, session=None, model="sonnet", system=""):
        exe = self.exe()
        if not exe: raise Unavailable("Claude Code isn't installed here: the chat runs `claude`, "
                                      "and it isn't on the PATH (claude.com/claude-code).")
        args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
                "--model", model, "--system-prompt", system]
        if session: args += ["--resume", session, "--fork-session"]
        return CLIRun(args, text)


class CLIRun:
    """its own process group, so a stop ends whatever claude started too"""

    def __init__(self, args, text):
        WORKDIR.mkdir(exist_ok=True)
        self.text, self.session, self.error, self.stopped = text, None, None, None   # stopped: when
        self.proc = subprocess.Popen(args, cwd=WORKDIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)

    def stop(self):
        self.stopped = self.stopped or time.monotonic()
        if self.proc.returncode is None: self.kill()

    def kill(self):
        try: os.killpg(self.proc.pid, signal.SIGKILL)
        except OSError: pass                           # gone already

    def lines(self):
        """stdout's lines, read on a thread: once it's stopped or exited, only for DRAIN s more, as
        one left holding it (a grandchild in its own session) would keep it open"""
        q, ended = queue.Queue(), None
        def read():
            with self.proc.stdout:
                for line in self.proc.stdout: q.put(line)
            q.put(None)
        threading.Thread(target=read, daemon=True).start()
        while True:
            try: line = q.get(timeout=0.2)
            except queue.Empty:
                ended = ended or ((self.stopped or self.proc.poll() is not None) and time.monotonic())
                if ended and time.monotonic() - ended > DRAIN: return
                continue
            if line is None: return
            yield line

    def __iter__(self):
        err, said, result = collections.deque(maxlen=3), False, None
        def errors():
            with self.proc.stderr: err.extend(self.proc.stderr)
        errs = threading.Thread(target=errors, daemon=True); errs.start()
        try: self.proc.stdin.write(self.text); self.proc.stdin.close()
        except OSError: pass                           # killed already: its exit code says why
        for line in self.lines():
            try: d = json.loads(line)
            except ValueError: continue
            if d.get("type") == "stream_event":
                delta = d.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta": said = True; yield delta["text"]
            elif d.get("type") == "result":            # the last line; an error's has a session too
                self.session, result = d.get("session_id"), d.get("result")
                if d.get("is_error"): self.error = f"Claude: {result or '; '.join(d.get('errors') or []) or d.get('subtype')}"
                break
        try: self.proc.wait(EXIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.kill()
            try: self.proc.wait(EXIT_TIMEOUT)
            except subprocess.TimeoutExpired: pass
        if result and not said and not self.error: yield result   # no deltas came through: the whole answer
        code = self.proc.returncode
        if self.stopped: self.error = None
        elif code and not self.error:
            errs.join(1)                               # its last words, when they're still coming
            self.error = f"claude exited {code}: {''.join(err).strip()}"


# ---------- the scripted one ------------------------------------------------------------------
class Fake:
    """replays canned replies in order; calls keeps each ask's (text, session, model)"""

    def __init__(self, replies, source="the script"):
        self.replies, self.source, self.calls, self.lock = list(replies), source, [], threading.Lock()

    @classmethod
    def load(cls, path):
        replies = json.loads(pathlib.Path(path).read_text())
        if not isinstance(replies, list): raise ValueError(f"{path}: a fake Claude's script is a list of replies")
        return cls(replies, str(path))

    def status(self): return {"state": "on", "plan": "fake"}

    def login(self): pass

    def ask(self, text, session=None, model="sonnet", system=""):
        with self.lock:
            self.calls.append((text, session, model))
            n = len(self.calls)
            reply = self.replies[n - 1] if n <= len(self.replies) else {"error": f"The fake Claude has no reply {n}: {self.source} has {len(self.replies)}."}
        return FakeRun(reply if isinstance(reply, dict) else {"text": reply}, f"fake-{n}")


class FakeRun:
    def __init__(self, reply, session):
        self.reply, self.session, self.error, self.stopped = reply, None, None, threading.Event()
        self.new_session = session

    def stop(self): self.stopped.set()

    def __iter__(self):
        text, piece, delay = self.reply.get("text", ""), int(self.reply.get("piece", 40)), float(self.reply.get("delay", 0.02))
        for i in range(0, len(text), piece):
            if self.stopped.wait(delay): return
            yield text[i:i + piece]
        if self.stopped.wait(0 if text else delay): return   # one that fails before a word takes delay too
        self.error, self.session = self.reply.get("error"), self.new_session
