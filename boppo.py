"""Boppo, the tablet, for the games in this repo: everything true of it stays behind this interface.

    import boppo
    async with boppo.connect(log=print) as tablet:    # TabletGone if it isn't there
        await tablet.show(frame)                      # 40 (r, g, b), four zones a button
        await tablet.play("hold-release/intro.wav")   # a path under /sd/activities/user, or "/effects/..."
        for p in await tablet.buttons(0.01): ...      # Press(t, button, down), stamped on receipt
    boppo.upload(path, "hold-release/intro.wav")      # where play() finds it

Boppo's WebSocket API (developer.boppo.com/docs/websocket), in Python: Boppo's own client,
rust_boppo_websocket, is Rust only. Where this departs from Boppo's docs, it's from what we saw
on our tablet, and says so:
- Ours: frames go out only when something changed and never faster than MAX_FPS. Boppo documents
  no limit, but about 20 frames a second with sounds on top has hung our tablet's firmware (a
  long press on the power button brings it back).
- Ours: a frame with a whitespace byte in it gets "sl invalid length" back, though Boppo's docs
  say a frame is raw bytes: UNSPACE nudges them off.
- Boppo's: it takes one connection, and a new one drops the old. Ours: two copies of a game would
  knock each other off every few seconds, so connect() stops any other copy on this computer
  first (only_me).
- Ours, seen: it drops the connection when it sleeps, after about six idle minutes; that, and
  every other way it goes, is TabletGone.
- Not yet Boppo's way: its certificate is signed by the Boppo Device CA, which Boppo's own client
  checks and this doesn't (_tls); and uploads go direct, but the WebSocket still follows the
  computer's proxy settings. It's on the LAN, so both should go direct.

The host and password come from pairing.json at the repo root (see the README). Tests build a
Tablet over MemorySocket, the tablet in memory.
"""
import asyncio, collections, contextlib, fcntl, functools, json, math, os, pathlib, signal, ssl, time, urllib.request
import websockets
from websockets.exceptions import WebSocketException

PAIRING = pathlib.Path(__file__).resolve().parent / "pairing.json"
USER = "/sd/activities/user/"               # play()'s paths and upload()'s places are under this
MAX_FPS = 10
DIM = (8, 8, 8)
RESTING = [DIM] * 40                        # the board as a game opens and closes
SET_LIGHTS = b"set_lights "                 # then the frame, 40 (r, g, b) as 120 bytes
UNSPACE = {9: 14, 10: 14, 11: 14, 12: 14, 13: 14, 32: 33}   # whitespace bytes in a frame: the tablet answers "sl invalid length"

Press = collections.namedtuple("Press", "t button down")
Press.__doc__ = """a button pressed (down) or let go; t: time.monotonic() when it arrived"""

class TabletGone(ConnectionError):
    """the tablet isn't there, or has dropped the connection: asleep, off, or another connection took
    its place. The cause is chained"""

def pairing(host=None, password=None):
    """the tablet's host and password: as given, or from pairing.json"""
    if host and password: return host, password
    if not PAIRING.exists(): raise SystemExit(f"No {PAIRING.name} at the repo root: pair with the tablet first (README, Pairing).")
    cfg = json.loads(PAIRING.read_text())
    return host or cfg["host"], password or cfg["password"]

def _auth(password): return {"Authorization": f"Bearer {password}"}

@functools.cache
def _tls():
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # unchecked; Boppo's own client checks it against the Boppo Device CA
    return ctx

@contextlib.asynccontextmanager
async def connect(host=None, password=None, log=print):
    """the tablet, host and password from pairing.json unless given, as a Tablet; first, any other copy
    on it from this computer is stopped (only_me). log: how the tablet's error messages, and a copy
    stopped, are reported"""
    host, password = pairing(host, password); await asyncio.to_thread(only_me, host, log)   # it sleeps while a copy stops
    try:
        ws = await websockets.connect(f"wss://{host}/ws", ssl=_tls(), open_timeout=20, ping_interval=None,
                                      additional_headers=_auth(password))
    except (OSError, TimeoutError, WebSocketException) as e:
        raise TabletGone(f"no tablet at {host}") from e
    async with Tablet(ws, log) as tablet: yield tablet

class Tablet:
    """the tablet over a socket: connect()'s, or MemorySocket in tests. Entered, it reads what the
    tablet says and the board goes DIM; it goes back to DIM on the way out"""
    def __init__(self, socket, log=print, clock=time.monotonic):
        self.socket, self.log, self.clock = socket, log, clock
        self._frame = self._sent = None; self._last = -math.inf; self._cid = 0
        self._presses = asyncio.Queue(); self._reader = None; self._why = None

    async def __aenter__(self):
        self._reader = asyncio.create_task(self._read())
        try:
            await self._put(RESTING)
        except BaseException:
            await self._close(); raise
        return self

    async def __aexit__(self, kind, *_):
        try:
            await self._put(RESTING); await asyncio.sleep(0.2)
        except TabletGone:
            if kind is None: raise                      # gone already: say so only if nothing else is being said
        finally:
            await self._close()

    async def _close(self): self._reader.cancel(); await self.socket.close()

    async def _read(self):
        try:
            async for msg in self.socket:
                t = self.clock(); p = msg.split() if isinstance(msg, str) else []
                if p[:1] == ["button"] and len(p) >= 3: self._presses.put_nowait(Press(t, int(p[1]), p[2] == "p"))
                elif p[:1] == ["error_message"]: self.log("tablet:", msg)
        except Exception as e:
            self._why = e                               # the connection's end, or a bug in reading it: buttons() tells them apart
        self._presses.put_nowait(None)                  # over: buttons() says so

    async def _send(self, msg):
        try:
            await self.socket.send(msg)
        except (OSError, WebSocketException) as e:
            raise TabletGone("the tablet dropped the connection") from e

    # lights
    async def show(self, frame):
        """the lights: 40 (r, g, b), buttons 0 to 9, four zones each: top, left, right, bottom. Sent
        now if a frame's slot is open (MAX_FPS); if not, the newest frame shown goes out with the
        first show() or buttons() after it opens. Never a frame the same as the last one sent."""
        self._frame = [tuple(UNSPACE.get(v, v) for v in c) for c in frame]
        await self._flush()

    async def _flush(self):
        if self._frame is None or self._frame == self._sent or self.clock() - self._last < 1 / MAX_FPS: return
        await self._put(self._frame)

    async def _put(self, frame):
        """frame out as soon as its slot opens, changed or not"""
        wait = self._last + 1 / MAX_FPS - self.clock()
        if wait > 0: await asyncio.sleep(wait)
        await self._send(SET_LIGHTS + bytes(v for c in frame for v in c))
        self._sent = frame; self._last = self.clock()

    # sound
    async def play(self, sound):
        """sound: a path under /sd/activities/user, where upload() puts files, or one of Boppo's built-ins
        by its path, "/effects/...". At volume 1.0, so the tablet's own volume rules. Each through a
        controller of its own, as from when sound_finished was awaited; no game waits for it now."""
        self._cid += 1
        await self._send("play_sound " + json.dumps({"i": "controller", "id": self._cid, "sound": sound, "volume": 1.0}))

    # buttons
    async def buttons(self, timeout):
        """every Press waiting, in order; waits up to timeout for the first, [] if none comes.
        TabletGone once the connection has dropped"""
        await self._flush()
        try:
            got = [await asyncio.wait_for(self._presses.get(), timeout)]
        except TimeoutError:
            return []
        while not self._presses.empty(): got.append(self._presses.get_nowait())
        if None in got:
            self._presses.put_nowait(None)              # and on every call after
            if not isinstance(self._why, (OSError, WebSocketException, type(None))): raise self._why   # a bug, not the tablet going
            raise TabletGone("the tablet closed the connection") from self._why
        return got

class MemorySocket:
    """the tablet in memory, for tests: what was sent, in sent (frames() and sounds() read it back);
    press() and say() as the tablet would say them; drop() as the connection goes"""
    def __init__(self):
        self.sent = []; self.dropped = False; self._in = asyncio.Queue(); self._held = set()

    async def send(self, msg):
        if self.dropped: raise ConnectionError("dropped")
        self.sent.append(msg)
    async def close(self): self.dropped = True
    def __aiter__(self): return self
    async def __anext__(self):
        msg = await self._in.get()
        if msg is None: raise StopAsyncIteration
        return msg

    def say(self, msg): self._in.put_nowait(msg)
    def press(self, button, down=True):
        """as the tablet says it: the button, p or r, and every button held as a hex bit set"""
        (self._held.add if down else self._held.discard)(button)
        self.say(f"button {button} {'p' if down else 'r'} {sum(1 << b for b in self._held):x}")
    def drop(self): self.dropped = True; self._in.put_nowait(None)

    def frames(self):
        """every frame sent, as 40 (r, g, b)"""
        return [[tuple(m[i:i + 3]) for i in range(len(SET_LIGHTS), len(m), 3)] for m in self.sent if isinstance(m, bytes)]
    def sounds(self):
        """every sound played, its path"""
        return [json.loads(m.split(" ", 1)[1])["sound"] for m in self.sent if isinstance(m, str) and m.startswith("play_sound ")]

# one connection
_LOCK = None                                    # only_me's lock file, held open while this process runs
LOCKS = pathlib.Path("/tmp")

def _take(f, wait=0.0):
    """the lock on f, trying for up to wait seconds"""
    end = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
        except BlockingIOError:
            if time.monotonic() >= end: return False
            time.sleep(0.1)

def only_me(host, log=print):
    """the tablet takes one connection and a new one drops the old: stop any other copy on this
    computer that holds host's lock, then hold it until this one exits. Once a process"""
    global _LOCK
    if _LOCK: return
    path = LOCKS / f"boppo-{host}.lock"
    try:
        f = open(path, "a+")
    except PermissionError:
        raise SystemExit(f"{path} is another user's: their copy may be connected to the tablet.") from None
    if not _take(f):
        old = None
        for _ in range(10):                             # the holder writes its pid just after it takes the lock; until then
            time.sleep(0.1)                             # the file is empty, or holds the last holder's, maybe someone else's now
            f.seek(0); s = f.read().strip()
            if s.isdigit(): old = int(s); break
        if old is None: raise SystemExit(f"Another copy holds {path} and won't say who it is.")
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):   # an INT alone has left one running
            try:
                os.kill(old, sig)
            except ProcessLookupError: pass
            except PermissionError: raise SystemExit(f"Couldn't stop the copy already running (pid {old}): it's another user's.") from None
            if _take(f, wait=1.0): break
        else: raise SystemExit(f"Couldn't stop the copy already running (pid {old}).")
        log(f"stopped the copy already running (pid {old}, {sig.name})")
    f.seek(0); f.truncate(); f.write(str(os.getpid())); f.flush()
    _LOCK = f

# files
@functools.cache
def _web(): return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=_tls()))   # the tablet is on the LAN: never through a proxy

def upload(path, dest, host=None, password=None):
    """the file at path onto the tablet at dest, under /sd/activities/user where play() finds it,
    over HTTPS; the HTTP status"""
    host, password = pairing(host, password)
    req = urllib.request.Request(f"https://{host}/files/upload?path={USER}{dest}", data=pathlib.Path(path).read_bytes(), method="POST",
                                 headers={**_auth(password), "Content-Type": "application/octet-stream"})
    return _web().open(req, timeout=30).status
