#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""studio_claude.py's CLI against a stand-in `claude` on the PATH: a script that prints what
`claude -p --output-format stream-json` prints (canned), and can sleep, fail, leave a child holding
its output, or flood stderr. Then a Job on it, for the expired session's retry. The real `claude`
is never run. Run it (uv brings Python); check.sh's studio part runs every tests/test_*.py here."""
import json, os, pathlib, sys, tempfile, threading, time, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import studio_chat, studio_claude, studio_store

WAIT = 10                                       # s; every run here ends in well under one
STAND_IN = f"""#!{sys.executable}
# a stand-in claude: each run takes the next plan in plans.json
import json, os, pathlib, subprocess, sys, time
here = pathlib.Path(__file__).parent
n = len(list(here.glob("argv-*.json")))
plan = json.loads((here / "plans.json").read_text())[n]
(here / f"argv-{{n}}.json").write_text(json.dumps(sys.argv[1:]))
(here / f"stdin-{{n}}.txt").write_text(sys.stdin.read())
sys.stderr.write("x" * plan.get("flood", 0) + plan.get("stderr", "")); sys.stderr.flush()
if plan.get("child"):                           # a grandchild holding stdout; "session": out of our group
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=plan["child"] == "session")
    (here / "child.pid").write_text(str(p.pid))
for line in plan.get("lines", []): print(json.dumps(line), flush=True)
time.sleep(plan.get("sleep", 0))
sys.exit(plan.get("exit", 0))
"""


def delta(text): return {"type": "stream_event", "session_id": "s1", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}}


def result(text, session="s1", **k): return {"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": session, **k}


EXPIRED = {"lines": [{"type": "result", "subtype": "error_during_execution", "is_error": True, "num_turns": 0, "session_id": "new-empty",
                      "errors": ["No conversation found with session ID: gone"]}],             # claude -p's FD(), 2.1.296
           "stderr": "No conversation found with session ID: gone\n", "exit": 1}
HELLO = {"lines": [{"type": "system", "subtype": "init", "session_id": "s1"}, delta("Hel"), delta("lo."),
                   {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello."}]}}, result("Hello.")]}


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = pathlib.Path(self.tmp.name)
        exe = self.dir / "claude"; exe.write_text(STAND_IN); exe.chmod(0o755)
        patch = mock.patch.dict(os.environ, {"PATH": f"{self.dir}{os.pathsep}{os.environ['PATH']}"})
        patch.start(); self.addCleanup(patch.stop)
        self.cli = studio_claude.CLI()
        self.assertEqual(self.cli.exe(), str(exe))

    def tearDown(self):
        pid = self.dir / "child.pid"
        if pid.exists():
            try: os.kill(int(pid.read_text()), 9)
            except OSError: pass
        self.tmp.cleanup()

    def plans(self, *plans): (self.dir / "plans.json").write_text(json.dumps(plans))

    def run_it(self, run, stop_after=None):
        """the run's text, iterated on a thread (so a hang fails the test), and how long it took;
        stop_after: stopped at its first piece"""
        out, t = [], time.monotonic()
        def go():
            for piece in run:
                out.append(piece)
                if stop_after is not None: run.stop()
        th = threading.Thread(target=go, daemon=True); th.start(); th.join(WAIT)
        self.assertFalse(th.is_alive(), "the run didn't end")
        return "".join(out), time.monotonic() - t

    def test_text_and_session(self):
        """the deltas as they come, the session, and the argv: no tools, resumed as a fork; the
        message on stdin"""
        self.plans(HELLO)
        run = self.cli.ask("hi there", session="s0", model="opus", system="be brief")
        text, _ = self.run_it(run)
        self.assertEqual((text, run.session, run.error), ("Hello.", "s1", None))
        argv = json.loads((self.dir / "argv-0.json").read_text())
        for a in (["--tools", ""], ["--model", "opus"], ["--system-prompt", "be brief"], ["--resume", "s0", "--fork-session"]):
            self.assertIn(a, [argv[i:i + len(a)] for i in range(len(argv))])
        self.assertEqual((self.dir / "stdin-0.txt").read_text(), "hi there")

    def test_whole_answer(self):
        """no deltas came through: the result's text, whole"""
        self.plans({"lines": [result("All at once.")]})
        self.assertEqual(self.run_it(self.cli.ask("hi"))[0], "All at once.")

    def test_api_error(self):
        """an error result: its text, and its session (the caller decides whether to keep it)"""
        self.plans({"lines": [result("API Error: 529 Overloaded", is_error=True)], "exit": 1})
        run = self.cli.ask("hi"); text, _ = self.run_it(run)
        self.assertEqual((text, run.session, run.error), ("", "s1", "Claude: API Error: 529 Overloaded"))

    def test_expired_session(self):
        """resuming a session that's gone: its errors' text, not just error_during_execution"""
        self.plans(EXPIRED)
        run = self.cli.ask("hi", session="gone"); self.run_it(run)
        self.assertEqual((run.session, run.error), ("new-empty", "Claude: No conversation found with session ID: gone"))

    def test_exit_without_result(self):
        self.plans({"stderr": "one\ntwo\nthree\nfour: broke\n", "exit": 2})
        run = self.cli.ask("hi"); self.run_it(run)
        self.assertEqual(run.error, "claude exited 2: two\nthree\nfour: broke")

    def test_stderr_flood(self):
        """more on stderr than a pipe holds: still read to the end"""
        self.plans({**HELLO, "flood": 2_000_000})
        run = self.cli.ask("hi")
        self.assertEqual((self.run_it(run)[0], run.error), ("Hello.", None))

    def test_stop_ends_its_children(self):
        """a stop ends claude and what it started, at once, and is no error"""
        self.plans({"lines": [delta("Hel")], "child": "group", "sleep": 60})
        run = self.cli.ask("hi"); text, took = self.run_it(run, stop_after=0)
        self.assertEqual((text, run.error), ("Hel", None))
        self.assertLess(took, 2)
        child = int((self.dir / "child.pid").read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try: os.kill(child, 0); time.sleep(0.05)
            except ProcessLookupError: break
        else: self.fail("the grandchild outlived the stop")

    def test_stop_past_an_escaped_child(self):
        """a grandchild in its own session keeps stdout open: the stop still returns, DRAIN s on"""
        self.plans({"lines": [delta("Hel")], "child": "session", "sleep": 60})
        with mock.patch.object(studio_claude, "DRAIN", 0.5):
            run = self.cli.ask("hi"); text, took = self.run_it(run, stop_after=0)
        self.assertEqual((text, run.error), ("Hel", None))
        self.assertLess(took, 3)

    def test_job_retries_expired(self):
        """a Job on it: the gone session's run fails, the fresh one answers, and only its session is kept"""
        self.plans(EXPIRED, {"lines": [delta("Fresh."), result("Fresh.", session="s2")]})
        with tempfile.TemporaryDirectory() as d:
            store = studio_store.Store(pathlib.Path(d))
            store.save_chat("orig", {"session": "gone", "messages": [{"role": "you", "text": "make it green"}]})
            job = studio_chat.Job(store, {"owner": "orig", "message": "again"}, self.cli); job.start()
            self.assertTrue(job.finished.wait(WAIT))
            chat = store.chat("orig")
            self.assertEqual((chat["session"], chat["messages"][-1]["text"], chat["messages"][-1]["error"]), ("s2", "Fresh.", None))
        self.assertNotIn("--resume", json.loads((self.dir / "argv-1.json").read_text()))
        self.assertTrue((self.dir / "stdin-1.txt").read_text().startswith("Earlier in this conversation:\nyou: make it green\n"))


if __name__ == "__main__":
    unittest.main()
