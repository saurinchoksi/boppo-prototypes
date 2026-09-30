"""Put Hold, Release's voice lines on the tablet: sounds/<line>.wav to
/sd/activities/user/hold-release/<line>.wav, over Wi-Fi with the password in pairing.json.
Names limit it to those lines; none uploads every line.
Usage: uv run hold-release/upload_lines.py [line ...]"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import boppo

files = [HERE / f"sounds/{n}.wav" for n in sys.argv[1:]] or sorted((HERE / "sounds").glob("*.wav"))
for f in files:
    print(f"{f.name:16s} {boppo.upload(f, f'hold-release/{f.name}')}")
