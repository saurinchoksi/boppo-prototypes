# The GIF studio

A page for drawing a Boppo light animation on a timeline and exporting it as a GIF: each row is
one button, each bar a light, played at the tablet's 10 frames a second. With
[Claude Code](https://claude.com/claude-code), a chat box along the bottom makes versions for you
("three versions: one yellow, one pink, one blue"). No tablet needed.

It's part of the [boppo-gif](.claude/skills/boppo-gif/) skill, and runs on a Mac, on your computer
only: nothing is uploaded.

## With Claude Code

Start `claude` anywhere and paste:

> Clone https://github.com/saurinchoksi/boppo-prototypes into ~/boppo-prototypes, then start the
> GIF studio as its gif-studio.md says.

Claude installs what's missing (it asks first) and opens the studio in your browser. Later, run
`claude` in `~/boppo-prototypes` and ask for the studio, or for a GIF ("buttons 4 and 5 pulse
purple, twice"): the skill is there in that folder.

## By hand

About 10 minutes the first time. Each step is a line to paste into Terminal (⌘-Space, type
`Terminal`, Return) and run with Return.

### 1. Install uv

uv runs the studio and fetches what it needs the first time (its own Python, and two drawing
libraries).

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

It ends with `everything's installed!`. **Quit Terminal (⌘-Q) and open it again**, so it finds uv.
`uv --version` then prints `uv` and a version number.

### 2. Get the repo

With git:

```
git clone https://github.com/saurinchoksi/boppo-prototypes ~/boppo-prototypes
```

Without it: on [the repo's page](https://github.com/saurinchoksi/boppo-prototypes), the green
**Code** button, then **Download ZIP**. In Downloads it's `boppo-prototypes-main` (Safari unzips it
for you; from Chrome, double-click `boppo-prototypes-main.zip` first). Move it to your home folder:

```
mv ~/Downloads/boppo-prototypes-main ~/boppo-prototypes
```

### 3. Start it

```
cd ~/boppo-prototypes
uv run .claude/skills/boppo-gif/studio.py
```

The first start downloads about 35 MB and takes under a minute; later ones, a second or two. It
prints `studio: http://127.0.0.1:8765/` and opens the page in your browser. Your animations are
saved in `~/boppo-prototypes/studio/`, one file each, with their GIFs beside them.

Leave Terminal open while you work. To stop the studio, click in Terminal and press Control-C. Next
time, open Terminal and paste the two lines of step 3 again.

### 4. Claude (optional)

Everything above works without Claude. The chat box needs Claude Code and a paid Claude plan (Pro
or Max):

```
curl -fsSL https://claude.ai/install.sh | bash
```

Then restart the studio (Control-C, then step 3). The dot by the chat box turns green when Claude
is on; if it says Claude is signed out, click **Sign in**, which opens your browser.

## Drawing

- **+** makes a new animation. Drag along a button's row to light it; on the right, pick its
  color, its effect (Steady, Pulse, Flash, Spin) and which of its four lights are on.
- **Press** (P) draws a finger pushing the button; **Light** (L) goes back to lights. **Space**
  plays.
- **Export GIF**, top right: the GIF and a still land in `studio/`.
- **?** by the tablet lists every key.
- **Claude**: ask in plain words ("light the bottom row green, one at a time", "#2 but slower", "a
  golf swing meter; ask me a few questions first"). Claude never changes your animation: it writes
  new versions beside it, and you pick one and keep going.

## Updating

With git: `git pull` in `~/boppo-prototypes`. With the ZIP: download it again and replace the
folder, keeping your `studio/` folder. Either way, your animations stay.

## If something goes wrong

- **`command not found: uv`**: quit Terminal (⌘-Q) and open it again.
- **The page doesn't open**: go to http://127.0.0.1:8765/ in your browser.
- **`port 8765 is taken`**: the studio is already running, likely in another Terminal window; use
  that one, or add `--port 8766` to the end of step 3's second line.
