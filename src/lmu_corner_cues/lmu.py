"""Read-only boundary for LMU's native shared memory."""

from dataclasses import dataclass


class TelemetryError(RuntimeError):
    """An actionable connection or telemetry failure."""


@dataclass(frozen=True)
class Snapshot:
    track: str
    vehicle: str
    vehicle_class: str
    lap: int
    distance: float


def _text(value):
    if isinstance(value, bytes):
        return value.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    raise ValueError("expected a shared-memory byte string")


class LMUReader:
    def __init__(self, factory=None):
        self._factory = factory
        self._info = None

    def connect(self):
        if self._info is not None:
            return
        factory = self._factory
        if factory is None:
            try:
                from pyLMUSharedMemory import lmu_data  # pyright: ignore[reportMissingImports]

            except ImportError as exc:
                raise TelemetryError(
                    "Install the optional pyLMUSharedMemory dependency in this Python environment."
                ) from exc
            factory = lmu_data.SimInfo
        try:
            self._info = factory()
        except (OSError, ValueError) as exc:
            raise TelemetryError("Cannot open LMU_Data; run LMU on Windows and enter a driving session.") from exc

    def read(self):
        if self._info is None:
            raise TelemetryError("Connect to LMU before reading telemetry.")
        try:
            data = self._info.LMUData
            index = data.telemetry.playerVehicleIdx
            if index < 0 or index >= len(data.telemetry.telemInfo) or index >= len(data.scoring.vehScoringInfo):
                raise ValueError("invalid player index")
            telemetry = data.telemetry.telemInfo[index]
            scoring = data.scoring.vehScoringInfo[index]
            if not scoring.mIsPlayer:
                raise ValueError("no local player")
            track, vehicle = _text(telemetry.mTrackName), _text(telemetry.mVehicleName)
            if not track or not vehicle:
                raise ValueError("missing track or vehicle")
            return Snapshot(track, vehicle, _text(scoring.mVehicleClass), scoring.mTotalLaps, scoring.mLapDist)
        except (OSError, AttributeError, IndexError, TypeError, ValueError) as exc:
            raise TelemetryError(
                "LMU telemetry has no valid local player; start LMU and enter a driving session."
            ) from exc

    def close(self):
        if self._info is not None:
            info, self._info = self._info, None
            info.close()
