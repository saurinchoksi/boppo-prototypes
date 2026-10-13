#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""animation.py at its interface: any JSON in, a clean Animation out, and its lights at a moment.
Run it (uv brings Python); check.sh's studio part runs every tests/test_*.py here."""
import json, os, pathlib, re, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import animation as A

GREEN, BLUE, RED = [0, 255, 0], [0, 0, 255], [255, 0, 0]


def block(**kw):
    return {"button": 0, "start": 0.0, "end": 1.0, "color": GREEN, **kw}


def blocks(*bs): return A.clean({"seconds": 3.0, "blocks": list(bs)})["blocks"]


class Clean(unittest.TestCase):
    def test_blocks(self):
        """bad blocks in, each left out or made drawable"""
        for name, b, want in [
            ("button 10", block(button=10), None),
            ("button -1", block(button=-1), None),
            ("button a string number", block(button="3"), {"button": 3}),
            ("button not a number", block(button="ten"), None),
            ("button missing", {"start": 0, "end": 1, "color": GREEN}, None),
            ("color missing", {"button": 0, "start": 0, "end": 1}, None),
            ("color markup", block(color="<img src=x onerror=alert(1)>"), None),
            ("color a name", block(color="spring green"), {"color": [0, 255, 127]}),
            ("color two numbers", block(color=[1, 2]), None),
            ("color out of range, strings", block(color=["300", -5, "x"]), {"color": [255, 0, 0]}),
            ("end before start", block(start=2.0, end=1.0), None),
            ("end at start", block(start=1.0, end=1.0), None),
            ("times as strings", block(start="0.5", end="1.5"), {"start": 0.5, "end": 1.5}),
            ("times past the longest", block(start=599.5, end=999), {"start": 599.5, "end": 600}),
            ("start below 0", block(start=-1, end=1), {"start": 0}),
            ("a time NaN", block(start=float("nan")), None),
            ("unknown effect", block(effect="wobble"), {"effect": "steady"}),
            ("effect not a string", block(effect={"x": 1}), {"effect": "steady"}),
            ("level over", block(level=5), {"level": 1}),
            ("level under", block(level=0), {"level": 0.05}),
            ("level a string", block(level="0.5"), {"level": 0.5}),
            ("every 0", block(every=0), {"every": 0.1}),
            ("fades negative", block(fade_in=-1, fade_out="x"), {"fade_in": 0, "fade_out": 0}),
            ("color2 junk", block(color2="nope"), {"color2": None}),
            ("lights unknown", block(lights=["up", "<b>"]), {"lights": list(A.LIGHTS)}),
            ("lights a number", block(lights=5), {"lights": list(A.LIGHTS)}),
            ("lights out of order", block(lights=["bottom", "top", "top"]), {"lights": ["top", "bottom"]}),
            ("not an object", "a block", None),
        ]:
            with self.subTest(name):
                got = blocks(b)
                if want is None: self.assertEqual(got, [])
                else:
                    self.assertEqual(len(got), 1)
                    for k, v in want.items(): self.assertEqual(got[0][k], v, k)

    def test_defaults(self):
        """a block with only what it must have gets the rest; an empty animation its length and still"""
        self.assertEqual(blocks(block()), [{"button": 0, "start": 0.0, "end": 1.0, "color": GREEN, **A.page()["block"]}])
        self.assertEqual(A.clean({}), {"seconds": 3.0, "blocks": [], "presses": [], "captions": [], "still": 1.0})
        self.assertEqual(A.clean({"seconds": "x"})["seconds"], A.FILE.seconds[2])

    def test_limits(self):
        """Claude's limits cut only Claude's versions; a file the page or a person wrote keeps all of
        it, and the page is sent a file's limits"""
        long = A.clean({"seconds": 45.0, "blocks": [block(start=32.0, end=40.0, every=20.0)],
                        "captions": [{"start": 0.0, "end": 44.0, "text": "y" * 87}]})
        self.assertEqual(A.clean(json.loads(json.dumps(long))), long)
        self.assertEqual((long["seconds"], long["blocks"][0]["start"], long["blocks"][0]["every"], len(long["captions"][0]["text"])),
                         (45.0, 32.0, 20.0, 87))
        c = A.clean(long, A.CLAUDE)
        self.assertEqual((c["seconds"], c["blocks"], c["captions"]), (30, [], [{"start": 0.0, "end": 30, "text": "y" * 80}]))
        self.assertEqual(A.clean({"blocks": [block(every=20.0)]}, A.CLAUDE)["blocks"][0]["every"], 10)
        self.assertEqual({k: A.page()[k] for k in ("seconds", "every", "text")}, {"seconds": (0.5, 600), "every": (0.1, 600), "text": 500})

    def test_animation(self):
        for name, a, key, want in [
            ("seconds under", {"seconds": 0.1}, "seconds", 0.5),
            ("seconds over", {"seconds": 900}, "seconds", 600),
            ("seconds infinite", {"seconds": float("inf")}, "seconds", 3.0),
            ("still past the end", {"seconds": 2, "still": 5}, "still", 1.9),
            ("still missing, short", {"seconds": 1}, "still", 0.5),
            ("blocks not a list", {"blocks": {"button": 0}}, "blocks", []),
            ("press button 10", {"presses": [{"button": 10, "start": 0, "end": 1}]}, "presses", []),
            ("press end before start", {"presses": [{"button": 1, "start": 1, "end": 0.5}]}, "presses", []),
            ("press strings", {"presses": [{"button": "9", "start": "1", "end": "1.4"}]}, "presses", [{"button": 9, "start": 1.0, "end": 1.4}]),
            ("caption text not a string", {"captions": [{"start": 0, "end": 1, "text": 5}]}, "captions", []),
            ("caption too long", {"captions": [{"start": 0, "end": 1, "text": "x" * 900}]}, "captions", [{"start": 0, "end": 1, "text": "x" * A.FILE.text}]),
            ("caption markup kept, as text", {"captions": [{"start": 0, "end": 1, "text": "<b>hi</b>"}]}, "captions", [{"start": 0, "end": 1, "text": "<b>hi</b>"}]),
        ]:
            with self.subTest(name): self.assertEqual(A.clean(a)[key], want)
        self.assertNotIn("junk", A.clean({"junk": 1}))
        for bad in ([], "x", None, 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError): A.clean(bad)

    def test_batch(self):
        b = {"id": "20261012-101010", "request": "r" * 300, "from": "dots", "n": "2", "note": 5, "picked": True, "x": 1}
        self.assertEqual(A.clean({"batch": b})["batch"],
                         {"id": "20261012-101010", "request": "r" * 120, "from": "dots", "n": 2, "note": "", "picked": True})
        self.assertEqual(A.clean({"batch": {"id": "a"}})["batch"], {"id": "a", "request": "", "from": None, "n": 0, "note": "", "picked": False})
        for bad in ({"request": "no id"}, {"id": 5}, "batch", None):
            with self.subTest(bad=bad): self.assertNotIn("batch", A.clean({"batch": bad}))

    def test_clean_twice(self):
        """what clean made, it leaves as it is"""
        a = A.clean({"seconds": "4", "blocks": [block(button="2", level=3, color="RED")], "presses": [{"button": 1, "start": 0, "end": 1}],
                     "captions": [{"start": 0, "end": 1, "text": "hi"}], "batch": {"id": "x", "n": 1}})
        self.assertEqual(A.clean(json.loads(json.dumps(a))), a)

    def test_schema(self):
        """SCHEMA's example is an animation clean leaves as it is, with every key clean writes"""
        example = json.loads(re.search(r"^\{.*?^ \"still\": [\d.]+\}$", A.SCHEMA, re.S | re.M).group(0))
        self.assertEqual(A.clean(example), example)
        for e in A.EFFECTS: self.assertIn(e, A.SCHEMA)
        for n in A.PALETTE: self.assertIn(n, A.SCHEMA)

    def test_read_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.json"
            wrote = A.write(p, {"blocks": [block(), block(button=10)]})
            self.assertEqual(A.read(p), wrote)
            self.assertEqual(len(wrote["blocks"]), 1)
            self.assertEqual([x.name for x in pathlib.Path(d).iterdir()], ["a.json"])   # no temp file left
            p.write_text("{half")
            with self.assertRaises(ValueError): A.read(p)

    def test_write_keeps(self):
        """a write keeps the file's mode, gives a new one the umask's, and goes through a symlink"""
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); mask = os.umask(0o022); os.umask(mask)
            A.write(d / "new.json", {})
            self.assertEqual((d / "new.json").stat().st_mode & 0o777, 0o666 & ~mask)
            (d / "new.json").chmod(0o640); A.write(d / "new.json", {"seconds": 2})
            self.assertEqual((d / "new.json").stat().st_mode & 0o777, 0o640)
            (d / "real").mkdir(); (d / "link.json").symlink_to(d / "real" / "a.json")
            A.write(d / "link.json", {"seconds": 4})
            self.assertTrue((d / "link.json").is_symlink())
            self.assertEqual(A.read(d / "real" / "a.json")["seconds"], 4)
            self.assertEqual(sorted(x.name for x in d.rglob("*")), ["a.json", "link.json", "new.json", "real"])


def fb(*bs, t): return A.framebuffer(A.clean({"seconds": 30, "blocks": list(bs)}), t)
def lit(f, button): return {side: f[button * 4 + i] for i, side in enumerate(A.LIGHTS) if f[button * 4 + i] != (0, 0, 0)}


class Playback(unittest.TestCase):
    def test_steady(self):
        f = fb(block(button=3, color=BLUE), t=0.5)
        self.assertEqual(lit(f, 3), dict.fromkeys(A.LIGHTS, (0, 0, 255)))
        self.assertEqual(sum(1 for c in f if c != (0, 0, 0)), 4)
        self.assertEqual(fb(block(), t=1.0), [(0, 0, 0)] * 40)                # its end is off
        self.assertEqual(lit(fb(block(level=0.5, lights=["left"]), t=0), 0), {"left": (0, 127, 0)})

    def test_flash(self):
        b = block(effect="flash", every=1.0, end=2.0)
        for t, want in [(0.0, (0, 255, 0)), (0.4, (0, 255, 0)), (0.5, None), (0.9, None), (1.0, (0, 255, 0))]:
            with self.subTest(color2=None, t=t): self.assertEqual(lit(fb(b, t=t), 0).get("top"), want)
        with self.subTest(color2=RED): self.assertEqual(lit(fb({**b, "color2": RED}, t=0.6), 0)["top"], (255, 0, 0))

    def test_spin(self):
        """one light at a time, clockwise from the top, a light every every / 4 s"""
        b = block(effect="spin", every=0.4, end=2.0)
        got = [list(lit(fb(b, t=i / 10), 0)) for i in range(5)]
        self.assertEqual(got, [["top"], ["right"], ["bottom"], ["left"], ["top"]])

    def test_pulse(self):
        b = block(effect="pulse", every=1.0, end=2.0)
        self.assertEqual(lit(fb(b, t=0), 0)["top"], (0, 255, 0))
        self.assertEqual(lit(fb(b, t=0.5), 0)["top"], (0, 63, 0))              # a quarter, at half a breath

    def test_fades(self):
        b = block(fade_in=0.5, fade_out=0.5, end=2.0)
        for t, g in [(0.0, None), (0.25, 127), (0.5, 255), (1.0, 255), (1.75, 127)]:
            with self.subTest(t=t): self.assertEqual(lit(fb(b, t=t), 0).get("top"), g and (0, g, 0))

    def test_later_over_earlier(self):
        """a block that starts later is drawn over one that started earlier, light by light"""
        early, late = block(color=GREEN, end=3.0), block(color=RED, start=1.0, end=2.0, lights=["left"])
        for order in ([early, late], [late, early]):
            f = fb(*order, t=1.5)
            with self.subTest(order=[b["color"] for b in order]):
                self.assertEqual(lit(f, 0), {"top": (0, 255, 0), "left": (255, 0, 0), "right": (0, 255, 0), "bottom": (0, 255, 0)})
        self.assertEqual(lit(fb(early, late, t=2.5), 0)["left"], (0, 255, 0))   # back once it ends


if __name__ == "__main__":
    unittest.main()
