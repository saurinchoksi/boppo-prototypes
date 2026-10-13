#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""studio_chat.py's Job, with studio_claude.py's Fake for Claude, on a temp folder: versions
written as they arrive, the retry, a stop, a timeout, the conversations saved, the names it holds. Run it (uv brings
Python); check.sh's studio part runs every tests/test_*.py here."""
import json, pathlib, sys, tempfile, time, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import animation, studio_chat, studio_claude, studio_store

WAIT = 10                                       # s; a job on the fake ends in well under one
ANIM = {"seconds": 2.0, "blocks": [{"button": 5, "start": 0, "end": 1, "color": [0, 255, 0]}]}


def tag(name, n=1): return f'<version name="{name}" note="take {n}">{json.dumps({**ANIM, "seconds": 1.0 + n})}</version>'


BATCH = '<batch size="3"/>Three takes.' + tag("slow", 1) + tag("fast", 2) + tag("slow", 3)


class Job(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = pathlib.Path(self.tmp.name)
        self.store = studio_store.Store(self.dir)
        self.store.save("orig", ANIM)

    def tearDown(self): self.tmp.cleanup()

    def run_job(self, replies, message="try three", fake=None, **req):
        self.fake = fake or studio_claude.Fake(replies)
        job = studio_chat.Job(self.store, {"owner": "orig", "name": "orig", "anim": ANIM, "message": message, **req}, self.fake)
        job.start()
        self.assertTrue(job.finished.wait(WAIT), "the job didn't end")
        return job

    def events(self, job, kind=None): return [e for e in job.state(0)["events"] if kind in (None, e["type"])]

    def test_batch(self):
        """a batch's versions written as they come, each from the owner, numbered, named apart"""
        job = self.run_job([{"text": BATCH, "piece": 9, "delay": 0}])
        self.assertEqual([e["type"] for e in self.events(job)], ["batch", "version", "version", "version", "done"])
        self.assertEqual(self.events(job, "batch")[0], {"type": "batch", "id": job.batch, "size": 3, "request": "try three"})
        names = [e["name"] for e in self.events(job, "version")]
        self.assertEqual(names, ["slow", "fast", "slow 2"])
        for n, name in enumerate(names, 1):
            a = self.store.load(name)
            self.assertEqual((a["seconds"], a["batch"]["from"], a["batch"]["n"], a["batch"]["note"], a["batch"]["id"]),
                             (1.0 + n, "orig", n, f"take {n}", job.batch))
        self.assertEqual([n for _, n, _ in self.store.versions(job.batch)], names)
        self.assertEqual(job.state(0)["reply"], "Three takes.")

    def test_chat_saved(self):
        """the owner's conversation, and a copy for each version, with the new session"""
        self.store.save_chat("orig", {"session": "s0", "messages": [{"role": "you", "text": "earlier"}]})
        job = self.run_job([BATCH])
        chat = self.store.chat("orig")
        self.assertEqual(chat["session"], "fake-1")
        self.assertEqual(chat["messages"][-2:], [{"role": "you", "text": "try three"},
                         {"role": "claude", "text": "Three takes.", "batch": job.batch, "versions": 3, "questions": None, "error": None}])
        for name in ("slow", "fast", "slow 2"): self.assertEqual(self.store.chat(name), chat)
        self.assertEqual(self.fake.calls[0][1], "s0")
        self.assertIn("The designer says: try three", self.fake.calls[0][0])

    def test_expired_session(self):
        """a resumed session that fails before a word: asked once more, fresh, told the gist"""
        self.store.save_chat("orig", {"session": "gone", "messages": [{"role": "you", "text": "make it green"}]})
        job = self.run_job([{"error": "Claude: No conversation found with session ID: gone"}, tag("green")])
        self.assertEqual([c[1] for c in self.fake.calls], ["gone", None])
        self.assertTrue(self.fake.calls[1][0].startswith("Earlier in this conversation:\nyou: make it green\n\n"))
        self.assertEqual(self.events(job, "error"), [])
        self.assertEqual(self.store.chat("orig")["session"], "fake-2")
        self.assertTrue(self.store.exists("green"))

    def test_retried_once(self):
        """it fails again: one error, no third try, and neither failed run's new (empty) session kept"""
        self.store.save_chat("orig", {"session": "gone", "messages": []})
        job = self.run_job([{"error": "Claude: first"}, {"error": "Claude: second"}, tag("never")])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Claude: second"])
        self.assertEqual(self.store.chat("orig")["session"], "gone")

    def test_error_saved(self):
        """a run that only fails: its error kept in the conversation, for the page to show"""
        self.run_job([{"error": "Claude: overloaded"}])
        last = self.store.chat("orig")["messages"][-1]
        self.assertEqual((last["role"], last["text"], last["error"]), ("claude", "", "Claude: overloaded"))
        self.assertIsNone(self.store.chat("orig")["session"])

    def test_failed_after_words(self):
        """one that fails partway: what it said, its error, and its session (which holds them)"""
        job = self.run_job([{"text": "Halfway.", "error": "Claude: API Error: 529"}])
        last = self.store.chat("orig")["messages"][-1]
        self.assertEqual((last["text"], last["error"]), ("Halfway.", "Claude: API Error: 529"))
        self.assertEqual(self.store.chat("orig")["session"], "fake-1")
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Claude: API Error: 529"])

    def test_no_session_no_retry(self):
        job = self.run_job([{"error": "Claude: overloaded"}, tag("never")])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Claude: overloaded"])

    def test_bad_version(self):
        """one that can't be read is skipped, said so, and the rest written"""
        job = self.run_job(['<version name="bad">{"seconds": </version>' + tag("good", 2)])
        self.assertEqual([e["type"] for e in self.events(job)], ["error", "batch", "version", "done"])
        self.assertIn("Version 1 didn't come out readable", self.events(job, "error")[0]["text"])
        self.assertEqual(self.events(job, "version")[0]["n"], 2)
        self.assertEqual(self.store.chat("orig")["messages"][-1]["versions"], 1)

    def test_questions(self):
        job = self.run_job(["Some questions.<question>How fast? (slow, quick)</question><question>Which row?</question>"],
                           message="more fun")
        self.assertEqual(self.events(job, "questions"), [{"type": "questions", "questions": ["How fast? (slow, quick)", "Which row?"], "request": "more fun"}])
        last = self.store.chat("orig")["messages"][-1]
        self.assertEqual((last["text"], last["batch"]), ("Some questions.\n1. How fast? (slow, quick)\n2. Which row?", None))

    def test_stop(self):
        """a stop ends the run, returns once the conversation is saved, and is no error"""
        fake = studio_claude.Fake([{"text": BATCH, "piece": 30, "delay": 0.05}])
        job = studio_chat.Job(self.store, {"owner": "orig", "message": "go"}, fake); job.start()
        deadline = time.monotonic() + WAIT
        while not self.events(job, "version") and time.monotonic() < deadline: time.sleep(0.01)
        self.assertTrue(job.stop())
        self.assertTrue(job.done)
        self.assertEqual(self.events(job, "error"), [])
        chat = self.store.chat("orig")
        self.assertEqual((chat["session"], chat["messages"][-1]["versions"]), (None, len(self.events(job, "version"))))
        self.assertLess(len(self.events(job, "version")), 3)

    def test_stop_before_start(self):
        job = studio_chat.Job(self.store, {"owner": "orig", "message": "go"}, studio_claude.Fake([BATCH]))
        job.stopped = True; job.start()
        self.assertTrue(job.finished.wait(WAIT))
        self.assertEqual(self.store.chat("orig")["messages"][-1]["text"], "(stopped)")

    def test_timeout(self):
        """still running at TIMEOUT: stopped, and said so"""
        with mock.patch.object(studio_chat, "TIMEOUT", 0.6):         # "Three takes." in, no version yet
            job = self.run_job([{"text": BATCH, "piece": 5, "delay": 0.05}])
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Stopped after 0.01 minutes."])
        last = self.store.chat("orig")["messages"][-1]
        self.assertEqual((last["text"], last["error"]), ("Three takes.", "Stopped after 0.01 minutes."))

    def test_timeout_no_retry(self):
        """a resumed session still silent at TIMEOUT: stopped, not tried again"""
        self.store.save_chat("orig", {"session": "s0", "messages": []})
        with mock.patch.object(studio_chat, "TIMEOUT", 0.3):
            job = self.run_job([{"error": "Claude: never", "delay": 5}, tag("never")])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Stopped after 0.005 minutes."])

    def test_retry_shares_budget(self):
        """the retry gets what's left of TIMEOUT, not its own; one that ends in time is no error"""
        self.store.save_chat("orig", {"session": "gone", "messages": []})
        with mock.patch.object(studio_chat, "TIMEOUT", 0.9):
            job = self.run_job([{"error": "Claude: No conversation found", "delay": 0.5}, {"text": tag("late"), "piece": 400, "delay": 0.7}])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertFalse(self.store.exists("late"))
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["Stopped after 0.015 minutes."])
        self.store.save_chat("orig", {"session": "gone", "messages": []})
        with mock.patch.object(studio_chat, "TIMEOUT", 0.9):
            job = self.run_job([{"error": "Claude: No conversation found", "delay": 0.5}, {"text": tag("quick"), "piece": 400, "delay": 0.1}])
        self.assertEqual(self.events(job, "error"), [])
        self.assertTrue(self.store.exists("quick"))

    def test_holds(self):
        """while it runs, the owner and the versions written so far can't be renamed or deleted (it
        saves their conversations at the end); anything else can, and all of them once it's done"""
        fake = studio_claude.Fake([{"text": BATCH, "piece": 30, "delay": 0.05}])
        job = studio_chat.Job(self.store, {"owner": "orig", "message": "go"}, fake); job.start()
        deadline = time.monotonic() + WAIT
        while not self.events(job, "version") and time.monotonic() < deadline: time.sleep(0.01)
        self.assertIn("a request about orig", job.holds("orig"))
        self.assertIn("the request that made slow", job.holds("slow"))
        self.assertIsNone(job.holds("other"))
        self.assertTrue(job.finished.wait(WAIT))
        self.assertEqual([job.holds(n) for n in ("orig", "slow")], [None, None])

    def test_unavailable(self):
        """no Claude at all: said so, and no conversation saved"""
        class Missing(studio_claude.Fake):
            def ask(self, *a, **k): raise studio_claude.Unavailable("no claude here")
        job = self.run_job([], fake=Missing([]))
        self.assertEqual([e["text"] for e in self.events(job, "error")], ["no claude here"])
        self.assertFalse(self.store.chat_path("orig").exists())

    def test_script_runs_out(self):
        job = self.run_job([])
        self.assertIn("has no reply 1", self.events(job, "error")[0]["text"])

    def test_grid_in_prompt(self):
        """the batch on screen is told by number"""
        first = self.run_job([BATCH])
        self.run_job([tag("slower")], message="#2, but slower", grid=first.batch)
        text = self.fake.calls[0][0]
        self.assertIn('On screen, the batch from "try three":', text)
        self.assertIn('#2 "fast" (take 2):', text)


class Fake(unittest.TestCase):
    def test_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump(["hi", {"text": "there", "error": None}], f); f.flush()
            fake = studio_claude.Fake.load(f.name)
            self.assertEqual(fake.status()["state"], "on")
            run = fake.ask("x"); self.assertEqual("".join(run), "hi"); self.assertEqual((run.session, run.error), ("fake-1", None))
            run = fake.ask("y"); self.assertEqual("".join(run), "there")
            f.seek(0); f.truncate(); f.write('{"replies": 1}'); f.flush()
            self.assertRaises(ValueError, studio_claude.Fake.load, f.name)
        run = studio_claude.Fake([{"error": "Claude: overloaded", "delay": 0}]).ask("x"); list(run)
        self.assertEqual((run.session, run.error), ("fake-1", "Claude: overloaded"))   # as claude -p's result has one


if __name__ == "__main__":
    unittest.main()
