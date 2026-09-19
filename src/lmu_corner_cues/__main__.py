"""Session inspection, automatic recording, stopped profile review, and driving."""

import argparse
import sys
from pathlib import Path

from .application import load_profile, probe, record, run
from .audio import BeepSink
from .lmu import LMUReader
from .wizard import create_profile, stopped_flow_guard


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect LMU, record uncalibrated drafts, or play corner cues.")
    parser.add_argument("--interval", type=float, default=0.02, help="positive polling interval in seconds (default: 0.02)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="open the Windows Tkinter desktop interface")
    commands.add_parser("session", help="show observed session identity without audio or files")
    drive = commands.add_parser("drive", help="drive using a calibrated JSON profile")
    drive.add_argument("profile", type=Path)
    recording = commands.add_parser("record", help="automatically record one lap as an uncalibrated draft")
    recording.add_argument("name", help="safe draft name (letters, digits, hyphens, underscores)")
    recording.add_argument("--overwrite", action="store_true", help="explicitly permit replacing an existing draft")
    profiles = commands.add_parser("profile", help="review recorded candidates while stopped; no JSON editing needed")
    profile_commands = profiles.add_subparsers(dest="profile_command", required=True)
    create = profile_commands.add_parser("create", help="turn an unverified draft into a confirmed driving profile",
        description="After record exits, stop driving and review each label and distance in meters. Nothing is saved without explicit confirmation; type cancel to exit.")
    create.add_argument("draft", type=Path, help="completed unverified draft, e.g. recordings/lap.json")
    create.add_argument("--overwrite", action="store_true", help="permit replacement of the chosen profiles/<name>.json after confirmation")
    for command in (drive, recording):
        command.add_argument("--interval", type=float, default=argparse.SUPPRESS, help="positive polling interval in seconds")
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Preserve the original PROFILE.json invocation as well as drive PROFILE.
    if arguments and arguments[0] not in {"session", "record", "drive", "profile", "gui"} and not arguments[0].startswith("-"):
        arguments.insert(0, "drive")
    args = parser.parse_args(arguments)
    try:
        if args.command == "gui":
            from .gui import launch
            launch()
        elif args.command == "session":
            probe(LMUReader())
        elif args.command == "record":
            with stopped_flow_guard():
                record(args.name, LMUReader(), args.interval, overwrite=args.overwrite)
        elif args.command == "profile":
            with stopped_flow_guard():
                create_profile(args.draft, overwrite=args.overwrite)
        else:
            profile = load_profile(args.profile)
            run(profile, LMUReader(), BeepSink(), args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
