"""Run with python -m lmu_corner_cues PROFILE.json."""

import argparse
import sys
from pathlib import Path

from .audio import BeepSink
from .lmu import LMUReader
from .profile import Profile
from .runtime import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read LMU telemetry and play corner cues on Windows.")
    parser.add_argument("profile", type=Path, help="JSON corner profile for the current track and vehicle/class")
    parser.add_argument("--interval", type=float, default=0.02, help="positive polling interval in seconds (default: 0.02)")
    args = parser.parse_args(argv)
    try:
        profile = Profile.from_json(args.profile.read_text(encoding="utf-8"))
        run(profile, LMUReader(), BeepSink(), args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
