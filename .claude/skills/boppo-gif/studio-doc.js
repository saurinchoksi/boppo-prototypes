// The studio page's Document: the Animation being edited, its undo and redo, whether it's saved, the
// Pick rule, and the save. The page loads it as a script (studio.py serves it beside studio.html);
// tests/test_doc.mjs runs it in Node.
//
// An edit is one undo step: edit(fn) at once, or a gesture (a drag, the slider, typing) as begin(), a
// preview(fn) each time it moves, and commit(), or cancel() to take it back. An edit or gesture that changes
// nothing leaves no step, picks nothing and saves nothing.
// The Pick rule: a Version is picked when it was picked when opened, or differs now from what was opened
// (what Claude wrote), so undo back to it unpicks it.
// The save: put(name, json) resolves to the file's mtime; it runs `wait` ms after the last edit. A failed
// one says so (state "failed", its error) and tries again every `retry` ms, `tries` times in a row at most;
// the next edit tries again.
// on(fn): fn(what) after each change, what one of load, edit, preview, cancel, undo, redo, status.
function studioDoc({ put, wait = 400, retry = 3000, tries = 3, log = console.error, later = setTimeout, cancel = clearTimeout }) {
  const MAX = 200, subs = [];
  let past = [], future = [], before = null, base = null;     // before: the gesture's start, null when none is open
  let rev = 0, savedRev = 0, gen = 0, timer = 0, fails = 0, saving = null;
  const body = a => JSON.stringify({ ...a, batch: undefined });
  const emit = what => subs.forEach(f => f(what));
  const doc = {
    anim: null, name: null, mtime: 0, state: "saved", error: "",
    get dirty() { return rev !== savedRev; },
    get gesture() { return before !== null; },
    on(f) { subs.push(f); },
    load(name, anim, mtime) {
      gen++; cancel(timer); past = []; future = []; before = null; rev = savedRev = fails = 0;
      Object.assign(doc, { anim, name, mtime, state: "saved", error: "" });
      base = { picked: !!(anim.batch && anim.batch.picked), body: body(anim) };
      emit("load");
    },
    close() { gen++; cancel(timer); before = null; rev = savedRev; doc.name = null; },   // deleted or renamed: nothing more to save
    begin() { if (before === null) before = JSON.stringify(doc.anim); },
    preview(fn) { doc.begin(); fn && fn(doc.anim); emit("preview"); },
    commit() {
      if (before === null) return false;
      const was = before; before = null;
      if (JSON.stringify(doc.anim) === was) return false;
      past.push(was); if (past.length > MAX) past.shift(); future = [];
      changed("edit"); return true;
    },
    cancel() {                         // the gesture taken back: the Animation as it began, no step
      if (before === null) return false;
      const was = before; before = null;
      if (JSON.stringify(doc.anim) === was) return false;
      doc.anim = JSON.parse(was); emit("cancel"); return true;
    },
    edit(fn) { doc.commit(); doc.begin(); fn(doc.anim); return doc.commit(); },
    undo() { return step(past, future, "undo"); },
    redo() { return step(future, past, "redo"); },
    flush: save,                       // now, if anything's unsaved; true once it's on disk
  };
  function step(from, to, what) {
    doc.commit(); if (!from.length) return false;
    to.push(JSON.stringify(doc.anim)); doc.anim = JSON.parse(from.pop());
    changed(what); return true;
  }
  function changed(what) {
    const b = doc.anim.batch; if (b) b.picked = base.picked || body(doc.anim) !== base.body;
    rev++; fails = 0; setState("unsaved");
    cancel(timer); timer = later(save, wait);
    emit(what);
  }
  function setState(s, error = "") {
    if (s === doc.state && error === doc.error) return;
    doc.state = s; doc.error = error; emit("status");
  }
  async function save() {
    cancel(timer);
    if (saving) { await saving; return save(); }       // one at a time, then whatever came since
    if (!doc.name || !doc.dirty) return true;
    const g = gen, r = rev, json = before ?? JSON.stringify(doc.anim);   // mid-gesture, what was committed
    saving = Promise.resolve().then(() => put(doc.name, json)).then(mtime => {
      if (g !== gen) return false;
      doc.mtime = mtime; savedRev = r; fails = 0; setState(doc.dirty ? "unsaved" : "saved");
      return !doc.dirty;
    }, e => {
      if (g !== gen) return false;
      if (++fails === 1) log("studio: save failed: " + e.message);
      setState("failed", e.message);
      cancel(timer); if (fails < tries) timer = later(save, retry);
      return false;
    }).finally(() => saving = null);
    return saving;
  }
  return doc;
}
