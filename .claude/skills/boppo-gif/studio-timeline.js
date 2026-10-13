// The studio page's timeline without the page: how a row's lights are laid out, and the edits a drag or a key
// makes. The page loads it as a script (studio.py serves it beside studio.html); tests/test_timeline.mjs runs
// it in Node.
//
// The limits, from the format the server fills in (animation.py's page()), each written once, here:
// - a time is on a frame (1/fps s), unless a limit isn't, and to the hundredth, as the server keeps it;
// - an item (a light, a press, a line) is a frame long at least, from 0 to the length, or to its own end if
//   that's past the length already: a length made shorter keeps what's past it, and an edit takes it no further;
// - a move keeps an item's length, even one off the frames or shorter than one (Claude's, say): its start snaps;
// - a light or a press is on a button, 0 to buttons - 1;
// - the length is seconds[0] to seconds[1]; the still, 0 to a frame before the length.
// An edit that would cross a limit stops at it; items moved together stop together.
//
// An op changes the Animation it's given (the one inside the Document's edit or preview) and returns the
// indexes of what it made, for the page to select. A grab is where items were when a drag began, the drag's
// every move measured from it: { kind, items: [{ i, start, end, button }] } (a line has no button).
function studioTimeline(format) {
  const FPS = format.fps, FRAME = 1 / FPS, [SHORTEST, LONGEST] = format.seconds, LAST = format.buttons - 1;
  const NEW = { blocks: 1.0, presses: 0.3, captions: 1.0 };       // a new item's length, s
  const snap = v => Math.round(v * FPS) / FPS;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));    // the least wins: a frame long beats the length
  const r100 = v => Math.round(v * 100) / 100;
  const at = (v, lo = 0, hi = Infinity) => r100(clamp(snap(v), lo, hi));
  const copy = x => JSON.parse(JSON.stringify(x));

  const grab = (a, kind, ids) => ({ kind, items: [...ids].map(i => { const { start, end, button } = a[kind][i]; return { i, start, end, button }; }) });
  // dt s and rows, cut short so each item stays inside the limits; kept: items already past the length may stay
  function shift(a, items, dt, rows, kept) {
    const room = Math.min(...items.map(o => kept ? Math.max(0, a.seconds - o.end) : a.seconds - o.end));
    const bs = items.map(o => o.button).filter(b => b !== undefined);
    return [clamp(snap(dt), -Math.min(...items.map(o => o.start)), room), bs.length ? clamp(rows, -Math.min(...bs), LAST - Math.max(...bs)) : 0];
  }
  // x, dt s on from o (shift's dt) with its length kept: its start on a frame, unless that would end it past the
  // length or where shift took it, then there
  function put(a, x, o, dt) {
    const n = o.end - o.start; x.start = at(o.start + dt, 0, Math.max(a.seconds, o.end + dt) - n); x.end = r100(x.start + n);
  }
  // a drag's move, and ← →: g's items from where they were, by dt s and rows
  function move(a, g, dt, rows = 0) {
    [dt, rows] = shift(a, g.items, dt, rows, true);
    for (const o of g.items) {
      const x = a[g.kind][o.i]; put(a, x, o, dt);
      if (o.button !== undefined) x.button = o.button + rows;
    }
  }
  const nudge = (a, kind, ids, dt, rows = 0) => move(a, grab(a, kind, ids), dt, rows);
  // a drag on an edge: each item's start or end from where it was, by dt s
  function resize(a, g, edge, dt) {
    for (const o of g.items) {
      const x = a[g.kind][o.i];
      if (edge === "start") x.start = at(o.start + dt, 0, o.end - FRAME);
      else x.end = at(o.end + dt, o.start + FRAME, Math.max(a.seconds, o.end));
    }
  }
  // where a new item drawn at t s goes: from its frame, its kind's length or to the end; null at the end or past it
  function place(a, kind, t) {
    const start = snap(Math.max(0, t));
    return start < a.seconds ? { start: at(start), end: at(start + NEW[kind], start + FRAME, a.seconds) } : null;
  }
  // a new item at t s on a button's row (a line has none), x its look; its index, -1 at the end or past it
  function create(a, kind, button, t, x = {}) {
    const p = place(a, kind, t); if (!p) return -1;
    a[kind].push({ ...x, ...(kind === "captions" ? {} : { button }), ...p });
    return a[kind].length - 1;
  }
  // the drag that draws a new item: from the frame at t0 to the frame at t1, either way
  function stretch(a, kind, i, t0, t1) {
    const x = a[kind][i];
    x.start = at(Math.min(t0, t1), 0, a.seconds - FRAME); x.end = at(Math.max(t0, t1), x.start + FRAME, a.seconds);
  }
  // copies of a clip's items ({ kind, items }), its earliest at t s, moved back as one if they'd run past the length
  function paste(a, clip, t) {
    const n = a[clip.kind].length, [dt] = shift(a, clip.items, snap(t) - Math.min(...clip.items.map(x => x.start)), 0, false);
    clip.items.forEach(x => { const y = copy(x); put(a, y, x, dt); a[clip.kind].push(y); });
    return clip.items.map((_, k) => n + k);
  }
  // ⌘D: copies just after the items, as a paste there
  function duplicate(a, kind, ids) {
    const items = [...ids].map(i => a[kind][i]);
    return paste(a, { kind, items }, Math.max(...items.map(x => x.end)));
  }
  // ⌥-drag: copies of g's items where they were, for the drag to move instead; the copies' grab
  function clone(a, g) {
    const n = a[g.kind].length;
    g.items.forEach(o => a[g.kind].push({ ...copy(a[g.kind][o.i]), start: o.start, end: o.end, ...(o.button !== undefined && { button: o.button }) }));
    return { kind: g.kind, items: g.items.map((o, k) => ({ ...o, i: n + k })) };
  }
  // typed in the panel: a start (its end pushed on to keep it a frame long), or an end
  function setStart(a, kind, i, s) {
    const x = a[kind][i]; if (!Number.isFinite(s)) return;
    x.start = at(s, 0, Math.max(a.seconds, x.end) - FRAME); x.end = Math.max(x.end, at(x.start + FRAME));
  }
  function setEnd(a, kind, i, s) { const x = a[kind][i]; if (Number.isFinite(s)) x.end = at(s, x.start + FRAME, Math.max(a.seconds, x.end)); }
  // the length; what's past it stays, the still comes before it
  function setLength(a, s) { if (Number.isFinite(s)) { a.seconds = at(s, SHORTEST, LONGEST); setStill(a, a.still); } }
  function setStill(a, s) { if (Number.isFinite(s)) a.still = at(s, 0, a.seconds - FRAME); }

  // A row's lights, laid out (the drawing only: the data doesn't change). A light inside another (inside its span,
  // and drawn over it, as the tablet draws a later start over an earlier one) draws inside it, a level deeper each
  // time; lights that only partly overlap take lanes, at every level, and a light spans the lanes of the lights
  // inside it. The row's height and lanes, and its lights in the tablet's drawing order, each
  // { i, lane, span, depth, top, height, inset, font }: its index in blocks, its lanes, its level, its px and font px
  function layout(blocks, button) {
    const bl = blocks.map((b, i) => ({ b, i, kids: [] })).filter(x => x.b.button === button)
      .sort((x, y) => x.b.start - y.b.start || x.i - y.i);          // the tablet's drawing order
    const within = (x, y) => y.b.start <= x.b.start + 1e-6 && y.b.end >= x.b.end - 1e-6;
    const overlap = (x, y) => x.b.start < y.b.end - 1e-6 && y.b.start < x.b.end - 1e-6;
    const tops = [];
    bl.forEach((x, k) => { const p = bl.slice(0, k).findLast(y => within(x, y)); (p ? p.kids : tops).push(x); });   // inside the last one drawn under it
    const pack = xs => {                  // each its lanes, the first free across its span; the lanes they take
      xs.forEach(x => x.span = x.kids.length ? pack(x.kids) : 1);
      let n = 1;
      xs.forEach((x, k) => {
        let o = 0; while (xs.slice(0, k).some(y => overlap(x, y) && y.off < o + x.span && o < y.off + y.span)) o++;
        x.off = o; n = Math.max(n, o + x.span);
      });
      return n;
    };
    const place = (xs, lane, depth) => xs.forEach(x => { x.lane = lane + x.off; x.depth = depth; place(x.kids, x.lane, depth + 1); });
    const lanes = pack(tops); place(tops, 0, 0);
    const laneH = lanes === 1 ? 22 : 15, step = 18, k1 = laneH >= 20 ? 4 : 2.5;   // a level in, then a little less each level
    const lights = bl.map(({ i, lane, span, depth }) => {
      const inset = depth ? k1 + k1 * 0.6 * (depth - 1) : 0, height = Math.max(5, (span - 1) * step + laneH - 2 * inset);
      return { i, lane, span, depth, top: 4 + lane * step + inset, height, inset, font: height >= 18 ? 11 : height >= 12 ? 9.5 : 8.5 };
    });
    return { height: lanes === 1 ? 34 : 4 + (lanes - 1) * step + laneH + 9, lanes, lights };
  }

  return { FPS, FRAME, snap, layout, grab, move, nudge, resize, place, create, stretch, paste, duplicate, clone, setStart, setEnd, setLength, setStill };
}
