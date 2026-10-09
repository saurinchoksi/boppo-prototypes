"""The rules of a try, through Tries: presses and releases at given times, what happened and where
the glow is. Times stay a hair off the edges, where float sums could land either side.
Run from the repo root: uv run python -m unittest discover -s hold-release"""
import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import levels
from tries import Tries

MISS, HIT = levels.turn_at("early"), levels.turn_at("hit")   # 2.1 s and 1.75 s: when the button pulses again

def whats(happened): return [h.what for h in happened]

class Level2(unittest.TestCase):
    """0.7 s a button along 4, the target on the last: a hit from 2.1 s held to 3.1 s (its end
    and the 0.3 s grace); the turn at 1 s"""

    def setUp(self): self.t = Tries(2, 0.0, 1.0)

    def test_hit(self):
        self.assertEqual(whats(self.t.press(1.0)), ["press"])
        self.assertEqual(self.t.release(3.5), [("release", "hit")])
        self.assertEqual(self.t.result, "hit"); self.assertTrue(self.t.at(3.5).over)

    def test_the_edges_of_the_target(self):
        for held, happened, result in [(2.09, "release", "early"), (2.11, "release", "hit"),
                                       (3.09, "release", "hit"), (3.11, "held to the end", "late")]:
            t = Tries(2, 0.0, 0.0); t.press(0.0)
            self.assertEqual(t.release(held), [(happened, result)], held)

    def test_release_after_the_grace(self):
        """a late miss when the grace ran out, not at the release"""
        self.t.press(1.0); self.assertEqual(self.t.release(4.5), [("held to the end", "late")])
        self.assertAlmostEqual(self.t.t_end, 4.1)

    def test_held_to_the_end(self):
        self.t.press(1.0)
        self.assertEqual(whats(self.t.update(4.0)), ["turn"])
        self.assertEqual(self.t.update(4.2), [("held to the end", "late")])
        self.assertAlmostEqual(self.t.t_end, 4.1)
        self.assertAlmostEqual(self.t.at(5.0).position, 4.0)          # stopped at the road's end

    def test_steps(self):
        self.t.press(1.0); self.t.update(1.0)
        self.assertEqual([t for t in (1.5, 1.75, 1.8, 2.45, 3.15, 3.8, 4.0) if self.t.update(t)], [1.75, 2.45, 3.15])

    def test_a_press_before_the_turn(self):
        self.assertEqual(whats(self.t.press(0.5)), ["not yet"])
        self.assertFalse(self.t.at(0.9).held)

    def test_held_into_the_turn(self):
        self.t.press(0.5); self.assertEqual(whats(self.t.update(1.0)), ["turn", "held in"])
        self.assertAlmostEqual(self.t.at(2.0).moved, 1.0)

    def test_down_before_the_level(self):
        self.assertEqual(whats(Tries(2, 0.0, 1.0, down=True).update(1.0)), ["turn", "held in"])

    def test_the_turn(self):
        self.assertEqual(self.t.update(0.99), [])
        self.assertEqual(whats(self.t.update(1.0)), ["turn"])
        self.assertEqual(self.t.update(1.01), [])                   # once

    def test_presses_during_the_wait_are_dropped(self):
        self.t.press(1.0); self.t.release(2.0)
        self.assertEqual(self.t.press(2.0 + MISS - 0.01), [])
        self.assertEqual(self.t.release(2.0 + MISS + 0.5), [])      # its release too, though the wait is over
        self.assertEqual(whats(self.t.press(2.0 + MISS + 1.0)), ["press"])
        self.assertAlmostEqual(self.t.at(2.0 + MISS + 1.5).moved, 0.5)   # a new try, from the start

    def test_a_finger_down_when_the_wait_ends(self):
        self.t.press(1.0); self.t.update(1.0); self.t.release(2.0); self.t.press(3.0)
        self.assertEqual(whats(self.t.update(2.0 + MISS + 0.01)), ["turn", "held in again"])
        self.assertTrue(self.t.at(2.0 + MISS + 0.01).held); self.assertIsNone(self.t.result)

    def test_the_turn_after_a_miss(self):
        self.t.press(1.0); self.t.update(1.0); self.t.release(2.0)
        self.assertEqual(self.t.update(2.0 + MISS - 0.01), [])
        self.assertEqual(whats(self.t.update(2.0 + MISS + 0.01)), ["turn"])
        self.assertEqual(self.t.update(2.0 + MISS + 0.02), [])      # once

    def test_the_hit_flashes_then_the_level_is_done(self):
        self.t.press(1.0); self.t.update(1.0); self.t.release(3.5)
        self.assertEqual(self.t.update(3.5 + levels.SETTLE_S - 0.01), [])
        self.assertEqual(whats(self.t.update(3.5 + levels.SETTLE_S + 0.01)), ["flash"])
        self.assertEqual(self.t.update(3.5 + levels.SETTLE_S + 0.02), [])           # once
        self.assertFalse(self.t.done(3.5 + HIT - 0.01)); self.assertTrue(self.t.done(3.5 + HIT + 0.01))
        self.assertAlmostEqual(self.t.done_at, 3.5 + HIT)

    def test_no_next_try_after_a_hit(self):
        self.t.press(1.0); self.t.update(1.0); self.t.release(3.5); self.t.press(4.0)
        self.assertEqual(whats(self.t.update(3.5 + HIT + 0.01)), ["flash"])  # the finger's down, but the level is done
        self.assertFalse(self.t.held)

    def test_summary(self):
        self.t.press(1.0); self.t.release(4.0)
        self.assertEqual(self.t.summary(), "held 3.00s, glow at 4.00 of 4 buttons (1.00 of the road), button 5 1.00 in, 0.20s into the grace: hit")

class Level1(unittest.TestCase):
    """stop-and-go: the target on 6-5, 2 and 3 of the 4 road buttons"""

    def test_release_short_waits(self):
        t = Tries(1, 0.0, 0.0); t.press(0.0)
        self.assertEqual(whats(t.release(0.5)), ["stop"])
        self.assertIsNone(t.result); self.assertFalse(t.at(1.0).over)
        self.assertEqual(whats(t.press(1.0)), ["press"])            # no wait: it moves on at once
        self.assertEqual(t.release(2.2), [("release", "hit")])
        self.assertAlmostEqual(t.moved, 1.7)

    def test_held_to_the_end_across_stops(self):
        t = Tries(1, 0.0, 0.0); t.press(0.0); t.update(0.0); t.release(1.0); t.press(2.0)
        self.assertEqual(t.update(4.2), [("held to the end", "late")])
        self.assertAlmostEqual(t.t_end, 4.1)

if __name__ == "__main__":
    unittest.main()
