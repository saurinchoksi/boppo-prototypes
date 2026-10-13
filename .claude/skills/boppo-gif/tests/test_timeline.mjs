// The studio page's timeline (studio-timeline.js) at its interface, no page: run with node --test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

vm.runInThisContext(readFileSync(new URL("../studio-timeline.js", import.meta.url), "utf8"));
const TL = globalThis.studioTimeline({ fps: 10, buttons: 10, seconds: [0.5, 30] });   // page()'s shape; a 30 s length keeps the tables short

const L = (button, start, end) => ({ button, start, end, color: [0, 255, 0] });
const P = (button, start, end) => ({ button, start, end });
const anim = (o = {}) => ({ seconds: 3, blocks: [], presses: [], captions: [], still: 1, ...o });
const spans = xs => xs.map(x => [x.start, x.end]);

test("layout: each light's lane, span, depth and px", () => {
  const geo = (blocks, button = 0) => { const l = TL.layout(blocks, button); return [l.lanes, l.height, l.lights.map(x => [x.i, x.lane, x.span, x.depth])]; };
  for (const [what, blocks, want] of [
    ["an empty row: one lane", [], [1, 34, []]],
    ["one light", [L(0, 0, 1)], [1, 34, [[0, 0, 1, 0]]]],
    ["another row's lights aren't this row's", [L(3, 0, 1), L(0, 2, 3)], [1, 34, [[1, 0, 1, 0]]]],
    ["two that partly overlap: two lanes", [L(0, 0, 2), L(0, 1, 3)], [2, 46, [[0, 0, 1, 0], [1, 1, 1, 0]]]],
    ["two apart: one lane", [L(0, 0, 1), L(0, 1, 2)], [1, 34, [[0, 0, 1, 0], [1, 0, 1, 0]]]],
    ["one inside another: inside it, one lane", [L(0, 0, 3), L(0, 1, 2)], [1, 34, [[0, 0, 1, 0], [1, 0, 1, 1]]]],
    // A[0,4] holds B[1,3] and C[2,3.5], which partly overlap: lanes of their own inside A; D inside C
    ["nested overlaps take lanes inside their light", [L(0, 0, 4), L(0, 1, 3), L(0, 2, 3.5), L(0, 2.5, 3)],
      [2, 46, [[0, 0, 2, 0], [1, 0, 1, 1], [2, 1, 1, 1], [3, 1, 1, 2]]]],
    ["the tablet's drawing order: by start", [L(0, 2, 3), L(0, 0, 1)], [1, 34, [[1, 0, 1, 0], [0, 0, 1, 0]]]],
  ]) assert.deepEqual(geo(blocks), want, what);
});

test("layout: a level in is inset, slimmer, its font smaller", () => {
  const one = TL.layout([L(0, 0, 1)], 0).lights[0];
  assert.deepEqual(one, { i: 0, lane: 0, span: 1, depth: 0, top: 4, height: 22, inset: 0, font: 11 });
  const [a, b, c, d] = TL.layout([L(0, 0, 4), L(0, 1, 3), L(0, 2, 3.5), L(0, 2.5, 3)], 0).lights;
  assert.deepEqual([a.top, a.height, a.inset, a.font], [4, 33, 0, 11]);       // across both lanes
  assert.deepEqual([b.top, b.height, b.inset, b.font], [6.5, 10, 2.5, 8.5]);
  assert.deepEqual([c.top, c.height, c.inset], [24.5, 10, 2.5]);
  assert.deepEqual([d.top, d.height, d.inset], [26, 7, 4]);                   // a level further, a little less in
});

test("move: by frames, kept inside the length and the rows, a group as one", () => {
  for (const [what, items, dt, rows, want, seconds = 3] of [
    ["by a frame-snapped time", [L(0, 1, 2)], 0.34, 0, [[1.3, 2.3, 0]]],
    ["past the end: stops at the length", [L(0, 1, 2)], 5, 0, [[2, 3, 0]]],
    ["before 0: stops at 0", [L(0, 1, 2)], -5, 0, [[0, 1, 0]]],
    ["a group stops as one", [L(0, 0.5, 1), L(1, 1, 2.5)], -2, 0, [[0, 0.5, 0], [0.5, 2, 1]]],
    ["off the last row: stays on it", [L(9, 0, 1)], 0, 1, [[0, 1, 9]]],
    ["off the first row", [L(0, 0, 1)], 0, -3, [[0, 1, 0]]],
    ["a group across rows stops as one", [L(7, 0, 1), L(9, 0, 1)], 0, 2, [[0, 1, 7], [0, 1, 9]]],
    ["a row down", [L(2, 0, 1)], 0, 3, [[0, 1, 5]]],
    ["already past the length: back, yes", [L(0, 2, 4)], -1, 0, [[1, 3, 0]]],
    ["already past the length: no further", [L(0, 2, 4)], 1, 0, [[2, 4, 0]]],
  ]) {
    const a = anim({ seconds, blocks: items.map(x => ({ ...x })) });
    TL.move(a, TL.grab(a, "blocks", items.map((_, i) => i)), dt, rows);
    assert.deepEqual(a.blocks.map(x => [x.start, x.end, x.button]), want, what);
  }
});

test("move: a drag's every move is from where it began; a line has no row", () => {
  const a = anim({ blocks: [L(0, 1, 2)], captions: [{ start: 0, end: 1, text: "Go" }] }), g = TL.grab(a, "blocks", [0]);
  for (const dt of [0.3, 0.6, 0.2]) TL.move(a, g, dt);
  assert.deepEqual(spans(a.blocks), [[1.2, 2.2]]);
  TL.move(a, TL.grab(a, "captions", [0]), 0.5, 4);
  assert.deepEqual(a.captions[0], { start: 0.5, end: 1.5, text: "Go" });
});

test("move: one off the frames or shorter than one (Claude's) keeps its length; its start snaps", () => {
  for (const [what, x, dt, want] of [
    ["off the frames: its start on one, its length kept", L(0, 1.23, 2), 0.3, [1.5, 2.27]],
    ["shorter than a frame: as short, not none", L(0, 1.21, 1.24), 0.1, [1.3, 1.33]],
    ["past the end: ends at the length, its start off the frames", L(0, 1.18, 2), 5, [2.18, 3]],
  ]) {
    const a = anim({ blocks: [{ ...x }] });
    TL.move(a, TL.grab(a, "blocks", [0]), dt);
    assert.deepEqual(spans(a.blocks), [want], what);
  }
  const a = anim({ presses: [P(4, 1.21, 1.24)] });
  TL.nudge(a, "presses", new Set([0]), 0.1);
  assert.deepEqual(spans(a.presses), [[1.3, 1.33]], "nudged");
  TL.paste(a, { kind: "presses", items: [P(1, 0.23, 1)] }, 1);
  assert.deepEqual(spans(a.presses.slice(1)), [[1, 1.77]], "pasted");
});

test("nudge: a frame or a second, inside the length and the rows", () => {
  for (const [what, x, dt, rows, want] of [
    ["a frame", P(4, 1, 1.4), 0.1, 0, [1.1, 1.5, 4]],
    ["a second back from near the start: to 0", P(4, 0.5, 0.9), -1, 0, [0, 0.4, 4]],
    ["past the length: to the end", P(4, 2.5, 2.9), 1, 0, [2.6, 3, 4]],
    ["at the end, on: stays", P(4, 2.6, 3), 0.1, 0, [2.6, 3, 4]],
    ["off the last row: stays", P(9, 1, 1.4), 0, 1, [1, 1.4, 9]],
  ]) {
    const a = anim({ presses: [x] });
    TL.nudge(a, "presses", new Set([0]), dt, rows);
    assert.deepEqual([a.presses[0].start, a.presses[0].end, a.presses[0].button], want, what);
  }
});

test("resize: a frame long at least, from 0 to the length", () => {
  for (const [what, x, edge, dt, want] of [
    ["the end, out", L(0, 1, 2), "end", 0.5, [1, 2.5]],
    ["the end, below a frame: a frame", L(0, 1, 2), "end", -3, [1, 1.1]],
    ["the end, past the length: to it", L(0, 1, 2), "end", 5, [1, 3]],
    ["the end of one past the length: no further", L(0, 1, 4), "end", 1, [1, 4]],
    ["the start, below a frame: a frame", L(0, 1, 2), "start", 3, [1.9, 2]],
    ["the start, before 0: 0", L(0, 1, 2), "start", -3, [0, 2]],
  ]) {
    const a = anim({ blocks: [x] });
    TL.resize(a, TL.grab(a, "blocks", [0]), edge, dt);
    assert.deepEqual(spans(a.blocks), [want], what);
  }
});

test("create: from its frame, its kind's length or to the end; nothing at the end", () => {
  const a = anim();
  assert.equal(TL.create(a, "blocks", 3, 0.44, { color: [0, 0, 255] }), 0);
  assert.deepEqual(a.blocks[0], { color: [0, 0, 255], button: 3, start: 0.4, end: 1.4 });
  assert.equal(TL.create(a, "presses", 9, 1, {}), 0);
  assert.deepEqual(a.presses[0], { button: 9, start: 1, end: 1.3 });
  assert.equal(TL.create(a, "captions", "captions", 2.5, { text: "" }), 0);
  assert.deepEqual(a.captions[0], { text: "", start: 2.5, end: 3 });          // to the end, no row
  assert.equal(TL.create(a, "blocks", 0, 2.96, {}), -1);                    // its frame is the end
  assert.equal(TL.place(a, "blocks", 3.4), null);
  assert.deepEqual(TL.place(a, "blocks", 2.9), { start: 2.9, end: 3 });
  assert.equal(a.blocks.length, 1);
});

test("stretch: the drag that draws one, either way, a frame long at least, to the length", () => {
  const a = anim({ blocks: [L(0, 1, 2)] });
  for (const [t0, t1, want] of [[1, 2.33, [1, 2.3]], [1, 0.2, [0.2, 1]], [1, 1.02, [1, 1.1]], [1, 9, [1, 3]]]) {
    TL.stretch(a, "blocks", 0, t0, t1);
    assert.deepEqual(spans(a.blocks), [want], `${t0} to ${t1}`);
  }
});

test("paste: at the playhead, moved back as one if it would run past the length", () => {
  const clip = { kind: "presses", items: [P(1, 0, 1), P(2, 0.5, 2)] };
  for (const [what, t, seconds, want] of [
    ["at the playhead", 0.5, 3, [[0.5, 1.5], [1, 2.5]]],
    ["overflowing: ends at the length", 2.5, 3, [[1, 2], [1.5, 3]]],
    ["longer than the length: from 0", 1, 1.5, [[0, 1], [0.5, 2]]],
  ]) {
    const a = anim({ seconds, presses: [P(0, 0, 1)] });
    assert.deepEqual(TL.paste(a, clip, t), [1, 2], what);
    assert.deepEqual(spans(a.presses.slice(1)), want, what);
    assert.deepEqual(a.presses.slice(1).map(x => x.button), [1, 2], what);
  }
  assert.equal(clip.items[0].start, 0);                                       // the clip stays as it was
});

test("duplicate: copies just after, fitted inside the length; ⌥-drag's copies where they were", () => {
  let a = anim({ blocks: [L(0, 0, 0.5), L(1, 0.2, 1)] });
  assert.deepEqual(TL.duplicate(a, "blocks", new Set([0, 1])), [2, 3]);
  assert.deepEqual(spans(a.blocks), [[0, 0.5], [0.2, 1], [1, 1.5], [1.2, 2]]);
  a = anim({ blocks: [L(0, 2, 3)] });
  TL.duplicate(a, "blocks", [0]);
  assert.deepEqual(spans(a.blocks), [[2, 3], [2, 3]]);                       // at the length: no room after it
  a.blocks[0].color = [255, 0, 0];
  assert.deepEqual(a.blocks[1].color, [0, 255, 0]);                          // a copy, not the same light
  a = anim({ blocks: [L(4, 1, 2)] });
  const g = TL.clone(a, TL.grab(a, "blocks", [0]));
  assert.deepEqual(g.items.map(o => o.i), [1]);
  TL.move(a, g, 0.5, 1);
  assert.deepEqual(a.blocks.map(x => [x.start, x.end, x.button]), [[1, 2, 4], [1.5, 2.5, 5]]);
});

test("setLength: inside the limits; what's past it stays, the still comes before it", () => {
  for (const [what, s, want] of [
    ["shorter than a light: the light stays", 1.53, [1.5, 1.4, [[0, 2.5]]]],
    ["below the least", 0.1, [0.5, 0.4, [[0, 2.5]]]],
    ["past the most", 99, [30, 2, [[0, 2.5]]]],
    ["not a number: no change", NaN, [3, 2, [[0, 2.5]]]],
  ]) {
    const a = anim({ blocks: [L(0, 0, 2.5)], still: 2 });
    TL.setLength(a, s);
    assert.deepEqual([a.seconds, a.still, spans(a.blocks)], want, what);
  }
});

test("setStill: from 0 to a frame before the length", () => {
  for (const [s, want] of [[1.26, 1.3], [5, 2.9], [3, 2.9], [-1, 0]]) {
    const a = anim(); TL.setStill(a, s); assert.equal(a.still, want, String(s));
  }
});

test("setStart, setEnd: typed, a frame long at least, inside the length", () => {
  for (const [what, set, v, want] of [
    ["a start", "setStart", 0.5, [0.5, 2]],
    ["a start past the end pushes the end", "setStart", 2.5, [2.5, 2.6]],
    ["a start past the length: a frame before it", "setStart", 9, [2.9, 3]],
    ["a start before 0", "setStart", -1, [0, 2]],
    ["an end before the start: a frame", "setEnd", 0.2, [1, 1.1]],
    ["an end past the length: to it", "setEnd", 9, [1, 3]],
    ["not a number: no change", "setEnd", NaN, [1, 2]],
  ]) {
    const a = anim({ captions: [{ start: 1, end: 2, text: "" }] });
    TL[set](a, "captions", 0, v);
    assert.deepEqual(spans(a.captions), [want], what);
  }
});
