"""Read-only boundary for LMU's native shared memory."""

import math
import mmap
import struct
import sys
from contextlib import suppress
from dataclasses import dataclass

import lmu_corner_cues._lmu_layout as layout


class TelemetryError(RuntimeError):
    """An actionable connection or telemetry failure."""


@dataclass(frozen=True)
class Snapshot:
    track: str
    vehicle: str
    vehicle_class: str
    lap: int
    distance: float
    throttle: float = 0.0
    brake: float = 0.0


def _text(data, offset, size):
    value = data[offset:offset + size].split(b"\0", 1)[0].decode("utf-8").strip()
    if not value:
        raise ValueError("missing identifier")
    return value


def _open_map():
    if sys.platform != "win32":
        raise OSError("LMU shared memory requires Windows")
    return mmap.mmap(-1, layout.MAP_SIZE, tagname=layout.MAP_NAME, access=mmap.ACCESS_READ)


class LMUReader:
    """The injectable factory returns a sized, sliceable raw mapping with close()."""

    def __init__(self, factory=None):
        self._factory = factory or _open_map
        self._info = None

    def connect(self):
        if self._info is not None:
            return
        info = None
        try:
            info = self._factory()
            if len(info) != layout.MAP_SIZE:
                raise ValueError("incompatible map size")
            self._info = info
        except (OSError, ValueError) as exc:
            if info is not None:
                with suppress(OSError):
                    info.close()
            raise TelemetryError(
                "Cannot open compatible LMU_Data; run LMU on Windows and enter a driving session."
            ) from exc

    def read(self):
        if self._info is None:
            raise TelemetryError("Connect to LMU before reading telemetry.")
        try:
            # Copy once: never mutate the mapping or retain views across close().
            data = self._info[:]
            if len(data) != layout.MAP_SIZE:
                raise ValueError("incompatible map size")
            active, index, has_vehicle = struct.unpack_from("<BBB", data, layout.TELEMETRY_OFFSET)
            if not (0 < active <= layout.MAX_VEHICLES and index < active and has_vehicle == 1):
                raise ValueError("no valid local player")
            telemetry = layout.TELEMETRY_RECORDS + index * layout.TELEMETRY_RECORD_SIZE
            scoring = layout.SCORING_RECORDS + index * layout.SCORING_RECORD_SIZE
            telemetry_id = struct.unpack_from("<i", data, telemetry)[0]
            scoring_id = struct.unpack_from("<i", data, scoring)[0]
            if telemetry_id == -1 or scoring_id == -1 or telemetry_id != scoring_id:
                raise TelemetryError(
                    "LMU scoring and telemetry player vehicle IDs disagree or are unset; "
                    "re-enter a driving session and retry."
                )
            track = _text(data, telemetry + 96, 64)
            vehicle = _text(data, telemetry + 32, 64)
            _text(data, scoring + 36, 64)
            vehicle_class = _text(data, scoring + 200, 32)
            # Scoring total laps preserves the cue engine's existing lap convention.
            lap = struct.unpack_from("<h", data, scoring + 100)[0]
            distance = struct.unpack_from("<d", data, scoring + 104)[0]
            throttle, brake = struct.unpack_from("<dd", data, telemetry + 388)
            if not all(math.isfinite(value) for value in (distance, throttle, brake)):
                raise ValueError("non-finite telemetry")
            if not (0.0 <= throttle <= 1.0 and 0.0 <= brake <= 1.0):
                raise ValueError("pedals outside inclusive range 0.0–1.0")
            if lap < 0 or distance < 0:
                raise ValueError("negative lap count or lap distance")
            return Snapshot(track, vehicle, vehicle_class, lap, distance, throttle, brake)
        except (OSError, IndexError, TypeError, ValueError, struct.error) as exc:
            raise TelemetryError(
                "LMU telemetry is incompatible or has no valid local player; "
                "start LMU and enter a driving session."
            ) from exc

    def close(self):
        if self._info is not None:
            info, self._info = self._info, None
            info.close()
