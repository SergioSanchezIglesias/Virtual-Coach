"""Record uncalibrated candidates, never driving cues.

Brake onset crosses 20%; release crosses down through 5%; throttle
reapplication crosses 20% on a later sample. These conservative heuristics
are not safe/calibrated braking points. Clean means continuous observed lap
and identity here: the reader does not expose sporting lap validity.
"""

import json
import math
import re
import time
from pathlib import Path

from .profile import CUE_NAMES, CornerMarker
from .runtime import _closing_reader, check_cancelled, wait_interval
from .session import describe

BRAKE_ON = 0.20
BRAKE_OFF = 0.05
THROTTLE_ON = 0.20


def draft_path(name, directory=Path("recordings")):
    # Reject rather than silently normalize names (including Windows devices).
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name)
            or name.upper() in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                                *[f"COM{i}" for i in range(1, 10)],
                                *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValueError("Use a safe recording name: 1–64 letters, digits, hyphens or underscores; no device names.")
    return Path(directory) / f"{name}.json"


def _identity(sample):
    return sample.track, sample.vehicle, sample.vehicle_class


def record(name, reader, interval=0.02, *, directory=Path("recordings"),
           overwrite=False, sleep=time.sleep, clock=time.monotonic, report=print,
           cancel=None):
    """Record on the caller's thread; optional Event cancellation discards the lap.

    Cancellation is checked before persistence, not during the authorized write.
    """
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Polling interval must be a finite positive number of seconds.")
    path = draft_path(name, directory)
    if path.exists() and not overwrite:
        raise ValueError(f"Draft already exists: {path}; use --overwrite to replace it.")
    markers = []
    pending = None
    release = None
    recording_lap = None
    with _closing_reader(reader):
        check_cancelled(cancel)
        reader.connect()
        check_cancelled(cancel)
        previous = reader.read()
        check_cancelled(cancel)
        identity = _identity(previous)
        report(describe(previous))
        report("Waiting for the next lap boundary; drive without terminal input. "
               "Candidates are uncalibrated, not safe driving points. "
               "Sporting lap validity is not available; drive a clean lap.")
        started = clock()
        while True:
            wait_interval(interval, sleep, cancel)
            sample = reader.read()
            check_cancelled(cancel)
            if _identity(sample) != identity:
                raise ValueError("Session identity changed; recording discarded.")
            delta = sample.lap - previous.lap
            if delta not in (0, 1) or (delta == 0 and sample.distance < previous.distance):
                raise ValueError("Lap telemetry reset or became discontinuous; recording discarded.")
            if delta == 1:
                if sample.distance >= previous.distance:
                    raise ValueError("Lap boundary lacks a distance wrap; recording discarded.")
                if recording_lap is not None:
                    elapsed = clock() - started
                    break
                recording_lap = sample.lap
                started = clock()
                report("Recording one complete lap automatically.")
            elif recording_lap is not None:
                if previous.brake < BRAKE_ON <= sample.brake:
                    pending, release = sample.distance, None
                elif pending is not None and release is None:
                    if previous.brake > BRAKE_OFF >= sample.brake:
                        release = sample.distance
                elif pending is not None and release is not None and previous.throttle < THROTTLE_ON <= sample.throttle:
                    if pending < release < sample.distance and (not markers or pending > markers[-1].throttle):
                        markers.append(CornerMarker(f"Corner {len(markers) + 1}", pending, release, sample.distance))
                    pending, release = None, None
            previous = sample
    # Deliberately not a loadable Profile: stopped review/calibration is required.
    draft = {
        "status": "draft", "calibrated": False,
        "warning": "Automatic candidates are not safe or calibrated driving points.",
        "lap_validity": "unverified; only observed telemetry continuity checked",
        "observed": {"circuit": identity[0], "vehicle": identity[1], "vehicle_class": identity[2]},
        "lap": recording_lap, "duration_seconds": elapsed,
        "thresholds": {"brake_on": BRAKE_ON, "brake_off": BRAKE_OFF, "throttle_on": THROTTLE_ON},
        "candidates": [{"name": m.name, **{cue: m.distances[index] for index, cue in enumerate(CUE_NAMES)}} for m in markers],
    }
    text = json.dumps(draft, indent=2, allow_nan=False) + "\n"
    check_cancelled(cancel)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects against a draft appearing during the lap.
    with path.open("w" if overwrite else "x", encoding="utf-8") as output:
        output.write(text)
    report(f"Saved uncalibrated draft: {path}. Review while stopped before use.")
    return path
