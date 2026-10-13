// The studio page's session (studio-session.js) at its interface, no page: run with node --test.
// Each test replays what the page feeds it: the folder, a request's events, the designer's clicks.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

vm.runInThisContext(readFileSync(new URL("../studio-session.js", import.meta.url), "utf8"));
const studioSession = globalThis.studioSession;

// the folder's entries, as /api/list gives them; a Version is [name, batch id, n, from]
const anim = n => ({ name: n, mtime: 1, batch: null, seconds: 2, strip: [] });
const version = (n, id, k, from) => ({ ...anim(n), batch: { id, request: "three blues", from, n: k, note: "", picked: false } });
// /api/job's answer: the events since the last, numbered on
let next = 0;
const job = (...events) => ({ events, next: next += events.length, reply: "", done: events.some(e => e.type === "done") });
const batch = (id, size) => ({ type: "batch", id, size, request: "three blues" });
const arrived = n => ({ type: "version", name: n, n: 1, note: "" });
const DONE = { type: "done" };

// a session on "sky", a request from it sent: Batch b1
function onSky(...more) {
  const s = studioSession(); s.setList([anim("sky"), ...more]); s.open("sky", null);
  s.chatLoaded("sky", { messages: [] });
  s.sent("sky", "three blues", "b1", 1000);
  return s;
}

test("a batch of three arriving one by one: the grid, its waiting tiles 3 to 0", () => {
  const s = onSky(), vs = [];
  assert.deepEqual(s.events(job(batch("b1", 3))), { open: null, errors: [] });
  assert.deepEqual(s.stage(), { grid: "b1" }); assert.equal(s.waiting(), 3);
  assert.equal(s.from("b1"), "sky"); assert.equal(s.owner(), "sky");   // before any Version: the request's
  for (const [k, n] of ["blue 1", "blue 2", "blue 3"].entries()) {
    vs.push(version(n, "b1", k + 1, "sky")); s.setList([anim("sky"), ...vs]);
    assert.equal(s.events(job(arrived(n))).open, null);
    assert.equal(s.waiting(), 2 - k);
  }
  assert.equal(s.busy, true); s.events(job(DONE));
  assert.equal(s.busy, false); assert.equal(s.waiting(), 0); assert.deepEqual(s.stage(), { grid: "b1" });
  assert.deepEqual(s.versions("b1").map(x => x.name), ["blue 1", "blue 2", "blue 3"]);
});

test("a Batch of one opens its Version as it arrives, once, no grid", () => {
  const s = onSky();
  s.events(job(batch("b1", 1))); assert.deepEqual(s.stage(), { anim: "sky" });
  s.setList([anim("sky"), version("blue", "b1", 1, "sky")]);
  assert.equal(s.events(job(arrived("blue"))).open, "blue");
  assert.equal(s.events(job()).open, null);            // still opening on the next poll: not again
  s.open("blue", { id: "b1", from: "sky" }); assert.deepEqual(s.back(), { from: "sky" });
});

test("size 0 (not said) and one Version: its grid while drawing, then it opens when done", () => {
  const s = onSky();
  s.events(job(batch("b1", 0))); assert.deepEqual(s.stage(), { grid: "b1" }); assert.equal(s.waiting(), 1);
  s.setList([anim("sky"), version("blue", "b1", 1, "sky")]);
  assert.equal(s.events(job(arrived("blue"))).open, null); assert.equal(s.waiting(), 0);
  assert.equal(s.events(job(DONE)).open, "blue");
  s.open("blue", { id: "b1", from: "sky" });
  assert.deepEqual(s.stage(), { anim: "blue" }); assert.equal(s.owner(), "blue");
});

test("a request stopped before any Version: the grid closes, nothing waiting", () => {
  const s = onSky();
  s.events(job(batch("b1", 3))); assert.equal(s.waiting(), 3);
  s.events(job({ type: "error", text: "stopped" }, DONE));
  assert.deepEqual(s.stage(), { anim: "sky" }); assert.equal(s.waiting("b1"), 0); assert.equal(s.owner(), "sky");
});

test("the studio lost mid-request: nothing drawing, the empty grid closes", () => {
  const s = onSky(); s.events(job(batch("b1", 2)));
  s.lost(); assert.equal(s.busy, false); assert.equal(s.grid, null); assert.equal(s.waiting("b1"), 0);
});

test("every Version deleted from the rail: the grid closes", () => {
  const s = studioSession(), vs = [version("a", "b1", 1, "sky"), version("b", "b1", 2, "sky")];
  s.setList([anim("sky"), ...vs]); s.open("sky", null); s.showGrid("b1");
  s.setList([anim("sky"), vs[1]]); assert.equal(s.grid, "b1");
  s.setList([anim("sky")]); assert.equal(s.grid, null);
  s.showGrid("b1"); assert.equal(s.grid, null);         // a Batch gone shows nothing
});

test("a Batch's from renamed or deleted: no from, the way back and the chat fall to the open one", () => {
  const vs = [version("a", "b1", 1, "sky"), version("b", "b1", 2, "sky")], one = version("c", "b2", 1, "sky");
  const s = studioSession(); s.setList([anim("sky"), ...vs, one]);
  s.open("c", one.batch); assert.deepEqual(s.back(), { from: "sky" });
  s.showGrid("b1"); assert.equal(s.from("b1"), "sky"); assert.equal(s.owner(), "sky");
  s.setList([anim("sky 2"), ...vs, one]);             // renamed
  assert.equal(s.from("b1"), null); assert.equal(s.owner(), "c");
  assert.equal(s.closeGrid(), null); assert.deepEqual(s.back(), { from: null });
  s.open("a", vs[0].batch); assert.deepEqual(s.back(), { grid: "b1" });
  s.setList([...vs, one]); assert.deepEqual(s.back(), { grid: "b1" });   // deleted: its grid's still there
});

test("closing a grid goes back to its from, unless that's open already", () => {
  const vs = [version("a", "b1", 1, "sky"), version("b", "b1", 2, "sky")];
  const s = studioSession(); s.setList([anim("sky"), anim("moon"), ...vs]);
  s.open("moon", null); s.showGrid("b1"); assert.equal(s.closeGrid(), "sky");
  s.open("sky", null); s.showGrid("b1"); assert.equal(s.closeGrid(), null); assert.deepEqual(s.stage(), { anim: "sky" });
});

test("questions asked, then answered: the answer carries the first request", () => {
  const s = onSky();
  s.events(job({ type: "questions", questions: ["Which way?", "Its colors?"], request: "a swing meter" }, DONE));
  assert.equal(s.asking(), true);
  s.chatLoaded("sky", { messages: [{ role: "you", text: "a swing meter" }, { role: "claude", text: "Before I draw it:", questions: ["Which way?", "Its colors?"] }] });
  assert.equal(s.asking(), true);
  assert.deepEqual(s.request("1: left, 2: green"), { owner: "sky", request: "a swing meter", grid: null });
  s.sent("sky", "1: left, 2: green", "b2", 2000);
  assert.equal(s.asking(), false); assert.equal(s.chat.messages.at(-1).text, "1: left, 2: green");
  assert.equal(s.request("and again").request, "and again");
});

test("questions asked from a reloaded chat: asking, the message its own request", () => {
  const s = studioSession(); s.setList([anim("sky")]); s.open("sky", null);
  s.chatLoaded("sky", { messages: [{ role: "claude", text: "?", questions: ["Which way?"] }] });
  assert.equal(s.asking(), true); assert.equal(s.request("left").request, "left");
});

test("questions for another Animation don't carry over", () => {
  const s = onSky(anim("moon"));
  s.events(job({ type: "questions", questions: ["Which way?"], request: "a swing meter" }, DONE));
  s.open("moon", null); s.chatLoaded("moon", { messages: [] });
  assert.equal(s.asking(), false); assert.equal(s.request("stars").request, "stars");
});

test("the chat's owner: the grid's from while it's up, else the open Animation", () => {
  const vs = [version("a", "b1", 1, "sky"), version("b", "b1", 2, "sky")];
  const s = studioSession(); s.setList([anim("sky"), ...vs]); s.open("a", vs[0].batch);
  assert.equal(s.owner(), "a"); assert.deepEqual(s.request("x"), { owner: "a", request: "x", grid: "b1" });
  s.showGrid("b1"); assert.equal(s.owner(), "sky"); assert.deepEqual(s.request("x"), { owner: "sky", request: "x", grid: "b1" });
  assert.equal(s.chatLoaded("a", { messages: [{ role: "claude", text: "late" }] }), false);   // left already
  assert.equal(s.chatLoaded("sky", { messages: [] }), true);
  s.sent("sky", "x", "b2", 0); assert.ok(s.thinking());
  s.closeGrid(); assert.equal(s.owner(), "a");
  s.chatLoaded("a", { messages: [] }); assert.equal(s.thinking(), null);   // the request is sky's
});

test("a Version reloaded or replaced behind the grid leaves the grid up", () => {
  const vs = [version("a", "b1", 1, "sky"), version("b", "b1", 2, "sky")];
  const s = studioSession(); s.setList([anim("sky"), ...vs]); s.open("a", vs[0].batch); s.showGrid("b1");
  s.load("a", vs[0].batch); assert.equal(s.grid, "b1");
  s.closed(); assert.equal(s.name, null); s.load("sky", null); assert.deepEqual(s.stage(), { grid: "b1" });
  s.open("b", vs[1].batch); assert.deepEqual(s.stage(), { anim: "b" });
});

test("a saved conversation's messages are its objects: anything else is dropped", () => {
  const s = studioSession(); s.setList([anim("sky")]); s.open("sky", null);
  s.chatLoaded("sky", { messages: [null, "hi", { role: "claude", text: "?", questions: ["Which way?"] }, 7] });
  assert.deepEqual(s.chat.messages, [{ role: "claude", text: "?", questions: ["Which way?"] }]); assert.equal(s.asking(), true);
  s.chatLoaded("sky", { messages: [{ role: "claude", text: "ok" }, null] }); assert.equal(s.asking(), false);
});
