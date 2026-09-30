# Boppo prototypes

Game prototypes for [Boppo](https://boppo.com), a screen-free tablet with ten light-up
buttons. Each game runs on a computer and plays on the tablet over Wi-Fi, through Boppo's
[WebSocket API](https://developer.boppo.com/docs/websocket). One folder per game.

| Game | |
|---|---|
| [Hold, Release](hold-release/) | A light moves only while you hold the button. Letting go on the target is the game. Five levels, ages 4+. |

## What you need

- A Boppo on the same Wi-Fi as your computer.
- macOS or Linux: the games read the keyboard through a Unix terminal.
- [uv](https://docs.astral.sh/uv/). It installs Python and the one dependency (`websockets`)
  the first time you run a game.

## Pairing

The games connect with the tablet's password, which you get once by pairing, as the
introduction to Boppo's [HTTPS API](https://developer.boppo.com/api) describes: the tablet's
address is `boppo-<SERIAL>.local`, the serial number is printed on the bottom of the tablet,
and you approve the pairing on the tablet. The password stays the same until a factory reset
([Security](https://developer.boppo.com/docs/security)).

We've run the games with Developer Mode on
([Developer Mode](https://developer.boppo.com/docs/developer-mode)). Boppo's docs don't require
it for anything the games do, but we haven't tried them without it.

1. Pair with Boppo's [CLI](https://github.com/boppofun/boppo_cli), installed as its README
   says:

   ```sh
   boppo wifi discover          # the tablets on your network, with their serial numbers
   boppo wifi pair <SERIAL>     # the tablet asks: press the green button to approve
   boppo devices get            # the serial number and password
   ```

   Without the CLI, ask the HTTPS API's `get-password` yourself, with an ID of your own for
   the request:

   ```sh
   ID=$(date +%s)
   curl -k -X POST "https://boppo-<SERIAL>.local/get-password?requestid=$ID"
   ```

   It answers `"status": "in-progress"`, and the tablet says another device is trying to
   control it: press the green button to approve. Run the same `curl` again and it answers
   with the password. (`-k` skips checking the tablet's certificate "for simplicity", as
   Boppo's HTTPS API page puts it; the certificate is signed by the
   [Boppo Device CA](https://developer.boppo.com/BoppoDeviceCA.crt).)
2. Copy `pairing.example.json` to `pairing.json` and fill in the host and password. This file
   is ours: the games read it, not the CLI's own store. `pairing.json` is gitignored.

Then follow the game's README.

## The tablet

The games reach the tablet through `boppo.py`, our Python counterpart of Boppo's Rust
[boppo_websocket](https://github.com/boppofun/rust_boppo_websocket): Boppo has no Python
library. It follows Boppo's [WebSocket API](https://developer.boppo.com/docs/websocket), and
departs from it in these ways, each from what we saw on our tablet:

- At most 10 frames a second. Boppo documents no limit, but faster, with sounds on top, has
  hung our tablet's firmware.
- Whitespace bytes in a frame are nudged off. Boppo's docs say a frame is raw bytes, but our
  tablet answers "sl invalid length" to them.
- Starting a game stops any other copy on this computer. The tablet takes one connection and
  a new one drops the old (Boppo's docs say so); our games reconnect on their own, so two
  copies would keep knocking each other off.
- It doesn't check the tablet's certificate, and the WebSocket follows the computer's proxy
  settings. Boppo's own client checks the certificate against the Boppo Device CA and
  connects directly; `boppo.py` should too.

Its tests: `uv run python -m unittest test_boppo`, from the repo root.

## Boppo's docs

The [developer docs](https://developer.boppo.com) cover the WebSocket and HTTPS APIs, the
built-in sounds and the button layout. Boppo
[invites the community](https://developer.boppo.com/docs/contributing) to share new activities.

## License

The code is MIT (see [LICENSE](LICENSE)). The voice lines in `hold-release/sounds/` are not
covered: they're my voice, all rights reserved.
