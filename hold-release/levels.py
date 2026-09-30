"""Hold, Release's levels and lights on the Boppo's 40 light zones. Every frame is a pure
function of the level, the state of the try and the player's color: the same state gives the
same frame. opening_lights and pick_lights do the same for a level's opening and for the pick,
by seconds since they began. hold_release.py reads the buttons, keeps time and sends these.

The light is the player's color, running along a yellow road, and it stays their color on the
target. On every level: the player's button, 9, in their color, bright while it moves the light
and dimmer when not; the road dim yellow where the light hasn't reached; the target green; the
road ends at the target, no button past it; unused buttons off. Each road button fills from the
side the light enters: that zone first, then the two side zones together, then the far one.

The light stops at the target's end and waits there tries.GRACE_S, the target full: a let-go
then is still a hit. Held past that, a late miss ends the try: the target back to dim green, only
its far zone lit in the player's color, frozen, the way Boppo's Tennis Rally shows a ball out.
After a miss the light freezes, drains back (the ball fades out) and the player's button pulses
again, from full: your turn. After a hit the target alternates green and the player's color
three times, then holds steady green, and the next level opens.

Zones are 10 buttons x 4 (top row 0-4, bottom row 5-9; per button 0 top, 1 left, 2 right,
3 bottom)."""
import math
from collections import namedtuple

# Speeds, seconds per road button
SLOW_S = 0.7                    # levels 1 and 2
FAST_S = 0.5                    # levels 3 and 4
BALL_S = 0.35                   # level 5: fast, not undoable
# Brightness, a fraction of full
ROAD = 0.22                     # the dim yellow road; a white one read like the button's blink
TARGET = 0.22                   # the green target before the light reaches it
UP = 0.45                       # the player's button while not moving the light
PULSE_S, PULSE_LO = 1.5, 0.25   # waiting for a press, it pulses at the pace of Boppo's own breath
PINK_LO, PINK_UP = 0.6, 0.8     # pink, dimmer than 0.6, reads purple on the tablet: it pulses down to 0.6 and waits at 0.8
# Pauses, seconds
FREEZE_S = 1.3                  # a miss: the light frozen where it stopped ("whoops")
DRAIN_S = 0.5                   # then it drains back to the start (the ball fades out)
EMPTY_S = 0.3                   # the empty road before "your turn"
SETTLE_S = 0.25                 # a hit: the light stopped, before the target flashes
FLASH_S, FLASHES = 0.2, 6       # the target: green, the player's color, three times over
GREEN_S = 0.3                   # then steady green

OFF, WHITE = (0, 0, 0), (255, 255, 255)
YELLOW, GREEN = (255, 200, 0), (0, 255, 0)
BLUE = (0, 0, 255)
COLORS = {"blue": BLUE, "pink": (255, 0, 127), "orange": (255, 127, 0),   # the five characters: blue, orange, white and
          "purple": (191, 0, 255), "white": WHITE}                        # pink (its ROSE) are Boppo's, from rust_boppo_core
                                # purple is ours: Boppo's VIOLET (127, 0, 255) shows 127 at about a quarter, a second blue
BUTTON = 9                      # the player's button, bottom-right; the only one that counts

Level = namedtuple("Level", "name road target cell_s ball again")
BOTTOM = [8, 7, 6, 5]                       # left along the bottom row to the target, the road's end
FULL = [8, 7, 6, 5, 0, 1, 2, 3]             # up at the corner into 0, along the top row to the target on 3
LEVELS = {   # road: buttons in the order the light runs; target: the green ones; again: stop-and-go
    1: Level("stop-and-go, a 2-button target", BOTTOM, [6, 5], SLOW_S, False, True),
    2: Level("a 1-button target, one go", BOTTOM, [5], SLOW_S, False, False),
    3: Level("faster", BOTTOM, [5], FAST_S, False, False),
    4: Level("the full road, target on 3", FULL, [3], FAST_S, False, False),
    5: Level("the ball, faster", FULL, [3], BALL_S, True, False),
}

def clamp(x): return max(0.0, min(1.0, x))
def scale(c, k): return tuple(int(v * k) for v in c)
def lerp(a, b, k): return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))

def shade(c, k):
    """c at brightness k. Pink never below PINK_LO, its red and blue stepping together (the tablet
    shows blue in steps of 8): apart, it wobbles as it breathes"""
    if c != COLORS["pink"]: return scale(c, k)
    b = int(127 * max(k, PINK_LO)) // 8 * 8; return (min(255, 2 * b + 1), 0, b)

def breath(c, w):
    """c w seconds into Boppo's breath, from full; pink breathes shallower"""
    lo = PINK_LO if c == COLORS["pink"] else PULSE_LO
    return shade(c, lo + (1 - lo) * (0.5 + 0.5 * math.cos(2 * math.pi * w / PULSE_S)))

def span(r):
    """the target as positions along the road: [lo, hi) in road buttons"""
    R = LEVELS[r]; at = [R.road.index(n) for n in R.target]
    return min(at), max(at) + 1

def turn_at(result):
    """seconds after a try ends when the player's button pulses again, your turn, and a press
    starts the next try"""
    return SETTLE_S + FLASH_S * FLASHES + GREEN_S if result == "hit" else FREEZE_S + DRAIN_S + EMPTY_S

def order(road, c):
    """(zone, from) for road button c: the entry zone lights from 0, the sides from 0.33, the
    far zone from 0.66 of the way through"""
    key = lambda n: divmod(n, 5)
    (ar, ac), (zr, zc) = (key(road[c - 1]), key(road[c])) if c else (key(road[0]), key(road[1]))
    if zr != ar: (first, last), sides = (3, 0) if zr < ar else (0, 3), (1, 2)       # up: bottom first
    else: (first, last), sides = (2, 1) if zc < ac else (1, 2), (0, 3)              # left: right first
    return (first, 0.0), (sides[0], 0.33), (sides[1], 0.33), (last, 0.66)

def road(L, r, p, player, fade=0.0, gone=0.0, late=False):
    """the road with the player's light filled to p, in their color, the target included. The
    trail keeps what it poured; the ball (level 5) lights the button it is in, the one behind
    fades back to the dim road over one button of travel, and further back is road again. fade:
    buttons of travel since the ball stopped, so its tail finishes fading; gone (0..1) fades the
    whole ball out. late: a late miss, the light out past the target's end: the target dim
    green, its far zone the player's while p is at the end"""
    R = LEVELS[r]; lo, hi = span(r)
    for c, n in enumerate(R.road):
        base = scale(GREEN, TARGET) if lo <= c < hi else scale(YELLOW, ROAD)
        tail = (1.0 if p - c < 1 else clamp(2 - (p - c) - fade)) * (1 - gone) if R.ball else 1.0
        for z, at in order(R.road, c):
            L[n * 4 + z] = base if late and c >= lo else lerp(base, player, clamp((clamp(p - c) - at) / 0.34) * tail)
    if late and p >= hi:                            # the edge, as Tennis Rally's ball out: the last target button's far zone
        z = order(R.road, hi - 1)[-1][0]; n = R.road[hi - 1]; L[n * 4 + z] = player

def lights(r, t, player=BLUE):
    """the 40 zone colors for level r, the try t (tries.Try) and the player's color"""
    L = [OFF] * 40; R = LEVELS[r]; p = t.position; res = t.result   # None until the try is over, and only read after
    own = player if t.held else shade(player, PINK_UP if player == COLORS["pink"] else UP)
    if not t.held and (not t.over or t.since >= turn_at(res)):                  # waiting for a press
        clock = t.since - turn_at(res) if t.over else t.clock           # after a try, from full: your turn
        own = breath(player, clock)
    if not t.over: road(L, r, p, player)
    elif res == "hit":
        e = t.since; fade = e / R.cell_s
        if e >= turn_at("hit"): road(L, r, 0, player)
        else: road(L, r, p, player, fade)
        k = int((e - SETTLE_S) / FLASH_S)
        if SETTLE_S <= e < turn_at("hit"):          # only the target flashes: green, the player's color, then steady green
            for n in R.target: L[n * 4:n * 4 + 4] = [player if k < FLASHES and k % 2 else GREEN] * 4
    else:
        e = t.since; late = res == "late"
        if e < FREEZE_S: road(L, r, p, player, e / R.cell_s, late=late)
        elif e < FREEZE_S + DRAIN_S:
            d = (e - FREEZE_S) / DRAIN_S
            if R.ball: road(L, r, min(p, span(r)[1] - 1e-6), player, 1.0, d, late=late)   # the edge goes as the ball fades
            else: road(L, r, p * (1 - d), player, late=late)
        else: road(L, r, 0, player)
    L[BUTTON * 4:BUTTON * 4 + 4] = [own] * 4
    return L

# --- a level's opening, before the first try: the level's board with the player's button lit,
# steady at full, a beat of silence, the level's line, and the button pulses on its last word.
# Levels 1 and 4, where the road is new, unfold it with the line over it, the line starting on
# the first note, and the player's turn comes when the later of the two ends. The road reveal: a
# sweep at the level's speed from where the road starts to the target, a rising piano note as it
# enters each button, its front shimmering (all four zones lit, one dipped, a different one each
# frame), the road behind at half; the target swells green with a chord; everything fades to the
# dim road together (never far end first: that's the miss's drain)
REVEAL = {1: 0, 4: 3}           # the levels with a reveal, and the road button it unfolds from: level 1
                                # beside the player's button on a dark board; level 4 level 3's target, button 5
BEFORE_S = 0.8                  # the board as it was, before the sweep
SWELL_S, SWELLED_S = 0.5, 0.5   # the target swells, then holds
FADE_S = 0.8                    # the new road down to dim
HALF = 0.5                      # the revealed road behind the sweep
DIP, SHIMMER = 0.4, (0, 2, 3, 1)   # the front button's dipped zone, frame by frame: top, right, bottom, left, clockwise as Boppo's swirl
CLEAR_S = 0.6                   # level 1's second pass: level 5's road fades out, together, before the reveal
RING, RING_S = [9, 8, 7, 6, 5, 0, 1, 2, 3, 4], 0.1   # the finish: the player's color round the ring, clockwise from their button,
FINALE_S = len(RING) * RING_S + 2 * PULSE_S          # a hard step a button, then all ten breathe twice
HUSH_S = 0.5                    # the silence before the line
LAST_S = 0.4                    # the player's button pulses this long before the line ends: on its last word

Opening = namedtuple("Opening", "turn cues start sweep swell fade clear", defaults=(None,) * 5)
Opening.__doc__ = """turn: seconds from the level's start to the player's turn, their button
pulsing; cues: the opening's sounds as (at, key): "line" the level's line, "noteN" the reveal's
Nth note, "chord", "done"; a reveal's road button it unfolds from, and when its sweep, swell and
fade start; clear: when the finish starts fading out, after "You did them all!" """

def opening(r, line_s, done_s=None):
    """level r's opening; line_s: its line's length in seconds. done_s: level 1 after level 5's
    hit, "You did them all!" first, this long"""
    t, cues, rv = 0.0, [], {}
    if done_s is not None: cues.append((t, "done")); t += max(done_s, FINALE_S); rv["clear"] = t; t += CLEAR_S
    if r in REVEAL:                 # the line starts with the first note: the turn comes when the later ends
        start = REVEAL[r]; sweep = t + BEFORE_S; m = span(r)[0] - start; cs = LEVELS[r].cell_s
        cues += [(sweep + i * cs, f"note{i}") for i in range(m)]
        swell = sweep + m * cs; cues.append((swell, "chord"))
        rv.update(start=start, sweep=sweep, swell=swell, fade=swell + SWELL_S + SWELLED_S)
        cues.append((sweep, "line")); cues.sort(key=lambda c: c[0])
        return Opening(max(rv["fade"] + FADE_S, sweep + line_s - LAST_S), cues, **rv)
    t += HUSH_S; cues.append((t, "line"))
    return Opening(t + line_s - LAST_S, cues, **rv)

def reveal(L, r, e, o):
    """the road reveal, e seconds into the opening o of level r"""
    R = LEVELS[r]; lo, hi = span(r)
    p = o.start + clamp((e - o.sweep) / (R.cell_s * (lo - o.start))) * (lo - o.start)   # the sweep's front, in road buttons
    k = clamp((e - o.swell) / SWELL_S) if e >= o.swell else 0.0; f = clamp((e - o.fade) / FADE_S) if e >= o.fade else 0.0
    for c, n in enumerate(R.road):
        if c < o.start: L[n * 4:n * 4 + 4] = [scale(YELLOW, ROAD)] * 4           # the road the player already knows
        elif c == o.start and e < o.sweep and o.start: L[n * 4:n * 4 + 4] = [scale(GREEN, TARGET)] * 4   # the old target, still green
        elif lo <= c < hi: L[n * 4:n * 4 + 4] = [scale(GREEN, k * (1 - f) + TARGET * f)] * 4
        elif c >= hi or p <= c or e < o.sweep: continue                          # past the target, or not reached: dark
        elif p < c + 1 and e < o.swell:                                          # the front: a shimmer
            dip = SHIMMER[(int(e / 0.1) + c) % 4]
            for z in range(4): L[n * 4 + z] = scale(YELLOW, DIP if z == dip else 1.0)
        else: L[n * 4:n * 4 + 4] = [scale(YELLOW, HALF * (1 - f) + ROAD * f)] * 4

def opening_lights(r, e, o, player):
    """the 40 zone colors e seconds into level r's opening o, the player's button lit, steady at
    full: after level 5, the finish, their color filling the ring and breathing, then fading
    out; the reveal; then the board at rest"""
    L = [OFF] * 40
    if o.clear is not None and e < o.clear + CLEAR_S:
        w = e - len(RING) * RING_S                                # into the breath, from full
        for n in RING[:int(e / RING_S + 1e-9) + 1]: L[n * 4:n * 4 + 4] = [breath(player, w) if w > 0 else player] * 4
        L = [scale(c, 1 - clamp((e - o.clear) / CLEAR_S)) for c in L]
        if e < o.clear: return L                                  # the player's button breathes with the rest
    elif o.sweep is not None and e < o.fade + FADE_S: reveal(L, r, e, o)
    else: road(L, r, 0, player)
    L[BUTTON * 4:BUTTON * 4 + 4] = [player] * 4
    return L

# --- the pick, once a session before level 1: "Pick your color!", then the five light along the
# top row one at a time, each as its name plays; they hold full while the player chooses. On a
# press the others go out while the chosen one swirls, Boppo's mark for a choice made, then it
# pours to the player's button, 9: along the top row to 4 and down, its front filling each
# button as the road fills, a fading tail behind, no tick
PICK = list(COLORS)             # on buttons 0 to 4, in this order
NAME_S = 0.8                    # a name's turn at least, its color fading in over LIT_S
LIT_S = 0.3
OUT_S, KEEP_S = 0.6, 0.3        # after the press: the others go out; the chosen one holds alone
SWIRL_LO = 0.5                  # meanwhile it swirls: one zone full, the others at this, clockwise, a step a frame
POUR_S, TAIL = 0.15, 2.0        # then it pours to the player's button, POUR_S a button, its tail TAIL buttons long
YOURS_S = 0.5                   # the player's button lit after "You're Blue!", before level 1 opens

Pick = namedtuple("Pick", "names ready cues")
Pick.__doc__ = """names: seconds from the pick's start when each color lights, and can be
chosen; ready: all five lit; cues: its sounds as (at, key)"""

def pick(prompt_s, name_s):
    """the pick's times; prompt_s: "Pick your color!"'s length, name_s: each name's"""
    t = prompt_s + HUSH_S; names, cues = [], [(0.0, "pick")]
    for c, s in zip(PICK, name_s): names.append(t); cues.append((t, f"name_{c}")); t += max(NAME_S, s + 0.2)
    return Pick(names, t, cues)

def walk(chose):
    """the buttons the chosen color pours through to the player's button: along the top row to
    4, down to 9. Not down and along the bottom: that would run the road backwards before its reveal"""
    return list(range(chose, len(PICK))) + [BUTTON]

def poured(chose, since):
    """how far along walk(chose) the color's front is, in buttons, since seconds after the press"""
    return max(0.0, since - OUT_S - KEEP_S) / POUR_S

def picked_s(chose, you_s):
    """seconds from the press to level 1's opening: the pour done, its tail drained into the
    player's button"""
    return max(OUT_S + KEEP_S + (len(walk(chose)) - 1 + TAIL) * POUR_S, you_s) + YOURS_S

def pick_lights(e, p, chose=None, since=0.0):
    """the 40 zone colors e seconds into the pick p; chose: the pick's index, since seconds before"""
    L = [OFF] * 40
    for n, (c, at) in enumerate(zip(PICK, p.names)):
        k = clamp((e - at) / LIT_S)
        if chose is not None: k = 1.0 if n == chose else clamp((e - since - at) / LIT_S) * (1 - clamp(since / OUT_S))   # not lit yet: stays dark
        L[n * 4:n * 4 + 4] = [scale(COLORS[c], k)] * 4
        if n == chose:                                          # the swirl, as the reveal's front turns (SHIMMER)
            for z in range(4): L[n * 4 + z] = COLORS[c] if z == SHIMMER[int(since / 0.1 + 1e-9) % 4] else shade(COLORS[c], SWIRL_LO)
    if chose is not None and since >= OUT_S + KEEP_S:           # the chosen color pours to the player's button
        path, color, front = walk(chose), COLORS[PICK[chose]], poured(chose, since)
        for c, n in enumerate(path):
            k = 1.0 if c == len(path) - 1 else clamp(1 - (front - c) / TAIL)   # behind the front, it fades; the player's button stays
            for z, at in order(path, c):                        # each fills from the side it enters, as the road
                L[n * 4 + z] = scale(color, k * (1.0 if c == 0 else clamp((clamp(front - c + 1) - at) / 0.34)))
    return L
