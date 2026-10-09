"""Hold, Release's play, through Game: scripted presses and releases of the player's button, in
10 ms ticks as session() runs, and what comes out: the sounds queued and the lines logged. Then
session() itself, briefly, over the tablet in memory.
Run from the repo root: uv run python -m unittest discover -s hold-release"""
import asyncio, contextlib, pathlib, sys, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boppo, hold_release, levels

TICK = 0.01

def play(level, script, after, down=False, color=levels.BLUE):
    """level's intro from 0 s, then script, [(s after the turn, pressed)], on button 9, run
    until `after` s past the script's last event (the turn, with none). down: the finger
    already on the button when the level starts. Returns the game, [(s after the turn, sound)],
    the log's lines, and fb(s after the turn): the framebuffer sent at the first tick from then."""
    said = []
    with mock.patch.object(hold_release, "say", lambda *a: said.append(" ".join(str(x) for x in a))):
        g = hold_release.Game(level, color); g.down = down; g.set_level(level, 0.0)
        turn = g.phase.o.turn; evs = sorted((turn + dt, p) for dt, p in script); sounds = []; fbs = []; i = 0
        for k in range(int((turn + max([dt for dt, _ in script], default=0.0) + after) / TICK) + 1):
            now = k * TICK
            while i < len(evs) and evs[i][0] <= now: g.button(evs[i][0], levels.BUTTON, evs[i][1]); i += 1
            g.update(now)
            while g.out: sounds.append((round(now - turn, 2), g.out.pop(0)))
            fbs.append((now - turn, g.render(now)))
    return g, sounds, said, lambda t: next(f for at, f in fbs if at >= t)

def button(fb, n):
    """button n's four lights: top, left, right, bottom"""
    return fb[n * 4:n * 4 + 4]

ROAD, TARGET, BLUE = levels.scale(levels.GOLD, levels.ROAD), levels.scale(levels.GREEN, levels.TARGET), levels.BLUE

def filled(lights):
    """all the player's blue: a road button the glow has passed. Its far light comes out 254, the
    fill's last step a hair under 1"""
    return all(c[:2] == (0, 0) and c[2] >= 254 for c in lights)

INTRO = {"intro", "again", "level2", "level3", "level4", "level5", "chord"} | {f"note{i}" for i in range(5)}

def keys(sounds):
    """the sounds without the steps and the levels' intros"""
    return [k for _, k in sounds if k != "step" and k not in INTRO]

def lines(said, word):
    return [s for s in said if word in s]

class Level2(unittest.TestCase):
    """one go: a 1-button target on 5 at the end of the bottom row, 0.7 s a button; a hit is a
    release from 2.1 s held (the glow into button 5) to 3.1 s (its end and the 0.3 s grace)"""

    def test_hit(self):
        g, sounds, said, fb = play(2, [(0.5, True), (3.0, False)], 2.5)
        self.assertEqual(keys(sounds), ["hit"])
        self.assertEqual([t for t, k in sounds if k == "step"], [1.2, 1.9, 2.6])   # into buttons 7, 6, 5
        self.assertEqual([t for t, k in sounds if k == "hit"], [3.25])                # on the flash, SETTLE_S after
        self.assertEqual(lines(said, "release"), ["level 2 release: held 2.50s, glow at 3.57 of 4 buttons (0.89 of the road), button 5 0.57 in: hit"])
        self.assertIn("level 2: up to 3 after this try", said)
        self.assertIn("level 3: faster, 0.5 s a button", said)                       # after the flash, 1.75 s after the release
        self.assertEqual(g.level, 3)

    def test_hit_lights(self):
        g, sounds, said, fb = play(2, [(0.5, True), (3.0, False)], 1.0)
        f = fb(-0.5)                                    # the intro: the board at rest, the player's button steady
        self.assertEqual((button(f, 9), button(f, 8), button(f, 5), button(f, 4)), ([BLUE] * 4, [ROAD] * 4, [TARGET] * 4, [levels.OFF] * 4))
        self.assertTrue(all(0 < c[2] < 255 for c in button(fb(0.2), 9)))   # the turn: it pulses
        f = fb(2.0)                                     # held 1.5 s: the glow through 8 and 7, the button full
        self.assertTrue(filled(button(f, 8)) and filled(button(f, 7)))
        self.assertEqual((button(f, 9), button(f, 5)), ([BLUE] * 4, [TARGET] * 4))
        flash = 3.0 + levels.SETTLE_S                   # then the target: green, the player's color, ...
        self.assertEqual(button(fb(flash + 0.5 * levels.FLASH_S), 5), [levels.GREEN] * 4)
        self.assertEqual(button(fb(flash + 1.5 * levels.FLASH_S), 5), [BLUE] * 4)

    def test_hit_in_the_grace(self):
        g, sounds, said, fb = play(2, [(0.0, True), (3.0, False)], 1.0)
        self.assertEqual(lines(said, "release"), ["level 2 release: held 3.00s, glow at 4.00 of 4 buttons (1.00 of the road), button 5 1.00 in, 0.20s into the grace: hit"])

    def test_early(self):
        g, sounds, said, fb = play(2, [(0.0, True), (1.0, False)], 3.0)
        self.assertEqual(keys(sounds), ["miss_early"])
        self.assertEqual(lines(said, "release"), ["level 2 release: held 1.00s, glow at 1.43 of 4 buttons (0.36 of the road), button 7 0.43 in: early"])
        self.assertEqual(g.level, 2)
        self.assertTrue(filled(button(fb(1.5), 8)))                       # frozen where it stopped
        self.assertEqual(button(fb(1.0 + levels.FREEZE_S + levels.DRAIN_S + 0.1), 8), [ROAD] * 4)   # drained back

    def test_late_held_to_the_end(self):
        """held past the grace: the glow stops at the end, a late miss, with the finger still down;
        the turn comes with it down and the glow starts again at once"""
        g, sounds, said, fb = play(2, [(0.0, True), (7.9, False)], 2.0)
        self.assertEqual(keys(sounds), ["miss_late", "hit"])
        self.assertEqual([t for t, k in sounds if k == "miss_late"], [3.1])
        self.assertEqual(lines(said, "held to the end")[0], "level 2 held to the end: held 3.10s, glow at 4.00 of 4 buttons (1.00 of the road), button 5 1.00 in, 0.30s into the grace: late")
        self.assertIn("level 2: held into the turn after the miss, the glow starts", said)   # at 3.1 + 2.1
        self.assertEqual(lines(said, "release")[0].split(": ", 1)[1][:12], "held 2.70s, ")          # 7.9 - 5.2
        self.assertEqual(g.level, 3)

    def test_late_release_after_the_grace(self):
        g, sounds, said, fb = play(2, [(0.0, True), (3.2, False)], 1.0)
        self.assertEqual(keys(sounds), ["miss_late"])
        self.assertEqual(button(fb(3.5), 5), [TARGET, BLUE, TARGET, TARGET])   # out past the end: the far light, left
        self.assertEqual(lines(said, "level 2 held to the end"), ["level 2 held to the end: held 3.10s, glow at 4.00 of 4 buttons (1.00 of the road), button 5 1.00 in, 0.30s into the grace: late"])

    def test_a_press_before_the_turn_after_a_miss_does_nothing(self):
        """2.1 s after a miss (freeze, drain, empty road) the button pulses; a press and release
        before that are dropped"""
        g, sounds, said, fb = play(2, [(0.0, True), (1.0, False), (2.0, True), (2.5, False), (5.0, True), (7.5, False)], 3.0)
        self.assertEqual(keys(sounds), ["miss_early", "hit"])
        self.assertEqual(len(lines(said, "release")), 2)
        self.assertEqual(lines(said, "release")[1].split(": ", 1)[1][:12], "held 2.50s, ")

    def test_held_through_the_wait_after_a_miss(self):
        """a press during the wait after a miss is dropped, but a finger still down when the
        button pulses starts the glow at once"""
        g, sounds, said, fb = play(2, [(0.0, True), (1.0, False), (2.0, True), (4.5, False)], 1.0)
        self.assertEqual(keys(sounds), ["miss_early", "miss_early"])
        self.assertIn("level 2: held into the turn after the miss, the glow starts", said)
        self.assertEqual(lines(said, "release")[1].split(": ", 1)[1][:12], "held 1.40s, ")   # 4.5 - (1.0 + 2.1)

    def test_a_press_in_the_intro_is_hushed(self):
        g, sounds, said, fb = play(2, [(-1.0, True), (-0.5, False), (0.0, True), (2.5, False)], 1.0)
        self.assertEqual(keys(sounds), ["hush", "hit"])

    def test_held_into_the_turn(self):
        """a finger down through the intro starts the glow on the turn"""
        g, sounds, said, fb = play(2, [(-1.0, True), (2.5, False)], 1.0)
        self.assertEqual(keys(sounds), ["hush", "hit"])
        self.assertIn("level 2: held into the turn, the glow starts", said)
        self.assertEqual(lines(said, "release")[0].split(": ", 1)[1][:12], "held 2.50s, ")

    def test_down_before_the_level_starts(self):
        g, sounds, said, fb = play(2, [(2.5, False)], 1.0, down=True)
        self.assertEqual(keys(sounds), ["hit"])
        self.assertIn("level 2: held into the turn, the glow starts", said)

    def test_timeout_prompt(self):
        """no press for 12 s from the turn: the timeout prompt, once a wait"""
        g, sounds, said, fb = play(2, [], 30.0)
        self.assertEqual([(t, k) for t, k in sounds if k == "timeout"], [(12.01, "timeout")])

    def test_timeout_counts_from_the_pulse_after_an_early_miss(self):
        """released at 1.0 s: the button pulses again 2.1 s later, and the prompt 12 s after that"""
        g, sounds, said, fb = play(2, [(0.0, True), (1.0, False)], 16.0)
        self.assertEqual([(t, k) for t, k in sounds if k == "timeout"], [(15.11, "timeout")])

    def test_timeout_counts_from_the_pulse_after_a_late_miss(self):
        """held to the end, the try over at 3.1 s, released after: the pulse at 5.2 s, the prompt 12 s after"""
        g, sounds, said, fb = play(2, [(0.0, True), (3.5, False)], 16.0)
        self.assertEqual([(t, k) for t, k in sounds if k == "timeout"], [(17.21, "timeout")])

class Level1(unittest.TestCase):
    """stop-and-go: a 2-button target on 6-5; releasing short stops the glow and the next
    press moves it on"""

    def test_no_timeout_prompt_while_holding(self):
        g, sounds, said, fb = play(1, [(0.0, True)], 13.0)
        self.assertNotIn("timeout", keys(sounds))

    def test_stop_and_go(self):
        g, sounds, said, fb = play(1, [(0.0, True), (0.5, False), (1.5, True), (2.7, False)], 2.0)
        self.assertEqual(keys(sounds), ["miss_early", "hit"])
        self.assertEqual(lines(said, "release"), [
            "level 1 release: held 0.50s, glow at 0.71 of 4 buttons (0.18 of the road), button 8 0.71 in: early, it waits: press again",
            "level 1 release: held 1.70s, glow at 2.43 of 4 buttons (0.61 of the road), button 6 0.43 in: hit"])
        self.assertEqual(g.level, 2)

    def test_stop_and_go_lights(self):
        """released 0.71 into button 8: the glow stays there, the far light part-filled, and the button pulses"""
        g, sounds, said, fb = play(1, [(0.0, True), (0.5, False)], 1.0)
        top, left, right, bottom = button(fb(1.0), 8)
        self.assertEqual((top, right, bottom), (BLUE, BLUE, BLUE))
        self.assertNotIn(left, (BLUE, ROAD))
        self.assertTrue(all(0 < c[2] < 255 for c in button(fb(1.0), 9)))

    def test_stop_and_go_steps_count_on(self):
        g, sounds, said, fb = play(1, [(0.0, True), (0.5, False), (1.5, True), (2.7, False)], 0.5)
        self.assertEqual([t for t, k in sounds if k == "step"], [1.7, 2.4])   # button 7 at 0.7 held, 6 at 1.4

    def test_stop_and_go_then_late(self):
        g, sounds, said, fb = play(1, [(0.0, True), (0.5, False), (1.0, True), (4.0, False)], 0.5)
        self.assertEqual(keys(sounds), ["miss_early", "miss_late"])
        self.assertEqual(lines(said, "held to the end")[0].split(": ")[-1], "late")

class Level5(unittest.TestCase):
    """the ball, round the full road to 3, 0.35 s a button; a hit goes back to level 1"""

    def test_hit_goes_back_to_1(self):
        g, sounds, said, fb = play(5, [(0.0, True), (2.6, False)], 2.0)
        self.assertEqual(keys(sounds), ["hit", "done"])
        self.assertIn("level 5: back to 1 after this try", said)
        self.assertEqual((g.level, g.phase.line), (1, "again"))

    def test_press_on_the_switch(self):
        """a press that comes before the tick that switches the level: the next level's intro"""
        g, sounds, said, fb = play(3, [(0.0, True), (1.8, False), (1.8 + levels.turn_at("hit") + 0.001, True)], 0.1)
        self.assertEqual(g.level, 4)
        self.assertEqual(keys(sounds), ["hit", "hush"])

class Session(unittest.IsolatedAsyncioTestCase):
    """session() over boppo's tablet in memory, in real time: what the tablet says reaches the
    Game, and the Game's lights reach the tablet"""
    async def asyncSetUp(self):
        self.said = []; mock.patch.object(hold_release, "say", lambda *a: self.said.append(" ".join(str(x) for x in a))).start()
        self.addCleanup(mock.patch.stopall)
        self.sock = boppo.MemorySocket(); self.tablet = await boppo.Tablet(self.sock, hold_release.say).__aenter__()
        self.addAsyncCleanup(self.close)

    async def close(self):
        """the tablet closed as connect() would: back to DIM, or gone already"""
        with contextlib.suppress(boppo.TabletGone): await self.tablet.__aexit__(None, None, None)

    async def run_for(self, g, s):
        task = asyncio.create_task(hold_release.session(g, self.tablet)); await asyncio.sleep(s); return task

    async def test_standby(self):
        g = hold_release.Game(1, standby=True); task = await self.run_for(g, 0.15); task.cancel()
        f = self.sock.framebuffers()[-1]
        self.assertEqual(button(f, hold_release.READY), [levels.scale(levels.WHITE, hold_release.READY_LO)] * 4)
        self.assertEqual(button(f, 9), [levels.OFF] * 4)

    async def test_the_players_button_reaches_the_game(self):
        g = hold_release.Game(2, BLUE); task = await self.run_for(g, 0.05)
        self.sock.press(9); await asyncio.sleep(0.05); self.assertTrue(g.down)
        self.sock.release(9); await asyncio.sleep(0.05); self.assertFalse(g.down)
        task.cancel()

    async def test_the_games_sounds_reach_the_tablet(self):
        g = hold_release.Game(1); task = await self.run_for(g, 0.05); task.cancel()   # the pick, its line at once
        self.assertEqual(self.sock.sounds(), ["hold-release/pick.wav"])

    async def test_a_drop_ends_it(self):
        g = hold_release.Game(2, BLUE); task = await self.run_for(g, 0.05)
        self.sock.drop()
        with self.assertRaises(boppo.TabletGone): await asyncio.wait_for(task, 1)

if __name__ == "__main__":
    unittest.main()
