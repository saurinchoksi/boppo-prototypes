# Hold, Release

A light moves only while you hold the button. Letting go on the target is the game.

For ages 4 to 7. The video and the design doc are at
[saurinchoksi.com/boppo](https://saurinchoksi.com/boppo).

## How it plays

The player picks a color, then holds the bottom-right button. Their light runs out of it along
a dim yellow road, and letting go on the green target is a hit. One hit finishes a level; a
miss plays it again and says which way: "Oops! Keep holding!" or "Oops, too far." After
level 5, "You did them all!" and back to level 1.

| Level | |
|---|---|
| 1 | Stop-and-go: letting go short of the two-button target stops the light, and the next press moves it on. |
| 2 | A one-button target, and one go: any release ends the try. |
| 3 | As 2, faster. |
| 4 | The full road, round the corner and along the top row. |
| 5 | As 4, with a ball instead of a trail, faster again. |

## Run it

Pair with the tablet first (the [repo README](../README.md#pairing)). Then, from the repo root:

1. Put the voice lines on the tablet, once:

   ```sh
   uv run hold-release/upload_lines.py
   ```

   They go to `/sd/activities/user/hold-release/` on the tablet.
2. Start the game:

   ```sh
   uv run hold-release/hold_release.py
   ```

   The tablet goes dark except the top-right button, lit dim white. That's standby, so the
   game can be set up before the player sits down. Hold that button for 2 seconds; it fills
   white and the color pick begins.

While it runs, keys on the computer: 1 to 5 jump to a level, + and - or the arrow keys step
between levels, and p starts the color pick again. Ctrl-C stops it. If the tablet goes to
sleep, wake it and the game reconnects, back at the start of the same level. Starting the game
again stops the copy already running. Connecting starts Boppo's WebSocket activity
([WebSocket API](https://developer.boppo.com/docs/websocket)); on our tablet its menu ("Choose
an activity") shows for a few seconds first, which Boppo doesn't document: leave it, and the
game takes over. The tablet sleeping after about six idle minutes is also what we saw, not
something Boppo documents.

| Option | |
|---|---|
| `--now` | Skip standby: the color pick starts as soon as it connects. |
| `--color blue` | Skip the pick (blue, pink, orange, purple or white). |
| `--level 3` | Start on level 3. |
| `--tick` | A tick as the light enters each road button. Off by default: on the test tablet, a voice line starting right after the tick sometimes froze it (what we saw, not in Boppo's docs). |

Every release is printed with the level, where the light stopped and the result, and logged
to `hold-release/logs/`.

## Sounds

The voice lines in `sounds/` are placeholders in my voice until a real record: some recorded,
some cloned with [Chatterbox](https://github.com/resemble-ai/chatterbox), an open-source
voice model. They're 48 kHz, 16-bit mono WAV. Boppo's
[Audio Formats](https://developer.boppo.com/docs/audio-formats) page doesn't recommend WAV,
which is much larger than its MP3 and QOA; ours are still WAV. To use your own, record the lines below under the same
names, then upload them again.

| File | Line |
|---|---|
| `pick` | Pick your color! |
| `name_blue`, `name_pink`, `name_orange`, `name_purple`, `name_white` | Blue! Pink! Orange! Purple! White! |
| `you_blue` … `you_white` | You're Blue! (and so on) |
| `pick_nudge` | Press a color! |
| `intro` | Hold your button... and let go on the green! |
| `nudge` | Press and hold your button! |
| `level2` | Now the green is smaller! |
| `level3` | Faster now. Ready? |
| `level4` | Hold it all the way around, to the green! |
| `level5` | Now it's a ball! Watch out, it moves fast! |
| `done` | You did them all! |
| `again` | Let's go again! |
| `oops_hold` | Oops! Keep holding! |
| `oops_far` | Oops, too far. |

The other sounds (the tick, the success chime, the piano notes) are Boppo's built-ins,
played by name on the tablet. None of them are in this repo.

## The code

- `hold_release.py`: the game. It reads the buttons, keeps time, plays the sounds and logs.
- `tries.py`: the rules of a try: where the light is, hit or miss, and when the next turn comes,
  from the times of the player's presses and let-gos.
- `levels.py`: the levels and every light frame, as pure functions of the level and the state
  of the try.
- `upload_lines.py`: puts `sounds/` on the tablet.
- `../boppo.py`: the tablet, shared by the repo's games: frames, sounds, presses, uploads, and
  what's true of it, such as how fast frames can go.

Tests: `uv run python -m unittest discover -s hold-release`, from the repo root.
