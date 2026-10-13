#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The studio's server, run on a temp folder and a free port with a fake Claude: every file it reads
or writes is cleaned, so a bad one in the folder still lists, draws and opens; a rename takes its
files along; a chat request makes its versions. uv brings studio.py's Pillow."""
import json, os, pathlib, re, signal, socket, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import animation

START = 60                                      # s; uv may fetch Pillow and numpy the first time
TIMEOUT = 30                                    # s; a request, a GIF of a few seconds drawn included
VALID = {"seconds": 2.0, "blocks": [{"button": 3, "start": 0.0, "end": 1.5, "color": [0, 0, 255], "level": 0.8,
         "effect": "flash", "every": 0.5, "color2": [255, 0, 0], "fade_in": 0.2, "fade_out": 0.0, "lights": ["top", "bottom"]}],
         "presses": [{"button": 9, "start": 1.0, "end": 1.4}], "captions": [{"start": 0.0, "end": 1.0, "text": "Go!"}], "still": 1.0}
LONG = {**VALID, "seconds": 45.0, "blocks": [{**VALID["blocks"][0], "start": 32.0, "end": 40.0, "every": 12.0}],
        "captions": [{"start": 31.0, "end": 44.0, "text": "a line longer than a version's eighty characters, every one of them kept, up to its end"}]}
REPLIES = ['<batch size="2"/>Two.' + "".join(f'<version name="take" note="n{n}">{json.dumps(VALID)}</version>' for n in (1, 2))]


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.dir = pathlib.Path(cls.tmp.name) / "folder"
        script = pathlib.Path(cls.tmp.name) / "fake.json"; script.write_text(json.dumps(REPLIES))
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}"
        cls.proc = subprocess.Popen(["uv", "run", "--quiet", "--script", str(HERE / "studio.py"), str(cls.dir), "--port", str(port), "--no-open",
                                     "--fake-claude", str(script)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + START
        while True:                             # until it answers, it exits, or START runs out
            try: urllib.request.urlopen(cls.url + "/api/list", timeout=2); return
            except OSError as e: err = e
            if (code := cls.proc.poll()) is not None or time.monotonic() > deadline:
                out = cls.stop(); cls.tmp.cleanup()
                why = f"exited {code}" if code is not None else f"didn't answer in {START} s ({err})"
                raise RuntimeError(f"studio.py {why}; it printed:\n{out}")
            time.sleep(0.2)

    @classmethod
    def stop(cls):
        """studio.py and its uv stopped, running or not; what they printed"""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try: os.killpg(cls.proc.pid, sig)
            except ProcessLookupError: pass     # gone already
            try: return cls.proc.communicate(timeout=10)[0].decode(errors="replace")
            except subprocess.TimeoutExpired: pass
        return cls.proc.communicate(timeout=10)[0].decode(errors="replace")

    @classmethod
    def tearDownClass(cls): cls.stop(); cls.tmp.cleanup()

    def test_a_taken_port_says_so(self):
        """a second studio on the same port: one plain line naming the next port, not a traceback"""
        port = self.url.rsplit(":", 1)[1]
        r = subprocess.run(["uv", "run", "--quiet", "--script", str(HERE / "studio.py"), str(self.dir), "--port", port, "--no-open"],
                           capture_output=True, text=True, timeout=START)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"port {port} is taken", r.stderr); self.assertIn(f"--port {int(port) + 1}", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def ask(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + path, data, method=method), timeout=TIMEOUT) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e: return e.code, e.headers.get("Content-Type"), e.read()

    def test_page(self):
        code, kind, html = self.ask("/")
        self.assertEqual((code, kind), (200, "text/html; charset=utf-8"))
        self.assertNotIn(b"__FORMAT__", html)
        self.assertIn(json.dumps(animation.page()).encode(), html)
        for src in re.findall(rb'<script src="([^"]+)"', html):   # each script it loads, served beside it
            self.assertEqual(self.ask(src.decode())[:2], (200, "text/javascript; charset=utf-8"), src)

    def test_bad_file(self):
        """a file with button 10, -1, no color and strings for numbers draws, lists and opens"""
        bad = {"seconds": "2", "blocks": [{"button": 10, "start": 0, "end": 1, "color": [0, 255, 0]}, {"button": -1, "start": 0, "end": 1, "color": [0, 255, 0]},
               {"button": 2, "start": 0, "end": 1}, {"button": "4", "start": "0", "end": "1", "color": "red"}], "presses": [{"button": 10}], "captions": "x"}
        (self.dir / "bad.json").write_text(json.dumps(bad))
        for path in ("/api/thumb/bad", "/api/thumb/bad?w=640", "/api/still/bad"):
            with self.subTest(path): self.assertEqual(self.ask(path)[0], 200)
        code, _, body = self.ask("/api/anim/bad")
        self.assertEqual((code, json.loads(body)), (200, animation.clean(bad)))
        self.assertEqual([b["button"] for b in json.loads(body)["blocks"]], [4])
        entry = next(x for x in json.loads(self.ask("/api/list")[2]) if x["name"] == "bad")
        self.assertEqual((entry["seconds"], entry["strip"]), (2.0, [[4, 0.0, 1.0, [255, 0, 0]]]))
        self.assertEqual(self.ask("/api/frames", "POST", bad)[0], 200)

    def test_unreadable(self):
        """half a file lists, with nothing in it, and doesn't open as an empty animation"""
        (self.dir / "half.json").write_text('{"seconds": 2, "blo')
        self.assertIn("half", [x["name"] for x in json.loads(self.ask("/api/list")[2])])
        self.assertEqual(self.ask("/api/anim/half")[0], 500)

    def test_round_trip(self):
        """a valid animation saves and opens unchanged, past Claude's limits too; a bad one saves cleaned"""
        self.assertEqual(self.ask("/api/anim/good", "PUT", VALID)[0], 200)
        self.assertEqual(json.loads(self.ask("/api/anim/good")[2]), VALID)
        (self.dir / "long.json").write_text(json.dumps(LONG))
        self.assertEqual(json.loads(self.ask("/api/anim/long")[2]), LONG)
        self.assertEqual(self.ask("/api/anim/long", "PUT", LONG)[0], 200)
        self.assertEqual(json.loads((self.dir / "long.json").read_text()), LONG)
        self.ask("/api/anim/fixed", "PUT", {**VALID, "blocks": VALID["blocks"] + [{"button": 10, "start": 0, "end": 1, "color": [1, 2, 3]}], "x": 1})
        self.assertEqual(json.loads((self.dir / "fixed.json").read_text()), VALID)

    def test_rename(self):
        """its GIF and still go with it; a taken name is refused"""
        self.ask("/api/anim/before", "PUT", VALID); (self.dir / "before.gif").write_bytes(b"GIF"); (self.dir / "before.png").write_bytes(b"PNG")
        self.ask("/api/anim/taken", "PUT", VALID)
        self.assertEqual(self.ask("/api/rename/before", "POST", {"to": "taken"})[0], 409)
        code, _, body = self.ask("/api/rename/before", "POST", {"to": "after"})
        self.assertEqual((code, json.loads(body)["renamed"]), (200, "after"))
        self.assertEqual([(self.dir / f).exists() for f in ("before.json", "before.gif", "before.png", "after.json", "after.gif", "after.png")],
                         [False] * 3 + [True] * 3)

    def test_chat(self):
        """a request to the fake Claude: its batch's versions listed, its conversation saved"""
        self.assertEqual(json.loads(self.ask("/api/claude")[2]), {"state": "on", "plan": "fake"})
        self.ask("/api/anim/owner", "PUT", VALID)
        code, _, body = self.ask("/api/chat", "POST", {"owner": "owner", "name": "owner", "anim": VALID, "message": "two please"})
        self.assertEqual(code, 200); batch = json.loads(body)["batch"]
        deadline = time.monotonic() + TIMEOUT
        while not (s := json.loads(self.ask("/api/job?since=0")[2]))["done"]:
            if time.monotonic() > deadline: self.fail(f"the job didn't end in {TIMEOUT} s")
            time.sleep(0.1)
        self.assertEqual([e["type"] for e in s["events"]], ["batch", "version", "version", "done"])
        listed = [x["name"] for x in json.loads(self.ask("/api/list")[2]) if (x["batch"] or {}).get("id") == batch]
        self.assertEqual(sorted(listed), ["take", "take 2"])
        chat = json.loads(self.ask("/api/chat/owner")[2])
        self.assertEqual((chat["session"], chat["running"], chat["messages"][-1]["versions"]), ("fake-1", False, 2))
        self.assertEqual(json.loads(self.ask("/api/job/stop", "POST")[2]), {"stopped": True})


if __name__ == "__main__":
    unittest.main()
