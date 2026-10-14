# The GIF studio

A page for drawing a Boppo light animation on a timeline and exporting it as a GIF: each row is
one button, each bar a light, played at the tablet's 10 frames a second. With
[Claude Code](https://claude.com/claude-code), a chat box along the bottom makes versions for you
("three versions: one yellow, one pink, one blue"). No tablet needed.

It's part of the [boppo-gif](.claude/skills/boppo-gif/) skill, and runs on a Mac, on your computer
only: nothing is uploaded.

## Three ways in

Pick the one that fits. They all end with the studio open in your browser.

- **You use Claude Code**: [With Claude Code](#with-claude-code).
- **You've never used git, or aren't sure**: [One line](#one-line). Most people.
- **You use git already**: [With git](#with-git).

## With Claude Code

Start `claude` anywhere and paste:

> Read https://github.com/saurinchoksi/boppo-prototypes/blob/main/gif-studio-install.md and set up
> the GIF studio as it says.

If a window asks to install Apple's "command line developer tools", click **Not Now**: the studio
doesn't need them.

Claude installs what's missing (it asks first) and opens the studio in your browser. Later, run
`claude` in `~/boppo-prototypes` and ask for the studio, or for a GIF ("buttons 4 and 5 pulse
purple, twice"): the skill is there in that folder.

## One line

Open Terminal (⌘-Space, type `Terminal`, Return), paste this line and press Return:

```
curl -fsSL https://raw.githubusercontent.com/saurinchoksi/boppo-prototypes/main/gif-studio.sh | sh
```

It installs uv (which runs the studio and fetches its own Python), downloads the studio into
`~/boppo-prototypes`, and starts it. The first time takes under a minute. It prints
`studio: http://127.0.0.1:8765/` and opens the page in your browser.

Leave Terminal open while you work. To stop the studio, click in Terminal and press Control-C.
**Next time, paste the same line**: it also updates the studio, keeping your animations.

## With git

```
git clone https://github.com/saurinchoksi/boppo-prototypes ~/boppo-prototypes
cd ~/boppo-prototypes
uv run .claude/skills/boppo-gif/studio.py
```

**uv** runs the studio: the first time, it fetches the right Python and the two drawing libraries,
kept apart from anything else on your Mac. `uv --version` says whether you have it; if it says
`command not found`, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`, then quit
Terminal (⌘-Q) and open it again. Or, after the clone, paste [the one line](#one-line): it leaves
your clone alone and installs uv if it's missing.

Update with `git pull` in `~/boppo-prototypes`.

## Claude (optional)

Everything above works without Claude. The chat box needs Claude Code and a paid Claude plan (Pro
or Max).

1. Leave the studio running. In Terminal, open a new window (⌘-N).
2. In the new window, paste this line and press Return. It ends with `Installation complete!`.
   ```
   curl -fsSL https://claude.ai/install.sh | bash
   ```
3. Reload the studio's page in your browser. By the chat box, click **Sign in**, which opens your
   browser to sign in to Claude. The dot turns green when Claude is on.

## If something goes wrong

- **The page doesn't open**: go to http://127.0.0.1:8765/ in your browser.
- **`port 8765 is taken`**: the studio is already running, likely in another Terminal window; use
  that one, or start this one on another port: add `-s -- --port 8766` after the one line's `sh`, or
  `--port 8766` after `uv run`'s line.

## Once it's open

How to draw, export and ask Claude for versions: [Using the GIF studio](gif-studio-usage.md).
