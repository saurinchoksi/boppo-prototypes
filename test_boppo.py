"""The tablet's rules, over the tablet in memory (boppo.MemorySocket) with a clock the tests move.
Run from the repo root: uv run python -m unittest test_boppo"""
import asyncio, os, pathlib, subprocess, sys, tempfile, textwrap, time, unittest
from unittest import mock

import boppo

HERE = pathlib.Path(__file__).resolve().parent
DIM = boppo.RESTING
def fb(color): return [color] * 40      # a framebuffer, one color

class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t

class Tablet(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sock = boppo.MemorySocket(); self.clock = Clock(); self.logged = []
        self.tablet = boppo.Tablet(self.sock, lambda *a: self.logged.append(" ".join(a)), self.clock)
        await self.tablet.__aenter__()

    async def asyncTearDown(self):
        if not self.tablet._reader.done(): self.tablet._reader.cancel()

    def tick(self, s=0.125): self.clock.t += s                  # a slot and a bit; binary, so exact

    async def test_opens_dim(self):
        self.assertEqual(self.sock.framebuffers(), [DIM])

    async def test_framebuffer_on_the_wire(self):
        self.tick(); await self.tablet.show([(1, 2, 3)] + [(40, 50, 60)] * 39)
        self.assertEqual(self.sock.sent[-1], b"set_lights " + bytes([1, 2, 3] + [40, 50, 60] * 39))

    async def test_set_color_lights_one_button(self):
        f = fb(boppo.OFF); boppo.set_color(f, 3, (255, 0, 0))
        self.assertEqual(f[12:16], [(255, 0, 0)] * 4)
        self.assertEqual(f[:12] + f[16:], [boppo.OFF] * 36)

    async def test_whitespace_bytes_are_nudged_off(self):
        self.tick(); await self.tablet.show([(9, 10, 11), (12, 13, 32)] + [(0, 0, 0)] * 38)
        self.assertEqual(self.sock.framebuffers()[-1][:2], [(14, 14, 14), (14, 14, 33)])

    async def test_unchanged_framebuffer_not_sent(self):
        self.tick(); await self.tablet.show(fb((1, 1, 1)))
        self.tick(); await self.tablet.show(fb((1, 1, 1)))
        self.assertEqual(self.sock.framebuffers(), [DIM, fb((1, 1, 1))])

    async def test_too_soon_the_newest_waits_for_the_slot(self):
        self.tick(); await self.tablet.show(fb((1, 1, 1)))
        self.tick(0.0625); await self.tablet.show(fb((2, 2, 2))); await self.tablet.show(fb((3, 3, 3)))
        self.assertEqual(self.sock.framebuffers(), [DIM, fb((1, 1, 1))])
        self.tick(0.0625); await self.tablet.buttons(0)    # the slot opens: the newest goes out
        self.assertEqual(self.sock.framebuffers(), [DIM, fb((1, 1, 1)), fb((3, 3, 3))])

    async def test_sound_on_the_wire(self):
        await self.tablet.play("hold-release/intro.wav"); await self.tablet.play("/effects/success.qoa")
        self.assertEqual(self.sock.sent[1:], [
            'play_sound {"i": "controller", "id": 1, "sound": "hold-release/intro.wav", "volume": 1.0}',
            'play_sound {"i": "controller", "id": 2, "sound": "/effects/success.qoa", "volume": 1.0}'])

    async def test_buttons_stamped_on_receipt(self):
        self.sock.press(9); await asyncio.sleep(0); self.tick(0.5)
        self.sock.release(9); self.sock.press(4); await asyncio.sleep(0)
        self.assertEqual(await self.tablet.buttons(0.01),
                         [boppo.ButtonEvent(100.0, 9, True), boppo.ButtonEvent(100.5, 9, False), boppo.ButtonEvent(100.5, 4, True)])
        self.assertEqual(await self.tablet.buttons(0.01), [])

    async def test_the_tablets_errors_are_logged(self):
        self.sock.say("error_message sl invalid length"); self.sock.say("sound_finished 1"); await asyncio.sleep(0)
        self.assertEqual(await self.tablet.buttons(0.01), [])
        self.assertEqual(self.logged, ["tablet: error_message sl invalid length"])

    async def test_a_drop_is_tablet_gone(self):
        self.sock.press(9); self.sock.drop(); await asyncio.sleep(0)
        with self.assertRaises(boppo.TabletGone): await self.tablet.buttons(0.01)
        with self.assertRaises(boppo.TabletGone): await self.tablet.buttons(0.01)   # and after
        with self.assertRaises(boppo.TabletGone): await self.tablet.play("x.wav")

    async def test_a_bug_in_reading_is_not_the_tablet_going(self):
        self.sock.say("button nine p"); await asyncio.sleep(0)
        with self.assertRaises(ValueError): await self.tablet.buttons(0.01)

    async def test_closes_dim(self):
        self.tick(); await self.tablet.show(fb((1, 1, 1)))
        self.tick(); await self.tablet.__aexit__(None, None, None)
        self.assertEqual(self.sock.framebuffers()[-1], DIM)
        self.assertTrue(self.sock.dropped)

    async def test_closing_after_a_drop(self):
        """gone already: the goodbye framebuffer's failure doesn't hide why it's closing, and a plain
        close says the tablet's gone"""
        self.sock.drop()
        self.assertFalse(await self.tablet.__aexit__(KeyError, KeyError(), None))
        with self.assertRaises(boppo.TabletGone): await self.tablet.__aexit__(None, None, None)

class Upload(unittest.TestCase):
    def test_request(self):
        sent = []
        class Web:
            def open(self, req, timeout): sent.append((req, timeout)); return mock.Mock(status=201)
        with tempfile.NamedTemporaryFile(suffix=".wav") as f, mock.patch.object(boppo, "_web", Web):
            f.write(b"RIFF"); f.flush()
            self.assertEqual(boppo.upload(f.name, "hold-release/intro.wav", "boppo-X.local", "pw"), 201)
        (req, timeout), = sent
        self.assertEqual((req.get_method(), req.full_url, req.data, timeout),
                         ("POST", "https://boppo-X.local/files/upload?path=/sd/activities/user/hold-release/intro.wav", b"RIFF", 30))
        self.assertEqual(dict(req.header_items()), {"Authorization": "Bearer pw", "Content-type": "application/octet-stream"})

class OnlyMe(unittest.TestCase):
    """one connection to the tablet: a new copy stops the one before it"""
    def setUp(self):
        self.locks = tempfile.TemporaryDirectory(); self.host = f"test-{os.getpid()}.local"
        mock.patch.object(boppo, "LOCKS", pathlib.Path(self.locks.name)).start(); self.addCleanup(mock.patch.stopall)
        mock.patch.object(boppo, "_LOCK", None).start()

    def test_stops_the_copy_before(self):
        before = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
            import pathlib, sys, time; sys.path.insert(0, {str(HERE)!r}); import boppo
            boppo.LOCKS = pathlib.Path({self.locks.name!r}); boppo.only_me({self.host!r}); print("held", flush=True); time.sleep(30)""")],
            stdout=subprocess.PIPE, text=True)
        self.addCleanup(before.kill)
        self.assertEqual(before.stdout.readline(), "held\n")
        said = []; boppo.only_me(self.host, said.append)
        self.assertIsNotNone(before.wait(5))
        self.assertEqual(said, [f"stopped the copy already running (pid {before.pid}, SIGINT)"])
        self.assertEqual((pathlib.Path(self.locks.name) / f"boppo-{self.host}.lock").read_text(), str(os.getpid()))
        boppo._LOCK.close()

    def test_no_copy_before(self):
        said = []; boppo.only_me(self.host, said.append); boppo.only_me(self.host, said.append)   # once a process
        self.assertEqual(said, []); boppo._LOCK.close()

if __name__ == "__main__":
    unittest.main()
