---
name: boppo-gif
description: GIFs of the Boppo tablet, drawn without it: an illustrated Boppo whose buttons light
  as a game would light them. Use to draw a new one, change one or look at one, and before a GIF
  generator is written, changed or run.
---

# Drawing the tablet

A generator is a Python script that draws GIFs of the tablet with this folder's drawing and writes
them by name, each with a still. G = this folder's `gif.py`, run as a command (`<folder>/gif.py`,
or `uv run <folder>/gif.py` if the copy lost its exec bit), not with `python3`: it needs only
[uv](https://docs.astral.sh/uv/), which brings Pillow and numpy. `G` alone prints its usage.

Which generator:
- **A change to a GIF**: the generator that wrote it; its docstring names each GIF it writes. A
  project that keeps GIFs may name this skill in its docs (`grep -rl boppo-gif` there): read what
  that finds first.
- **A new GIF**: `G new <path>.py [<out dir>]`, a starter that lights button 0 green for 2 s, or a
  copy of the generator whose GIFs come closest.
- **A one-off**: `G new /tmp/<name>.py`. It skips step 3: its GIFs stay where step 1 wrote them.

The drawing (`tablet-drawing.py`, which every generator `exec()`s, so a change to it changes every
GIF: re-check them all). Buttons 0-4 are the top row, 5-9 the bottom row, the kid's side; the
drawing's key for button n is `(n // 5, n % 5)`. `frame(lights, presses)` is one image: `lights`
maps a key to its lit sides, each of a button's four lights (top, left, right, bottom) a
`(color, strength 0-1)`, filled by `all_lights(lights, key, color, strength)` or
`add_light(lights, key, side, color, strength)`; `presses` maps a key to how far it's pushed in,
0-1. A color is an RGB tuple; the drawing has `GREEN` and `BLUE`. FPS 10 is the tablet's: a GIF
stores whole hundredths, so 15 fps plays about 10% fast. To check that buttons are lit green in
the first frame (a target, say), pass `dots` to `gifcheck.check`: its docstring says how.

1. **Draw it.** Change the generator, then `G check <generator> [name ...]`. Done when it
   exits 0: no `<<` line, and a sheet path for each GIF.
2. **Look at it.** Read every sheet G printed, and say what each GIF shows, frame by frame,
   against what was asked. A moment shorter than the sheet's spacing (a flash, a press) can fall
   between its frames: `G sheet <gif> <t1> <t2> ...` at its times (a video works too, with
   ffmpeg installed). Done when every GIF is described and matches the ask; back to 1 for any
   that doesn't.
3. **Write it**: `G run <generator> [name ...]`. A starter writes beside itself, so from
   anywhere; a generator with a relative output path, from the folder that path starts in (its
   docstring says). Done when each GIF and its still are written: in a repo, `git status` shows
   them.
4. **The asker's call.** Whether a GIF looks right is the call of whoever asked for it: give them
   each GIF's path and what to watch for. Done when they say yes; a no goes back to 1 with their
   words.
