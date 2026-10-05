"""Hold, Release's tries on one level, from its opening until its hit has flashed. In: every press
and let-go of the player's button, stamped on receipt. Out: what happened, where the light is,
how each try ended and when the next may start. Where the light stopped comes from those times,
never from the last frame. hold_release.py turns what happened into sounds and log lines;
levels.py's lights draw the snapshot, at().

The light moves only while the button is held, and only from the player's turn: a press before it
is not yet their turn. Held to the target's end, the light stops there and waits GRACE_S, and a
let-go then is still a hit; held past that, the try ends on its own, a late miss. A let-go short
of the target is an early miss, but on level 1, stop-and-go, the light waits there and the next
press moves it on. After a try, presses are dropped until the button pulses again (levels.turn_at);
a finger down then starts the next try at once, as on the level's first turn. One hit, and the
level is done when its flash is."""
from collections import namedtuple
import levels
from levels import LEVELS

GRACE_S = 0.3                   # the light at the target's end, still a hit on a let-go: the benefit of the doubt

Happened = namedtuple("Happened", "what result", defaults=(None,))
Happened.__doc__ = """one thing that happened, in Tries' words (below); result: how the try ended,
"early", "hit" or "late", on the two that end it"""

Try = namedtuple("Try", "moved held over since clock position result", defaults=(0.0, False, False, 0.0, 0.0, 0.0, None))
Try.__doc__ = """the try at a moment, as the lights draw it. moved: seconds the light has moved
(every hold added up on level 1); held: it is moving now; over: the try has ended, at moved;
since: seconds since it ended; clock: seconds since the level's turn, only for the waiting
pulse; position: the light in road buttons, 0 to the road's length; result: "early", "hit" or
"late", once over. Try() is the empty board, waiting for a press."""

def end_s(r): return len(LEVELS[r].road) * LEVELS[r].cell_s      # holding this long reaches the end of the road
def over_s(r): return end_s(r) + GRACE_S                          # holding this long is a late miss

def judge(r, moved):
    """moved: seconds the light has moved, the grace at the end included"""
    lo, hi = levels.span(r); p = moved / LEVELS[r].cell_s
    return "early" if p < lo else "hit" if p < hi + GRACE_S / LEVELS[r].cell_s - 1e-9 else "late"

class Tries:
    """the tries on level r, its opening from t_open and the player's turn turn_s after that;
    down: their finger already on the button. press, release and update say what happened, in
    order, as Happened:
      "not yet"         a press before the turn: no light
      "press"           a press that counts: the light moves
      "stop"            level 1, let go short of the target: the light waits for the next press
      "release"         let go, and the try is over, with its result
      "held to the end" held past the grace, or let go after it: a late miss
      "turn"            the player's turn: their button pulses, after the opening and after each miss
      "held in"         the turn came with the finger down: the light starts
      "held in again"   the same after a miss
      "step"            the light into the next road button
      "flash"           the hit's target starts flashing"""
    def __init__(self, r, t_open, turn_s, down=False):
        self.r, self.R, self.t_open, self.turn_s, self.down, self.turned = r, LEVELS[r], t_open, turn_s, down, False
        self.new_try()
    def new_try(self): self.moved = 0.0; self.t_press = self.t_end = self.result = None; self.c = 0; self.flashed = self.pulsed = False

    @property
    def held(self): return self.t_press is not None
    def moving(self, t): return self.moved + (t - self.t_press if self.t_press is not None else 0.0)
    def position(self, moved): return min(moved, end_s(self.r)) / self.R.cell_s
    def before_turn(self, t): return t < self.t_open + self.turn_s   # the opening: not the player's turn yet
    def done(self, t): return self.result == "hit" and t - self.t_end >= levels.turn_at("hit")   # the hit has flashed: the next level
    @property
    def done_at(self): return self.t_end + levels.turn_at("hit")

    def press(self, t):
        self.down = True
        if self.before_turn(t): return [Happened("not yet")]
        if self.t_end is not None:                      # a new try once the button pulses again
            if t - self.t_end < levels.turn_at(self.result): return []
            self.new_try()
        if self.t_press is None: self.t_press = t
        return [Happened("press")]

    def release(self, t):
        self.down = False
        if self.t_press is None or self.t_end is not None: return []
        moved = self.moving(t); self.t_press = None
        if moved >= over_s(self.r): return self.run_out(t, moved)   # the end came first
        self.moved = moved
        if self.R.again and judge(self.r, moved) == "early": return [Happened("stop")]   # level 1: stopped short, not over
        return self.end(t, moved, "release")

    def update(self, now):
        """the turn, with a finger down or not; the light into each road button, and held to the
        very end of the road: the light stops there, a late miss; the hit's flash"""
        out = []
        if not self.turned and now - self.t_open >= self.turn_s:
            self.turned = True; out.append(Happened("turn"))
            if self.down and self.t_press is None and self.t_end is None: self.t_press = self.t_open + self.turn_s; out.append(Happened("held in"))
        if self.t_end is not None and self.result != "hit" and not self.pulsed and now - self.t_end >= levels.turn_at(self.result):
            self.pulsed = True; out.append(Happened("turn"))   # after a miss: the button pulses again
            if self.down: turn = self.t_end + levels.turn_at(self.result); self.new_try(); self.t_press = turn; out.append(Happened("held in again"))
        if self.t_press is not None:
            moved = self.moving(now); c = int(moved / self.R.cell_s)
            if self.c < c < len(self.R.road): out.append(Happened("step"))
            self.c = max(self.c, c)
            if moved >= over_s(self.r): out += self.run_out(now, moved)   # past the grace
        if self.result == "hit" and not self.flashed and now - self.t_end >= levels.SETTLE_S:
            self.flashed = True; out.append(Happened("flash"))
        return out

    def run_out(self, t, moved):
        """held past the grace, found at t having moved this far: the try ended when the grace did"""
        over = over_s(self.r); return self.end(t - (moved - over), over, "held to the end")
    def end(self, t, moved, what):
        self.t_press = None; self.moved = moved; self.t_end = t; self.result = judge(self.r, moved); return [Happened(what, self.result)]

    def at(self, now):
        """the try at now, for the lights"""
        clock = now - self.t_open - self.turn_s        # the pulse starts from full, as the opening left it
        if self.t_end is not None: return Try(self.moved, False, True, now - self.t_end, clock, self.position(self.moved), self.result)
        moved = self.moving(now); return Try(moved, self.held, clock=clock, position=self.position(moved))

    def summary(self):
        """the try as it stands, for the log: how long held, where the light is, and its judgement"""
        R = self.R; p = self.position(self.moved); c = min(int(p), len(R.road) - 1)
        grace = self.moved - end_s(self.r); grace = f", {grace:.2f}s into the grace" if grace > 0 else ""
        return (f"held {self.moved:.2f}s, light at {p:.2f} of {len(R.road)} buttons ({p / len(R.road):.2f} of the road), "
                f"button {R.road[c]} {p - c:.2f} in{grace}: {judge(self.r, self.moved)}")
