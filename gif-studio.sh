#!/bin/sh
# The GIF studio in one line (gif-studio-install.md): installs what's missing, gets or updates the
# studio, and starts it. Paste into Terminal on a Mac, the first time and every time after:
#   curl -fsSL https://raw.githubusercontent.com/saurinchoksi/boppo-prototypes/main/gif-studio.sh | sh
# What it does, each step skipped when it's done already:
#   uv        uv's own installer (astral.sh), into ~/.local/bin; uv brings the studio's Python
#   the repo  this repo's ZIP into ~/boppo-prototypes, so no git (or Apple's developer tools) is
#             needed; later runs lay a fresh ZIP over it, keeping studio/ (your animations).
#             A git clone there is left alone: update it with `git pull`
#   start     uv run .claude/skills/boppo-gif/studio.py, in the foreground; Control-C stops it
# Arguments after `sh -s --` go to studio.py (`--port 8766`).
# Everything is in the main function, called on the last line, so sh has read the whole script
# before it runs any of it: a piped script cut short does nothing.

main() {
  dir=$HOME/boppo-prototypes
  zip=https://github.com/saurinchoksi/boppo-prototypes/archive/refs/heads/main.zip
  say() { printf 'gif studio: %s\n' "$*"; }

  [ "$(uname)" = Darwin ] || { say "this runs on a Mac only (it draws with macOS's fonts)"; exit 1; }

  # where uv's and Claude Code's installers put them, found without reopening Terminal
  PATH=$HOME/.local/bin:$PATH; export PATH
  if ! command -v uv >/dev/null; then
    say "installing uv, which runs the studio"
    curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_PRINT_QUIET=1 sh || { say "uv didn't install"; exit 1; }
  fi

  if [ -d "$dir/.git" ]; then
    say "using your git copy in $dir (update it with: cd ~/boppo-prototypes; git pull)"
  else
    tmp=$(mktemp -d) || exit 1
    if curl -fsSL -o "$tmp/main.zip" "$zip" && ditto -xk "$tmp/main.zip" "$tmp"; then
      [ -d "$dir" ] && say "updating $dir (your animations in studio/ stay)" || say "getting the studio into $dir"
      ditto "$tmp/boppo-prototypes-main" "$dir" || { say "couldn't write $dir"; exit 1; }
    elif [ -d "$dir" ]; then
      say "couldn't download an update; starting the copy you have"
    else
      say "couldn't download the studio from GitHub; check your internet connection and paste the line again"
      rm -rf "$tmp"; exit 1
    fi
    rm -rf "$tmp"
  fi

  # On a Mac without Apple's developer tools, /usr/bin/python3, install_name_tool and git are
  # placeholders that pop Apple's installer when run. uv runs python3 to ask its version, unless
  # told to use only its own Pythons (UV_PYTHON_PREFERENCE), and install_name_tool, found on PATH,
  # the first time it sets up its Python (crates/uv-python-managed/src/macos_dylib.rs in
  # github.com/astral-sh/uv), a fix that matters only for building native extensions. Claude Code
  # runs git as it starts, for each chat request. The studio needs neither: stand-ins that decline
  # keep the dialog away (uv warns, which -q hides; Claude Code sees no repo).
  UV_PYTHON_PREFERENCE=only-managed; export UV_PYTHON_PREFERENCE
  if ! xcode-select -p >/dev/null 2>&1; then
    stub=$HOME/.cache/boppo-gif-studio/bin
    mkdir -p "$stub" && for tool in install_name_tool git; do
      printf '#!/bin/sh\nexit 1\n' >"$stub/$tool" && chmod +x "$stub/$tool"
    done && PATH=$stub:$PATH
  fi

  command -v claude >/dev/null ||
    say "for the chat box, Claude Code: gif-studio-install.md, \"Claude (optional)\""
  cd "$dir" || exit 1
  say "starting (the first time, it downloads about 35 MB: under a minute)"
  say "leave this window open; press Control-C here to stop the studio"
  # -q: uv's own lines, among them a warning on Macs without Apple's developer tools that doesn't
  # touch the studio (it builds nothing); its errors still show
  exec uv run -q .claude/skills/boppo-gif/studio.py "$@" </dev/null
}

main "$@"
