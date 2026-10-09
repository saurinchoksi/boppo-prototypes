"""Hold, Release on a Boppo tablet, played from a computer on the same Wi-Fi over Boppo's
WebSocket API. A glow moves only while you hold the button; releasing on the target is the
game.

Once a sitting the player picks a character, a color. They hold their button, 9, and their
glow runs out of it along a dim yellow road; releasing on the green target is a hit.
  1 stop-and-go, the target on 6-5, 0.7 s a button: releasing short of the target stops the
    glow and the next press moves it on; held past the target's end and its 0.3 s grace is a
    late miss
  2 the target is button 5 only, and it is one go: any release ends the try
  3 as 2, at 0.5 s a button
  4 the full road, 8-7-6-5 up into 0 and 1-2-3, the target on 3, at 0.5 s
  5 as 4 with a ball instead of the trail, at 0.35 s
It climbs by itself: one hit finishes a level (after level 5, back to 1); a miss just plays
again, and says which way: "Oops! Keep holding!" for an early release, "Oops, too far." for a
late one.

Each level's intro: its board and the player's button lit, steady (levels 1 and 4, where the
road is new, first unfold it), then a beat of silence and the level's line; the button pulses on
the line's last word, their turn, and keeps pulsing while it waits for a press. A press before
that gets no sound and no glow, but a finger still down when the turn comes starts the glow at
once. A hit: success on the target's flash, then the next level's intro, no fanfare; after
level 5, "You did them all!" as the player's color fills the ring and breathes, then level 1 with
"Let's go again!". The try's rules are tries.py's and the lights levels.py's pure functions;
this script only reads the buttons, keeps time, plays the sounds and logs.

Usage: uv run hold-release/hold_release.py [--level N] [--color C] [--now] [--tick]
Without --color it starts in standby, the board dark but button 4 (top-right) dim white, so it
can be set up ahead: an adult holds it for 2 s, it fills white, and the pick begins; a tap does
nothing. --now skips standby; --color skips the pick; --level is where the pick leads. While it
runs, keys on the computer: 1 to 5 jump to a level and its intro (its own key restarts it),
+ and - or the arrow keys step up and down, p the pick again. Runs until Ctrl-C; when the tablet
sleeps it waits for it to wake. Every release prints with the level, where the glow stopped and
the result, also to hold-release/logs/."""
import argparse, asyncio, atexit, datetime, os, pathlib, signal, sys, termios, time, tty, wave

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                     # boppo.py, the tablet, shared by the repo's games
import boppo, levels
from levels import LEVELS
from tries import Tries

RETRY_S = 5.0               # while the tablet sleeps, try to reconnect this often
TIMEOUT_S = 12.0            # no press this long: the timeout prompt, once per wait
READY, READY_S = 4, 2.0     # standby: the adult holds button 4 (top-right) this long to start the pick; it fills white
READY_LO = 0.2              # from dim white, lit the whole standby: never an all-dark board
# Sounds at Boppo's default volume (1.0), so the tablet's volume rules. Effects are Boppo's
# built-ins (developer.boppo.com, Audio Files); the lines are sounds/, put on the tablet by
# upload_lines.py and mastered to the loudness of Boppo's own "Woohoo!". success, not
# success_mini_game: that one is ~25 dB quieter.
V = "hold-release/"
PIANO = "/effects/piano_chromatic_scale/{}.qoa"
SOUNDS = {
    "step": "/effects/button_tick.qoa",                  # the glow enters a road button: holding moves it
    "hit": "/effects/success.qoa",                       # on the target's first green beat
    "miss_early": V + "oops_hold.wav",                   # "Oops! Keep holding!": an early release, every level
    "miss_late": V + "oops_far.wav",                     # "Oops, too far.": a late miss, every level
    "timeout": V + "timeout.wav",
    **{k: V + f"{k}.wav" for k in ("intro", "again", "level2", "level3", "level4", "level5")},   # the levels' lines, after
                                                         # the hit's success, no fanfare; "again": level 1's second pass
    "done": V + "done.wav",                              # "You did them all!", after level 5
    **{k: V + f"{k}.wav" for k in ["pick", "pick_timeout"] + [f"{w}_{c}" for w in ("name", "you") for c in levels.COLORS]},   # the pick's lines
    **{f"note{i}": PIANO.format(n) for i, n in enumerate([1, 3, 5, 8, 10])},   # the reveal: a rising pentatonic note a button
    "chord": PIANO.format(10),                          # the target swells: one high note for now
}
# Every sound is a plain file: sound instructions wrapped in speed, volume or simultaneous went
# with the tablet dropping the connection, so they wait until the cause is known. That's also
# why a press during an intro ("hush") is silent for now.
QUIET = {"hush", "step"}    # keys not played. The step tick only with --tick: a line 56 ms after it has frozen the tablet
LINE_S = {w.stem: (lambda f: f.getnframes() / f.getframerate())(wave.open(str(w)))   # the lines' lengths, from the
          for w in (HERE / "sounds").glob("*.wav")}                                  # local copies: the pulse comes on the last word
DONE_S = LINE_S["done"] + 0.6                             # "You did them all!", and a beat

LOG = None                  # the day's log in logs/, set by main()
def say(*a):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] " + " ".join(str(x) for x in a)
    print(line, flush=True)
    if LOG:
        with open(LOG, "a") as f: f.write(line + "\n")

class Cues:
    """a phase's sounds: its cues, (at, key) from its start, each queued in out as its time comes;
    and its timeout_line, the prompt said once a wait when no press has come for TIMEOUT_S"""
    def __init__(self, out, start, cues, timeout_line, quiet):
        self.out, self.start, self.cues, self.timeout_line, self.cue = out, start, cues, timeout_line, 0; self.heard(quiet)
    def heard(self, t):
        """a press, or the turn: the timeout prompt counts from here"""
        self.quiet = t; self.timed_out = False
    def play(self, now):
        while self.cue < len(self.cues) and self.cues[self.cue][0] <= now - self.start:
            self.out.append(self.cues[self.cue][1]); self.cue += 1
    def wait(self, now):
        """waiting for a press: the timeout prompt, once TIMEOUT_S has gone by without one"""
        if not self.timed_out and now - self.quiet > TIMEOUT_S: self.timed_out = True; self.out.append(self.timeout_line)

class Standby:
    """the dark board before a sitting but button 4, dim white: an adult holds it READY_S to start
    the pick, and it fills white"""
    def __init__(self, game): self.game = game; self.t_ready = None
    def button(self, t, idx, pressed):
        if idx == READY: self.t_ready = t if pressed else None   # released early: nothing
    def update(self, now):                              # held long enough: the pick
        if self.t_ready is not None and now - self.t_ready >= READY_S: say("ready: the pick"); self.game.start_pick(now)
    def render(self, now):
        L = [levels.OFF] * 40; k = levels.clamp((now - self.t_ready) / READY_S) if self.t_ready is not None else 0.0
        L[READY * 4:READY * 4 + 4] = [levels.scale(levels.WHITE, READY_LO + (1 - READY_LO) * k)] * 4
        return L

class Pick:
    """the pick, once a sitting: the five colors light on the top row as their names play, and a
    press on a lit one chooses it; it pours to the player's button, then the level the sitting
    started on"""
    def __init__(self, game, now):
        self.game, self.t_pick, self.chose = game, now, None
        self.p = levels.pick(LINE_S["pick"], [LINE_S[f"name_{c}"] for c in levels.PICK])
        self.cues = Cues(game.out, now, self.p.cues, "pick_timeout", now + self.p.ready)   # the timeout prompt counts from all five lit

    def button(self, t, idx, pressed):
        """one of the five on the top row, once lit, names still coming"""
        if not pressed or self.chose is not None: return
        self.cues.heard(t)
        if idx < len(levels.PICK) and t - self.t_pick >= self.p.names[idx]:
            self.chose, self.t_chose = idx, t; self.game.out.append(f"you_{levels.PICK[idx]}"); say(f"picked {levels.PICK[idx]}")
        else: self.game.out.append("hush")              # a color not lit yet, or not a color

    def update(self, now):
        """the names as they come and the timeout prompt, until a press stops them; then the pour, and the level"""
        if self.chose is None: self.cues.play(now); self.cues.wait(now); return
        c = levels.PICK[self.chose]; end = self.t_chose + levels.picked_s(self.chose, LINE_S[f"you_{c}"])   # it pours, silently:
        if now >= end: self.game.player = levels.COLORS[c]; self.game.set_level(self.game.level, end)       # a tick a step froze the tablet

    def render(self, now):
        return levels.pick_lights(now - self.t_pick, self.p, self.chose, now - self.t_chose if self.chose is not None else 0.0)

class Level:
    """level n from the top: its intro (its board, sometimes a reveal, and its line), then its
    tries (tries.py) until the hit has flashed, and the next level. done: level 1 again, after level 5"""
    def __init__(self, game, n, now, done=False):
        self.game, self.n, self.R, self.t_intro = game, n, LEVELS[n], now
        self.line = "again" if done else "intro" if n == 1 else f"level{n}"
        self.o = levels.intro(n, LINE_S[self.line], DONE_S if done else None)
        self.cues = Cues(game.out, now, [(at, self.line if k == "line" else k) for at, k in self.o.cues], "timeout", now)
        self.tries = Tries(n, now, self.o.turn, game.down)
        say(f"level {n}: {self.R.name}, {self.R.cell_s} s a button")

    def next_level(self): return self.n % len(LEVELS) + 1   # one hit and the level is done; after level 5, back to 1
    def switch(self):
        """the hit's flash is over: the next level's intro, the phase from now on"""
        n = self.next_level(); return self.game.set_level(n, self.tries.done_at, done=n == 1)

    def button(self, t, idx, pressed):
        """only the player's button"""
        if idx == levels.BUTTON: self.press(t) if pressed else self.release(t)

    def press(self, t):
        if self.tries.done(t): return self.switch().press(t)   # pressed before it changed
        for h in self.tries.press(t):
            if h.what == "not yet": self.game.out.append("hush")   # not the player's turn yet
            else: self.cues.heard(t)

    def release(self, t):
        happened = self.tries.release(t)
        if happened: self.cues.heard(t)
        for h in happened: self.happened(h, t)

    def update(self, now):
        """the intro's sounds as they come, the tries, and the timeout prompt"""
        if self.tries.done(now): return self.switch().update(now)   # the next level's intro
        self.cues.play(now)
        for h in self.tries.update(now): self.happened(h, now)
        if not self.tries.before_turn(now) and not self.tries.held: self.cues.wait(now)

    def happened(self, h, now):
        """what the tries say happened, as sounds and log lines"""
        what, out = h.what, self.game.out
        if what == "step": out.append("step")
        elif what == "flash": out.append("hit")         # success on the target's first green beat
        elif what == "stop": out.append("miss_early"); self.report("release", ", it waits: press again")
        elif what == "turn": self.cues.heard(now)       # the timeout prompt counts from the pulse
        elif what == "held in": say(f"level {self.n}: held into the turn, the glow starts")
        elif what == "held in again": self.cues.heard(now); say(f"level {self.n}: held into the turn after the miss, the glow starts")
        elif what in ("release", "held to the end"):
            self.report(what)
            if h.result != "hit": out.append(f"miss_{h.result}")   # which way, on every level; no stepping back
            else: n = self.next_level(); say(f"level {self.n}: {'up' if n > self.n else 'back'} to {n} after this try")

    def report(self, what, extra=""):
        say(f"level {self.n} {what}: {self.tries.summary()}{extra}")

    def render(self, now):
        if self.tries.before_turn(now): return levels.intro_lights(self.n, now - self.t_intro, self.o, self.game.player)
        return levels.lights(self.n, self.tries.at(now), self.game.player)

class Game:
    """a sitting, from the tablet's presses and releases, stamped on receipt, through its phases:
    Standby, the Pick, and each Level; what they do comes out as sounds in out, and log lines"""
    def __init__(self, level, player=None, standby=False):
        self.level = level; self.player = player; self.out = []; self.down = False
        self.phase = Standby(self) if standby else None   # else session() starts the pick or the level
    @property
    def standby(self): return isinstance(self.phase, Standby)

    def set_level(self, n, now, done=False):
        """level n from the top: its intro, then the player's turn. done: back to 1 after level 5"""
        if n not in LEVELS: return                       # stepped off either end
        self.level = n; self.player = self.player or levels.BLUE   # a key during the pick: blue
        self.phase = Level(self, n, now, done); return self.phase

    def start_pick(self, now):
        """the pick, once a sitting; then the level it started on"""
        self.phase = Pick(self, now); say("the pick")

    def button(self, t, idx, pressed):
        """any button: in standby the adult's hold on button 4; during the pick one of the five on
        the top row; after that only the player's"""
        if idx == levels.BUTTON: self.down = pressed    # the player's finger on their button, whatever the phase
        self.phase.button(t, idx, pressed)

    def update(self, now): self.phase.update(now)
    def render(self, now): return self.phase.render(now)

def keys(g):
    """the computer's keyboard picks the level: every tablet button is road on levels 4 and 5"""
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    tty.setcbreak(fd); atexit.register(termios.tcsetattr, fd, termios.TCSADRAIN, old)   # Ctrl-C still stops it
    def on_key():
        s = os.read(fd, 16).decode(errors="ignore")
        now = time.monotonic()
        if s in ("\x1b[A", "\x1b[C"): return g.set_level(g.level + 1, now)
        if s in ("\x1b[B", "\x1b[D"): return g.set_level(g.level - 1, now)
        for ch in s:
            if ch in "pP": g.player = None; g.start_pick(now)
            elif ch.isdigit() and int(ch) in LEVELS: g.set_level(int(ch), now)
            elif ch in "+=]": g.set_level(g.level + 1, now)
            elif ch in "-_[": g.set_level(g.level - 1, now)
    asyncio.get_running_loop().add_reader(fd, on_key)
    say("keys: 1 to 5 pick a level (its own key restarts it), + and - or the arrows step, p the pick again")

UP = [True]                                              # connected last time: say so once when it goes

async def session(g, tablet):
    """one connection: the level's empty board, then play until the tablet goes (TabletGone)"""
    say("connected"); UP[0] = True
    if g.standby: say(f"standby: hold button {READY} for {READY_S:.0f} s to start the pick")
    elif g.player is None: g.start_pick(time.monotonic())   # once a sitting: a reconnect keeps the player's color
    else: g.set_level(g.level, time.monotonic())       # the level's intro; the timeout prompt counts from its pulse
    while True:
        for e in await tablet.buttons(0.01): g.button(e.t, e.button, e.pressed)   # every release in before update
        now = time.monotonic()
        g.update(now)
        while g.out:
            k = g.out.pop(0)
            if k in QUIET: continue
            if k != "step": say("sound", k)
            await tablet.play(SOUNDS[k])
        await tablet.show(g.render(now))               # the tablet sends it when a framebuffer's slot comes

def stop(*_):                         # asyncio's own Ctrl-C handling has let a copy live on after pkill -INT
    say("stopped"); atexit._run_exitfuncs(); os._exit(0)

async def run(args):
    for sig in (signal.SIGINT, signal.SIGTERM): asyncio.get_running_loop().add_signal_handler(sig, stop)
    say(f"hold-release: level {args.level}; {levels.SLOW_S}/{levels.FAST_S}/{levels.BALL_S} s a button, road {levels.ROAD}, target {levels.TARGET}")
    g = Game(args.level, levels.COLORS.get(args.color), standby=args.color is None and not args.now)   # set up, then the adult starts it
    if sys.stdin.isatty(): keys(g)
    while True:                                          # the tablet sleeps after about six idle minutes
        try:
            async with boppo.connect(log=say) as tablet: await session(g, tablet)
        except boppo.TabletGone as e:
            if UP[0]: say(f"tablet gone ({type(e.__cause__ or e).__name__}); wake it and the level comes back")
            UP[0] = False
        await asyncio.sleep(RETRY_S)

def main():
    global LOG
    ap = argparse.ArgumentParser(description="Hold, Release on a Boppo tablet")
    ap.add_argument("--level", type=int, default=1, choices=sorted(LEVELS), help="start on this level")
    ap.add_argument("--color", choices=list(levels.COLORS), help="the player's color, skipping the pick")
    ap.add_argument("--now", action="store_true", help="skip standby: the pick starts as soon as it connects")
    ap.add_argument("--tick", action="store_true", help="a tick as the glow enters each road button (off: it has frozen the tablet)")
    args = ap.parse_args()
    if args.tick: QUIET.discard("step")
    (HERE / "logs").mkdir(exist_ok=True); LOG = HERE / f"logs/hold-release-{datetime.date.today()}.log"
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        say("stopped")

if __name__ == "__main__":
    main()
