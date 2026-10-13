#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""studio_store.py on a temp folder: the animations, their exports, their conversations, and a
Batch's versions. Run it (uv brings Python); check.sh's studio part runs every tests/test_*.py here."""
import json, pathlib, sys, tempfile, threading, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import animation, studio_store

ANIM = {"seconds": 2.0, "blocks": [{"button": 5, "start": 0, "end": 1, "color": [0, 255, 0]}]}


def version(of, n, batch="b1"): return {**ANIM, "batch": {"id": batch, "request": "try some", "from": of, "n": n}}


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = pathlib.Path(self.tmp.name)
        self.s = studio_store.Store(self.dir)

    def tearDown(self): self.tmp.cleanup()

    def files(self): return sorted(str(p.relative_to(self.dir)) for p in self.dir.rglob("*") if p.is_file())

    def test_save_load_list(self):
        a, mtime = self.s.save("one", {**ANIM, "x": 1})
        self.assertEqual(a, animation.clean(ANIM))
        self.assertEqual(self.s.load("one"), a)
        (self.dir / "half.json").write_text('{"seconds": 2, "blo')
        rows = {e["name"]: e for e in self.s.list()}
        self.assertEqual(rows["one"]["mtime"], mtime)
        self.assertEqual(rows["half"]["anim"], animation.clean({}))
        self.assertFalse(rows["one"]["gif"])
        self.assertRaises(ValueError, self.s.load, "half")
        self.assertRaises(FileNotFoundError, self.s.load, "none")

    def test_names(self):
        for bad in ("../up", ".chat", "", "a/b", "x" * 90, None, "a\n"):
            with self.subTest(bad): self.assertRaises(ValueError, self.s.path, bad)

    def test_versions(self):
        self.s.save("b", version("orig", 2)); self.s.save("a", version("orig", 1)); self.s.save("c", version("orig", 1, "b2"))
        self.s.save("orig", ANIM)
        self.assertEqual([(n, name) for n, name, _ in self.s.versions("b1")], [(1, "a"), (2, "b")])

    def test_rename(self):
        """the JSON, GIF, still and conversation move, and each version is told where it came from"""
        self.s.save("orig", ANIM)
        (self.dir / "orig.gif").write_bytes(b"GIF"); (self.dir / "orig.png").write_bytes(b"PNG")
        self.s.save_chat("orig", {"session": "s1", "messages": [{"role": "you", "text": "hi"}]})
        self.s.save("v1", version("orig", 1)); self.s.save("v2", version("orig", 2)); self.s.save("other", version("else", 1))
        self.s.rename("orig", "renamed")
        self.assertEqual(self.files(), [".chat/renamed.json", "other.json", "renamed.gif", "renamed.json", "renamed.png", "v1.json", "v2.json"])
        self.assertEqual(self.s.chat("renamed")["session"], "s1")
        self.assertEqual([self.s.load(n)["batch"]["from"] for n in ("v1", "v2", "other")], ["renamed", "renamed", "else"])

    def test_rename_unreadable(self):
        """an unreadable file in the folder is left alone, and the rest moves"""
        self.s.save("orig", ANIM); self.s.save("v1", version("orig", 1))
        (self.dir / "half.json").write_text('{"batch": {"from": "orig"')
        self.s.rename("orig", "new")
        self.assertEqual(self.files(), ["half.json", "new.json", "v1.json"])
        self.assertEqual((self.dir / "half.json").read_text(), '{"batch": {"from": "orig"')
        self.assertEqual(self.s.load("v1")["batch"]["from"], "new")

    def test_rename_taken(self):
        """the new name's JSON or conversation there already: nothing moves"""
        for there in ("taken.json", ".chat/taken.json"):
            with self.subTest(there):
                self.tearDown(); self.setUp()
                self.s.save("orig", ANIM); (self.dir / "orig.gif").write_bytes(b"GIF"); self.s.save_chat("orig", {"session": None, "messages": []})
                (self.dir / ".chat").mkdir(exist_ok=True); (self.dir / there).write_text("{}")
                before = self.files()
                self.assertRaises(studio_store.Exists, self.s.rename, "orig", "taken")
                self.assertEqual(self.files(), before)
        self.assertRaises(FileNotFoundError, self.s.rename, "none", "other")

    def test_rename_over_export(self):
        """a deleted animation's exports don't block its name: old's replace them, or they stay, as
        they would for a save to it"""
        self.s.save("gone", ANIM); (self.dir / "gone.gif").write_bytes(b"OLD GIF"); (self.dir / "gone.png").write_bytes(b"OLD PNG")
        self.s.delete("gone")
        self.s.save("orig", ANIM); (self.dir / "orig.gif").write_bytes(b"GIF")
        self.s.rename("orig", "gone")
        self.assertEqual(self.files(), ["gone.gif", "gone.json", "gone.png"])
        self.assertEqual([(self.dir / f).read_bytes() for f in ("gone.gif", "gone.png")], [b"GIF", b"OLD PNG"])

    def test_rename_meanwhile(self):
        """a version changed or deleted while the files move is read again, not written back as it was"""
        self.s.save("orig", ANIM); self.s.save("v1", version("orig", 1)); self.s.save("v2", version("orig", 2))
        real = pathlib.Path.replace
        def replace(p, to):
            if p.name == "orig.json":
                animation.write(self.dir / "v1.json", {**version("orig", 1), "seconds": 5}); (self.dir / "v2.json").unlink()
            return real(p, to)
        with mock.patch.object(pathlib.Path, "replace", replace): self.s.rename("orig", "new")
        self.assertEqual(self.files(), ["new.json", "v1.json"])
        self.assertEqual((self.s.load("v1")["seconds"], self.s.load("v1")["batch"]["from"]), (5, "new"))

    def test_writes_take_turns(self):
        """a write waits for one under way on another thread"""
        with self.s.lock:
            t = threading.Thread(target=self.s.save, args=("one", ANIM)); t.start(); t.join(0.2)
            self.assertFalse(self.s.exists("one"))
        t.join(5)
        self.assertTrue(self.s.exists("one"))

    def test_rename_fails_midway(self):
        """a move that fails puts back the ones before it, and no version is touched"""
        self.s.save("orig", ANIM); (self.dir / "orig.gif").write_bytes(b"GIF"); (self.dir / "orig.png").write_bytes(b"PNG")
        self.s.save("v1", version("orig", 1))
        before, real = self.files(), pathlib.Path.replace
        def replace(p, to):
            if p.suffix == ".png": raise PermissionError("no")
            return real(p, to)
        with mock.patch.object(pathlib.Path, "replace", replace):
            self.assertRaises(PermissionError, self.s.rename, "orig", "new")
        self.assertEqual(self.files(), before)
        self.assertEqual(self.s.load("v1")["batch"]["from"], "orig")

    def test_delete(self):
        """the JSON and its conversation go; an export stays"""
        self.s.save("one", ANIM); self.s.save_chat("one", {"session": None, "messages": []}); (self.dir / "one.gif").write_bytes(b"GIF")
        self.s.delete("one")
        self.assertEqual(self.files(), ["one.gif"])
        self.s.delete("one")                            # gone already: no error

    def test_unique(self):
        """odd characters go; " 2", " 3" are added and kept within the limit"""
        self.assertEqual(self.s.unique("  a/b: c!  "), "a b c")
        self.assertEqual(self.s.unique("///"), "version")
        long = "w" * 100
        first = self.s.unique(long); self.s.save(first, ANIM)
        second = self.s.unique(long); self.s.save(second, ANIM)
        third = self.s.unique(long, limit=70)
        self.assertEqual((first, second), ("w" * 60, "w" * 58 + " 2"))
        self.assertEqual(third, "w" * 70)
        for i in range(3, 12): self.s.save(self.s.unique(long), ANIM)
        self.assertEqual(self.s.unique(long), "w" * 57 + " 12")
        self.assertEqual(self.s.unique("word " + "x" * 60, limit=5), "word")   # a cut at a space drops it
        self.s.save("word", ANIM)
        self.assertEqual(self.s.unique("word " + "x" * 60, limit=5), "wor 2")
        (self.dir / "batch go.gif").write_bytes(b"GIF")       # an export with no animation: its name is taken too
        self.assertEqual(self.s.unique("batch go"), "batch go 2")

    def test_chat(self):
        """a missing or unreadable conversation is an empty one; one saved reads back"""
        self.assertEqual(self.s.chat("none"), {"session": None, "messages": []})
        (self.dir / ".chat").mkdir(); (self.dir / ".chat" / "bad.json").write_text("[1")
        self.assertEqual(self.s.chat("bad"), {"session": None, "messages": []})
        c = {"session": "s", "messages": [{"role": "you", "text": "x"}]}
        self.s.save_chat("good", c)
        self.assertEqual(self.s.chat("good"), c)


if __name__ == "__main__":
    unittest.main()
