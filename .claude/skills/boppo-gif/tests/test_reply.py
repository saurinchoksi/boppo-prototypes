#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""studio_reply.py: Claude's reply read as it arrives, fed a few characters at a time as the CLI
streams it. Run it (uv brings Python); check.sh's studio part runs every tests/test_*.py here."""
import json, pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import animation, studio_reply

ANIM = {"seconds": 2.0, "blocks": [{"button": 5, "start": 0, "end": 1, "color": [0, 255, 0]}]}


def tag(name, body, note="a note"): return f'<version name="{name}" note="{note}">{body}</version>'


def fed(text, piece=7):
    """every piece's findings, in order, with the Reply"""
    r, out = studio_reply.Reply(), []
    for i in range(0, len(text), piece): out += r.feed(text[i:i + piece])
    return out, r


class Read(unittest.TestCase):
    def test_batch(self):
        """the size first, then each version, cleaned, its name and note kept"""
        text = '<batch size="2"/>Two takes.\n' + tag("slow", json.dumps(ANIM)) + tag("fast", json.dumps({**ANIM, "x": 1}), "quicker")
        out, r = fed(text)
        self.assertEqual([k for k, _ in out], ["size", "version", "version"])
        self.assertEqual(out[0][1], 2)
        v1, v2 = out[1][1], out[2][1]
        self.assertEqual((v1["n"], v1["name"], v1["note"]), (1, "slow", "a note"))
        self.assertEqual((v2["n"], v2["name"], v2["note"], v2["anim"]), (2, "fast", "quicker", animation.clean(ANIM)))
        self.assertEqual(r.visible(), "Two takes.")

    def test_claude_limits(self):
        """a version keeps to Claude's limits, not a file's: a 45 s one comes out at Claude's longest"""
        out, _ = fed(tag("long", json.dumps({**ANIM, "seconds": 45})))
        v = next(x for k, x in out if k == "version")
        self.assertEqual(v["anim"]["seconds"], animation.CLAUDE.seconds[1])
        self.assertLess(animation.CLAUDE.seconds[1], 45)

    def test_wrappers(self):
        """a code fence or CDATA around the JSON is read past"""
        for body in (f"```json\n{json.dumps(ANIM)}\n```", f"<![CDATA[{json.dumps(ANIM)}]]>", f"\n  {json.dumps(ANIM)}  \n"):
            with self.subTest(body[:12]):
                out, _ = fed(tag("v", body))
                self.assertEqual(out[-1][1]["anim"], animation.clean(ANIM))

    def test_half_written(self):
        """a version still being written isn't read, or shown"""
        whole = "Here it is. " + tag("v", json.dumps(ANIM))
        r = studio_reply.Reply()
        self.assertEqual(r.feed(whole[:len(whole) - 20]), [])
        self.assertEqual(r.visible(), "Here it is.")
        r2 = studio_reply.Reply(); r2.feed("Here it is. <vers")
        self.assertEqual(r2.visible(), "Here it is.")
        self.assertEqual([k for k, _ in r.feed(whole[len(whole) - 20:])], ["size", "version"])

    def test_bad_version(self):
        """a version that isn't JSON, or isn't an object, comes back with its error and no animation;
        the numbering goes on past it"""
        out, _ = fed(tag("bad", '{"seconds": 2, "blo') + tag("list", "[1, 2]") + tag("good", json.dumps(ANIM)))
        vs = [x for k, x in out if k == "version"]
        self.assertEqual([(v["n"], v["anim"] is None, "error" in v) for v in vs], [(1, True, True), (2, True, True), (3, False, False)])
        self.assertEqual([k for k, _ in out], ["version", "version", "size", "version"])   # a size only before a readable one

    def test_size_inferred(self):
        """no <batch> tag: size 0 (not said) with the first version; a tag after it is too late"""
        out, r = fed(tag("v", json.dumps(ANIM)) + '<batch size="3"/>')
        self.assertEqual(out[0], ("size", 0))
        self.assertEqual(r.size, 0)

    def test_questions(self):
        """questions listed, the old <choice>s folded in, and none of it in the words shown"""
        text = ("Before I start:<question>How fast? (slow, quick)</question>"
                "<question>Which row? <choice>top</choice><choice> bottom </choice></question>")
        out, r = fed(text)
        self.assertEqual(out, [])
        self.assertEqual(r.questions(), ["How fast? (slow, quick)", "Which row? (top, bottom)"])
        self.assertEqual(r.visible(), "Before I start:")

    def test_less_than(self):
        """a '<' in the words is hidden only while it could still become a tag, and kept once done"""
        r = studio_reply.Reply(); r.feed("Kept the level <")
        self.assertEqual(r.visible(), "Kept the level")
        r.feed(" 1 so it stays soft.")
        self.assertEqual(r.visible(), "Kept the level < 1 so it stays soft.")
        for half in ("<", "<ver", '<version name="a', "<batch size=", "</ques"):
            with self.subTest(half):
                self.assertEqual(studio_reply.visible("Ok. " + half), "Ok.")
                if "version" not in half: self.assertEqual(studio_reply.visible("Ok. " + half, done=True), "Ok. " + half)
        self.assertEqual(studio_reply.visible("a <b and <versions"), "a <b and <versions")

    def test_body_past_the_json(self):
        """the version is its first JSON object: braces in words after it, a missing close tag before
        the next version, and a '>' in a note are all read past"""
        out, _ = fed(tag("v", json.dumps(ANIM) + " (keep {it} soft)", "fast -> slow") + "\n"
                     + f'<version name="open">{json.dumps(ANIM)}\n' + tag("next", json.dumps({**ANIM, "seconds": 3.0})))
        vs = [x for k, x in out if k == "version"]
        self.assertEqual([(v["n"], v["name"], v["note"], v["anim"] is not None) for v in vs],
                         [(1, "v", "fast -> slow", True), (2, "open", "", True), (3, "next", "a note", True)])
        self.assertEqual(vs[2]["anim"]["seconds"], 3.0)

    def test_note_cut(self):
        out, _ = fed(tag("v", json.dumps(ANIM), "x" * 400))
        self.assertEqual(len(out[-1][1]["note"]), studio_reply.NOTE)


if __name__ == "__main__":
    unittest.main()
