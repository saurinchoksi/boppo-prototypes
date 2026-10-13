// The studio page's Document (studio-doc.js) at its interface, no page: run with node --test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

vm.runInThisContext(readFileSync(new URL("../studio-doc.js", import.meta.url), "utf8"));
const studioDoc = globalThis.studioDoc;

const ANIM = () => ({ seconds: 2, blocks: [{ button: 3, start: 0, end: 1, color: [0, 0, 255], level: 1 }], presses: [], captions: [], still: 1 });
const VERSION = () => ({ ...ANIM(), batch: { id: "b1", request: "blue", from: "x", n: 1, note: "", picked: false } });

// a clock the test runs by hand, and a server that saves or fails as told
function rig({ fail = 0 } = {}) {
  let id = 0, now = 0; const timers = new Map(), saves = [], logs = [], seen = [];
  const r = {
    saves, logs, seen, fail,
    later: (f, ms) => { timers.set(++id, [now + ms, f]); return id; },
    cancel: k => timers.delete(k),
    async tick(ms) {                   // runs each timer due by now + ms, and what its save awaits
      now += ms;
      for (;;) {
        const due = [...timers].filter(([, [at]]) => at <= now).sort((a, b) => a[1][0] - b[1][0])[0];
        if (!due) break;
        timers.delete(due[0]); due[1][1]();
        await settle();
      }
      await settle();
    },
    pending: () => timers.size,
  };
  r.doc = studioDoc({ put: async (name, json) => { if (r.fail > 0) { r.fail--; throw new Error("no answer"); } saves.push([name, JSON.parse(json)]); return saves.length; },
    wait: 400, retry: 3000, tries: 3, log: s => logs.push(s), later: r.later, cancel: r.cancel });
  r.doc.on(what => seen.push(what));
  return r;
}
const settle = () => new Promise(res => setImmediate(res));

test("an edit is one undo step, saved after the wait", async () => {
  const r = rig(), d = r.doc; d.load("a", ANIM(), 1);
  assert.equal(d.edit(a => a.blocks[0].level = 0.5), true);
  assert.equal(d.state, "unsaved"); assert.equal(d.dirty, true);
  await r.tick(399); assert.equal(r.saves.length, 0);
  await r.tick(1); assert.equal(r.saves.length, 1); assert.equal(r.saves[0][1].blocks[0].level, 0.5);
  assert.equal(d.state, "saved"); assert.equal(d.mtime, 1);
  assert.equal(d.undo(), true); assert.equal(d.anim.blocks[0].level, 1);
  assert.equal(d.undo(), false);
});

test("a slider gesture, begun, previewed many times and committed, is one undo step", async () => {
  const r = rig(), d = r.doc; d.load("a", ANIM(), 1);
  d.edit(a => a.seconds = 3);
  d.begin();
  for (const v of [0.9, 0.8, 0.7, 0.6]) d.preview(a => a.blocks[0].level = v);
  assert.equal(r.seen.filter(w => w === "preview").length, 4);
  assert.equal(d.commit(), true);
  assert.equal(d.anim.blocks[0].level, 0.6);
  d.undo(); assert.equal(d.anim.blocks[0].level, 1); assert.equal(d.anim.seconds, 3);   // the slider alone
  d.undo(); assert.equal(d.anim.seconds, 2);
});

test("typing, a preview with no begin, then a commit, is one undo step", () => {
  const r = rig(), d = r.doc; d.load("a", { ...ANIM(), captions: [{ start: 0, end: 1, text: "" }] }, 1);
  for (const s of ["G", "Go", "Go!"]) d.preview(a => a.captions[0].text = s);
  assert.equal(d.gesture, true); d.commit(); assert.equal(d.gesture, false);
  d.undo(); assert.equal(d.anim.captions[0].text, "");
});

test("undo then redo round-trips; a new edit clears the redo", () => {
  const r = rig(), d = r.doc; d.load("a", ANIM(), 1);
  d.edit(a => a.blocks.push({ ...a.blocks[0], button: 4 }));
  const after = JSON.stringify(d.anim);
  d.undo(); assert.equal(d.anim.blocks.length, 1);
  assert.equal(d.redo(), true); assert.equal(JSON.stringify(d.anim), after);
  d.undo(); d.edit(a => a.still = 0.5); assert.equal(d.redo(), false);
});

test("a click with no change makes no step, no pick and no save", async () => {
  const r = rig(), d = r.doc; d.load("v", VERSION(), 1);
  d.begin(); d.preview(a => a.blocks[0].start = 0);   // a drag that ends where it began
  assert.equal(d.commit(), false);
  assert.equal(d.edit(() => {}), false);
  assert.equal(d.anim.batch.picked, false); assert.equal(d.undo(), false);
  await r.tick(5000); assert.equal(r.saves.length, 0); assert.equal(d.state, "saved");
});

test("editing a Version picks it; undo back to what Claude wrote unpicks it, and saves that", async () => {
  const r = rig(), d = r.doc; d.load("v", VERSION(), 1);
  d.edit(a => a.blocks[0].color = [255, 0, 0]); assert.equal(d.anim.batch.picked, true);
  d.edit(a => a.blocks[0].level = 0.5); assert.equal(d.anim.batch.picked, true);
  d.undo(); assert.equal(d.anim.batch.picked, true);
  d.undo(); assert.equal(d.anim.batch.picked, false);
  d.redo(); assert.equal(d.anim.batch.picked, true); d.undo();
  await r.tick(400); assert.equal(r.saves.at(-1)[1].batch.picked, false);
  d.edit(a => a.blocks[0].level = 0.5); d.edit(a => a.blocks[0].level = 1);   // changed and changed back by hand
  assert.equal(d.anim.batch.picked, false);
});

test("a Version picked when opened stays picked", () => {
  const r = rig(), d = r.doc, v = VERSION(); v.batch.picked = true; d.load("v", v, 1);
  d.edit(a => a.still = 0.5); d.undo(); assert.equal(d.anim.batch.picked, true);
});

test("a failed save says so, retries a few times, and the next edit tries again", async () => {
  const r = rig({ fail: 99 }), d = r.doc; d.load("a", ANIM(), 1);
  d.edit(a => a.still = 0.5);
  await r.tick(400);
  assert.equal(d.state, "failed"); assert.equal(d.error, "no answer"); assert.equal(d.dirty, true);
  assert.deepEqual(r.logs, ["studio: save failed: no answer"]);
  await r.tick(3000); await r.tick(3000);
  assert.equal(r.pending(), 0);                       // three tries in a row, then it stops
  r.fail = 1; d.edit(a => a.still = 0.4);             // the next edit: one more failure, then saved
  await r.tick(400); assert.equal(d.state, "failed");
  await r.tick(3000); assert.equal(d.state, "saved"); assert.equal(d.dirty, false);
  assert.equal(r.saves.at(-1)[1].still, 0.4);
});

test("flush saves now; mid-gesture it saves what was committed", async () => {
  const r = rig(), d = r.doc; d.load("a", ANIM(), 1);
  d.edit(a => a.still = 0.5);
  d.preview(a => a.still = 0.2);
  assert.equal(await d.flush(), true); assert.equal(r.saves.at(-1)[1].still, 0.5);
  d.commit(); assert.equal(await d.flush(), true); assert.equal(r.saves.at(-1)[1].still, 0.2);
  assert.equal(await d.flush(), true); assert.equal(r.saves.length, 2);   // nothing new: no save
});

test("load resets undo, redo and the saved state; a closed document saves nothing", async () => {
  const r = rig(), d = r.doc; d.load("a", ANIM(), 1);
  d.edit(a => a.still = 0.5); d.edit(a => a.still = 0.4); d.undo();
  d.load("b", ANIM(), 7);
  assert.equal(d.undo(), false); assert.equal(d.redo(), false);
  assert.equal(d.state, "saved"); assert.equal(d.mtime, 7); assert.equal(d.name, "b");
  await r.tick(1000); assert.equal(r.saves.length, 0);   // a's pending save went with it
  d.edit(a => a.still = 0.3); d.close();
  await r.tick(1000); assert.equal(r.saves.length, 0); assert.equal(await d.flush(), true);
});

test("cancel takes a gesture back: no step, no pick, no save; nothing to take back, nothing done", async () => {
  const r = rig(), d = r.doc; d.load("v", VERSION(), 1);
  d.edit(a => a.still = 0.5);
  d.begin(); d.preview(a => a.blocks.push({ ...a.blocks[0], button: 7 })); d.preview(a => a.blocks[1].start = 0.5);
  assert.equal(d.cancel(), true); assert.equal(d.gesture, false);
  assert.equal(d.anim.blocks.length, 1); assert.equal(d.anim.still, 0.5); assert.equal(r.seen.at(-1), "cancel");
  assert.equal(d.cancel(), false);
  d.begin(); assert.equal(d.cancel(), false);           // begun, nothing moved
  d.undo(); assert.equal(d.anim.still, 1); assert.equal(d.anim.batch.picked, false);
  await r.tick(400); assert.equal(r.saves.length, 1); assert.equal(r.saves[0][1].still, 1);
});
