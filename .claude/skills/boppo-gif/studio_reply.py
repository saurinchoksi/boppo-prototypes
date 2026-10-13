"""Claude's reply as it arrives, read: the words for the designer, the batch's size, each version
once its closing tag is in, and the questions. Pure: text in, values out; studio_chat.py's Job
writes the files.

The shape Claude is asked for (studio_chat.SYSTEM): <batch size="N"/>, a sentence or two, then
<version name=".." note="..">{JSON}</version> each, or <question>..? (a, b, c)</question> each.
"""
import json, re
import animation

VERSION = re.compile(r'<version\b((?:[^>"]|"[^"]*")*)>(.*?)(?:</version>|(?=<version\b))', re.S)   # an unclosed one ends at the next
QUESTION = re.compile(r"<question>(.*?)</question>", re.S)
CHOICE = re.compile(r"<choice>(.*?)</choice>", re.S)    # the old way to give examples, folded in
BATCH = re.compile(r'<batch\s+size="(\d+)"\s*/?>')
ATTR = re.compile(r'(\w+)="([^"]*)"')
TAGS = ("batch", "version", "question", "choice")
PARTIAL = re.compile(r'</?(\w*)(\s(?:[^<>"]|"[^"]*"?)*)?$')     # a tag at the end, still being written
NOTE = 160


def visible(text, done=False):
    """what the designer reads: the text without its tags, and, till it's done, without the start of
    one still being written"""
    text = BATCH.sub("", text)
    text = re.sub(r"<(version|question)\b.*?(</\1>|$)", "", text, flags=re.S)
    m = None if done else PARTIAL.search(text)
    if m and any(t == m[1] if m[2] else t.startswith(m[1]) for t in TAGS): text = text[:m.start()]
    return text.strip()


def version(n, attrs, body):
    """a closed <version>: {"n", "name" ("" when it gave none), "note", "anim"}, its Animation cleaned,
    or None and "error" when its JSON can't be read"""
    a = dict(ATTR.findall(attrs))
    v = {"n": n, "name": a.get("name", ""), "note": a.get("note", "")[:NOTE], "anim": None}
    try:                                               # the first object in it: past a code fence, CDATA (10/11)
        if (i := body.find("{")) < 0: raise ValueError("no JSON object")
        v["anim"] = animation.clean(json.JSONDecoder().raw_decode(body, i)[0], animation.CLAUDE)   # Claude keeps to its own limits
    except ValueError as e: v["error"] = str(e)
    return v


class Reply:
    """feed() it the text as it comes; it says what each piece completed"""

    def __init__(self):
        self.text, self.size, self.n, self.at = "", None, 0, 0   # at: where the next version can start

    def feed(self, delta):
        """the new things delta completed, in order: ("size", N), then ("version", version()) each.
        size is the <batch> tag's, or 0 (not said) when a readable version comes before any"""
        self.text += delta
        out = []
        if self.size is None and (m := BATCH.search(self.text)):
            self.size = int(m.group(1)); out.append(("size", self.size))
        for m in VERSION.finditer(self.text, self.at):
            self.n += 1; self.at = m.end()
            v = version(self.n, m.group(1), m.group(2))
            if self.size is None and v["anim"]: self.size = 0; out.append(("size", 0))
            out.append(("version", v))
        return out

    def visible(self, done=False): return visible(self.text, done)

    def questions(self):
        """each <question>, its <choice>s folded in as (a, b)"""
        return [visible(CHOICE.sub("", q)) + (f' ({", ".join(c.strip() for c in cs)})' if (cs := CHOICE.findall(q)) else "")
                for q in QUESTION.findall(self.text)]
