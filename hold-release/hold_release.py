"""Hold, Release on a Boppo tablet, played from a computer on the same Wi-Fi over Boppo's
WebSocket API. A light moves only while you hold the button; letting go on the target is the
game.

Once a session the player picks a character, a color. They hold their button, 9, and their
light runs out of it along a dim yellow road; letting go on the green target is a hit.
  1 stop-and-go, the target on 6-5, 0.7 s a button: letting go short of the target stops the
    light and the next press moves it on; held past the target's end and its 0.3 s grace is a
    late miss
  2 the target is button 5 only, and it is one go: any release ends the try
  3 as 2, at 0.5 s a button
  4 the full road, 8-7-6-5 up into 0 and 1-2-3, the target on 3, at 0.5 s
  5 as 4 with a ball instead of the trail, at 0.35 s
It climbs by itself: one hit finishes a level (after level 5, back to 1); a miss just plays
again, and says which way: "Oops! Keep holding!" for an early let-go, "Oops, too far." for a
late one.

Each level opens with its board and the player's button lit, steady (levels 1 and 4, where the
road is new, first unfold it), then a beat of silence and the level's line; the button pulses on
the line's last word, their turn, and keeps pulsing while it waits for a press. A press before
that gets no sound and no light, but a finger still down when the turn comes starts the light at
once. A hit: success on the target's flash, then the next level's opening, no fanfare; after
level 5, "You did them all!" as the player's color fills the ring and breathes, then level 1 with
"Let's go again!". The try's rules are tries.py's and the lights levels.py's pure functions;
this script only reads the buttons, keeps time, plays the sounds and logs.

Usage: uv run hold-release/hold_release.py [--level N] [--color C] [--now] [--tick]
Without --color it starts in standby, the board dark but button 4 (top-right) dim white, so it
can be set up ahead: an adult holds it for 2 s, it fills white, and the pick begins; a tap does
nothing. --now skips standby; --color skips the pick; --level is where the pick leads. While it
runs, keys on the computer: 1 to 5 jump to a level and its opening (its own key restarts it),
+ and - or the arrow keys step up and down, p the pick again. Runs until Ctrl-C; when the tablet
sleeps it waits for it to wake. Every release prints with the level, where the light stopped and
the result, also to hold-release/logs/."""
import argparse, asyncio, atexit, datetime, os, pathlib, signal, sys, termios, time, tty, wave

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                     # boppo.py, the tablet, shared by the repo's games
import boppo, levels
from levels import LEVELS
from tries import Tries

RETRY_S = 5.0               # while the tablet sleeps, try to reconnect this often
NUDGE_S = 12.0              # no press this long: the nudge line, once per wait
READY, READY_S = 4, 2.0     # standby: the adult holds button 4 (top-right) this long to start the pick; it fills white
READY_LO = 0.2              # from dim white, lit the whole standby: never an all-dark board
# Sounds at Boppo's default volume (1.0), so the tablet's volume rules. Effects are Boppo's
# built-ins (developer.boppo.com, Audio Files); the lines are sounds/, put on the tablet by
# upload_lines.py and mastered to the loudness of Boppo's own "Woohoo!". success, not
# success_mini_game: that one is ~25 dB quieter.
V = "hold-release/"
PIANO = "/effects/piano_chromatic_scale/{}.qoa"
SOUNDS = {
    "step": "/effects/button_tick.qoa",                  # the light enters a road button: holding moves it
    "hit": "/effects/success.qoa",                       # on the target's first green beat
    "miss_early": V + "oops_hold.wav",                   # "Oops! Keep holding!": an early let-go, every level
    "miss_late": V + "oops_far.wav",                     # "Oops, too far.": a late miss, every level
    "nudge": V + "nudge.wav",
    **{k: V + f"{k}.wav" for k in ("intro", "again", "level2", "level3", "level4", "level5")},   # the levels' lines, after
                                                         # the hit's success, no fanfare; "again": level 1's second pass
    "done": V + "done.wav",                              # "You did them all!", after level 5
    **{k: V + f"{k}.wav" for k in ["pick", "pick_nudge"] + [f"{w}_{c}" for w in ("name", "you") for c in levels.COLORS]},   # the pick's lines
    **{f"note{i}": PIANO.format(n) for i, n in enumerate([1, 3, 5, 8, 10])},   # the reveal: a rising pentatonic note a button
    "chord": PIANO.format(10),                          # the target swells: one high note for now
}
# Every sound is a plain file: sound instructions wrapped in speed, volume or simultaneous went
# with the tablet dropping the connection, so they wait until the cause is known. That's also
# why a press during an opening ("hush") is silent for now.
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

class Game:
    """a session's phases: standby, the pick, and each level's opening and tries (tries.py), from
    the tablet's presses and let-gos, stamped on receipt; what they do comes out as sounds in out, and log lines"""
    def __init__(self, level, player=None, standby=False):
        self.level = level; self.player = player; self.out = []; self.quiet = time.monotonic(); self.nudged = False; self.down = False
        self.t_open = self.t_pick = self.t_ready = None; self.standby = standby
        self.tries = None                               # set_level's: the play, and every press on it, needs a level first
    @property
    def R(self): return LEVELS[self.level]

    def set_level(self, n, now, done=False):
        """level n from the top: its opening, then the player's turn. done: back to 1 after level 5"""
        if n not in LEVELS: return                       # stepped off either end
        self.level = n; self.t_pick = None; self.standby = False; self.player = self.player or levels.BLUE   # a key during the pick: blue
        self.line = "again" if done else "intro" if n == 1 else f"level{n}"
        self.o = levels.opening(n, LINE_S[self.line], DONE_S if done else None); self.t_open = now; self.cue = 0
        self.tries = Tries(n, now, self.o.turn, self.down)
        say(f"level {self.level}: {self.R.name}, {self.R.cell_s} s a button")

    def start_pick(self, now):
        """the pick, once a session; then the level it started on"""
        self.t_pick = now; self.chose = None; self.cue = 0; self.nudged = False; self.standby = False
        self.p = levels.pick(LINE_S["pick"], [LINE_S[f"name_{c}"] for c in levels.PICK]); self.quiet = now + self.p.ready
        say("the pick")

    def button(self, t, idx, pressed):
        """any button: in standby the adult's hold on button 4; during the pick one of the five on
        the top row; after that only the player's"""
        if idx == levels.BUTTON: self.down = pressed    # the player's finger on their button, whatever the phase
        if self.standby:
            if idx == READY: self.t_ready = t if pressed else None   # let go early: nothing
            return
        if self.t_pick is None:
            if idx == levels.BUTTON: self.press(t) if pressed else self.release(t)
            return
        if not pressed or self.chose is not None: return
        self.quiet = t; self.nudged = False
        if idx < len(levels.PICK) and t - self.t_pick >= self.p.names[idx]:   # any color once lit, names still coming
            self.chose, self.t_chose = idx, t; self.out.append(f"you_{levels.PICK[idx]}"); say(f"picked {levels.PICK[idx]}")
        else: self.out.append("hush")                   # a color not lit yet, or not a color

    def picking(self, now):
        """the pick's sounds as they come, its nudge, and when it's done, level 1's opening"""
        e = now - self.t_pick
        while self.chose is None and self.cue < len(self.p.cues) and self.p.cues[self.cue][0] <= e:   # a press stops the names
            self.out.append(self.p.cues[self.cue][1]); self.cue += 1
        if self.chose is None and not self.nudged and now - self.quiet > NUDGE_S: self.nudged = True; self.out.append("pick_nudge")
        if self.chose is not None:                      # the chosen color pours, silently: a tick a step froze the tablet
            c = levels.PICK[self.chose]; end = self.t_chose + levels.picked_s(self.chose, LINE_S[f"you_{c}"])
            if now >= end: self.player = levels.COLORS[c]; self.set_level(self.level, end)

    def opening(self, now): return self.tries is not None and self.tries.before_turn(now)
    def next_level(self): return self.level % len(LEVELS) + 1   # one hit and the level is done; after level 5, back to 1
    def switch(self):
        """the hit's flash is over: the next level's opening"""
        n = self.next_level(); self.set_level(n, self.tries.done_at, done=n == 1)

    def press(self, t):
        if self.tries.done(t): self.switch()             # pressed before it changed
        for h in self.tries.press(t):
            if h.what == "not yet": self.out.append("hush")   # not the player's turn yet
            else: self.quiet = t; self.nudged = False

    def release(self, t):
        happened = self.tries.release(t)
        if happened: self.quiet = t
        for h in happened: self.happened(h, t)

    def update(self, now):
        """the opening's sounds as they come, the tries, and the nudge"""
        if self.standby:                                # held long enough: the pick
            if self.t_ready is not None and now - self.t_ready >= READY_S: say("ready: the pick"); self.start_pick(now)
            return
        if self.t_pick is not None: return self.picking(now)
        if self.tries.done(now): self.switch()           # the next level's opening
        e = now - self.t_open
        while self.cue < len(self.o.cues) and self.o.cues[self.cue][0] <= e:
            k = self.o.cues[self.cue][1]; self.out.append(self.line if k == "line" else k); self.cue += 1
        for h in self.tries.update(now): self.happened(h, now)
        if not self.opening(now) and not self.tries.held and not self.nudged and now - self.quiet > NUDGE_S:
            self.nudged = True; self.out.append("nudge")

    def happened(self, h, now):
        """what the tries say happened, as sounds and log lines"""
        what = h.what
        if what == "step": self.out.append("step")
        elif what == "flash": self.out.append("hit")    # success on the target's first green beat
        elif what == "stop": self.out.append("miss_early"); self.report("release", ", it waits: press again")
        elif what == "turn": self.quiet = now; self.nudged = False   # the nudge counts from the pulse
        elif what == "held in": say(f"level {self.level}: held into the turn, the light starts")
        elif what == "held in again":
            self.quiet = now; self.nudged = False; say(f"level {self.level}: held into the turn after the miss, the light starts")
        elif what in ("release", "held to the end"):
            self.report(what)
            if h.result != "hit": self.out.append(f"miss_{h.result}")   # which way, on every level; no stepping back
            else: n = self.next_level(); say(f"level {self.level}: {'up' if n > self.level else 'back'} to {n} after this try")

    def report(self, what, extra=""):
        say(f"level {self.level} {what}: {self.tries.summary()}{extra}")

    def render(self, now):
        if self.standby:                                # dark but button 4, dim white, filling while held
            L = [levels.OFF] * 40; k = levels.clamp((now - self.t_ready) / READY_S) if self.t_ready is not None else 0.0
            L[READY * 4:READY * 4 + 4] = [levels.scale(levels.WHITE, READY_LO + (1 - READY_LO) * k)] * 4
            return L
        if self.t_pick is not None:
            return levels.pick_lights(now - self.t_pick, self.p, self.chose, now - self.t_chose if self.chose is not None else 0.0)
        if self.opening(now): return levels.opening_lights(self.level, now - self.t_open, self.o, self.player)
        return levels.lights(self.level, self.tries.at(now), self.player)

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
    elif g.player is None: g.start_pick(time.monotonic())   # once a session: a reconnect keeps the player's color
    else: g.set_level(g.level, time.monotonic())       # the level's opening; the nudge counts from its pulse
    while True:
        for p in await tablet.buttons(0.01): g.button(p.t, p.button, p.down)   # every release in before update
        now = time.monotonic()
        g.update(now)
        while g.out:
            k = g.out.pop(0)
            if k in QUIET: continue
            if k != "step": say("sound", k)
            await tablet.play(SOUNDS[k])
        await tablet.show(g.render(now))               # the tablet sends it when a frame's slot comes

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
    ap.add_argument("--tick", action="store_true", help="a tick as the light enters each road button (off: it has frozen the tablet)")
    args = ap.parse_args()
    if args.tick: QUIET.discard("step")
    (HERE / "logs").mkdir(exist_ok=True); LOG = HERE / f"logs/hold-release-{datetime.date.today()}.log"
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        say("stopped")

if __name__ == "__main__":
    main()
