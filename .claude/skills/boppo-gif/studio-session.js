// The studio page's session: what the stage shows (a Batch's grid or one Animation), how many of a Batch's
// tiles Claude is still drawing, whose conversation the chat box holds, and whether Claude is asking. The
// page loads it as a script (studio.py serves it beside studio.html); tests/test_session.mjs runs it in Node.
//
// Pure: no page, no network. Its inputs: the folder (setList, /api/list's entries), a request's events
// (events, /api/job's answer), and what the designer does (open, showGrid, closeGrid, sent, closed). The page
// feeds it, then redraws its views from the answers. After every input:
// - a grid shows its Batch while a Version of it is in the folder or Claude is still drawing it; otherwise it
//   closes (stopped before any came, or each deleted from the rail);
// - a Batch's from is the Animation it was asked from, while one by that name is in the folder;
// - the chat is the open Animation's; with a grid up, its Batch's from's, when there is one.
// A request's Batch of one opens its Version as it arrives; one that never said its size (0) and came to
// one Version opens it when the request is done; any other shows its grid.
function studioSession() {
  let list = [], name = null, batch = null, grid = null, job = null, questions = null;
  let chat = { messages: [] }, chatOwner = null;      // the conversation in the box, and whose
  const versions = id => list.filter(x => x.batch && x.batch.id === id).sort((a, b) => a.batch.n - b.batch.n);
  const alive = n => n != null && list.some(x => x.name === n) ? n : null;
  const drawing = id => !!job && !job.done && job.batch === id;
  function from(id) {                  // before its first Version, the request's own
    const v = versions(id)[0];
    return alive(v ? v.batch.from : job && job.batch === id ? job.owner : null);
  }
  const owner = () => grid !== null && from(grid) || name;
  function back() {                    // the open Version's way back: its Batch's grid, or the Animation it came from
    if (!batch) return null;
    return versions(batch.id).length > 1 ? { grid: batch.id } : { from: alive(batch.from) };
  }
  function settle() { if (grid !== null && !versions(grid).length && !drawing(grid)) grid = null; }
  function take(n, b) { name = n; batch = b && b.id ? { id: b.id, from: b.from } : null; }
  const s = {
    get list() { return list; }, get name() { return name; }, get grid() { return grid; },
    get job() { return job; }, get chat() { return chat; }, get busy() { return !!job && !job.done; },
    stage: () => grid !== null ? { grid } : { anim: name },
    versions, from, drawing, owner, back,
    waiting(id = grid) {               // tiles still to come: the size said less those in the folder, or one till any
      if (!drawing(id)) return 0;
      const n = versions(id).length;
      return job.size > n ? job.size - n : n ? 0 : 1;
    },
    asking() {                         // Claude's questions, till the next message answers them
      const m = (chat.messages || []).at(-1);
      return !!questions && questions.owner === owner() || !!(m && m.role === "claude" && m.questions);
    },
    thinking: () => job && !job.done && job.owner === chatOwner ? { reply: job.reply, t0: job.t0 } : null,
    request(text) {                    // what a message carries: whose chat, the request it answers, the Batch on screen
      const o = owner(), q = questions && questions.owner === o ? questions : null, b = back();
      return { owner: o, request: q ? q.request : text, grid: grid !== null ? grid : b && b.grid || null };
    },

    setList(entries) { list = Array.isArray(entries) ? entries : []; settle(); },
    open(n, b) { take(n, b); grid = null; },          // onto the stage
    load: take,                                      // behind the grid, if one's up: reloaded, or the one deleted replaced
    closed() { name = null; batch = null; },         // deleted or renamed
    showGrid(id) { grid = id; settle(); },
    closeGrid() {                      // the Animation to go back to: the Batch's from, when it isn't open already
      const f = grid !== null ? from(grid) : null; grid = null;
      return f !== name ? f : null;
    },
    chatLoaded(o, c) {                 // a conversation fetched, its messages the objects in it; one for an owner since left is dropped
      if (o !== owner()) return false;
      chat = c && Array.isArray(c.messages) ? { ...c, messages: c.messages.filter(m => m && typeof m === "object") } : { messages: [] };
      chatOwner = o; return true;
    },
    sent(o, text, id, t0) {            // a request started, Batch id
      job = { batch: id, owner: o, since: 0, size: null, reply: "", done: false, t0, versions: [], opened: false };
      questions = null;
      if (chatOwner !== o) { chat = { messages: [] }; chatOwner = o; }
      chat = { ...chat, messages: [...(chat.messages || []), { role: "you", text }] };
    },
    events(st) {                       // /api/job's answer: { events, next, reply }; returns what the page does now
      const out = { open: null, errors: [] };
      if (!job) return out;
      job.since = st.next; job.reply = st.reply || "";
      for (const e of st.events || []) {
        if (e.type === "batch") { job.size = e.size; if (e.size !== 1) grid = e.id; }
        else if (e.type === "version") job.versions.push(e.name);
        else if (e.type === "questions") questions = { list: e.questions, request: e.request, owner: job.owner };
        else if (e.type === "error") out.errors.push(e.text);
        else if (e.type === "done") job.done = true;
      }
      const one = job.versions.length === 1 && !job.opened ? job.versions[0] : null;
      if (one && (job.size === 1 || job.size === 0 && job.done)) { job.opened = true; out.open = one; }
      settle(); return out;
    },
    lost() { if (job) job.done = true; settle(); },  // the studio stopped answering mid-request
  };
  return s;
}
