"""Pure lap-aware cue progression, independent of telemetry and audio."""

from dataclasses import dataclass

from .profile import CUE_NAMES, Profile, _distance


@dataclass(frozen=True)
class Cue:
    lap: int
    marker: str
    kind: str
    distance: float


class CueEngine:
    """Emit all reached cues, including on the first sample or skipped frames.

    A distance decrease within the same lap suspends emission until the lap
    identifier changes. This avoids duplicate or stale cues while telemetry's
    lap counter catches up at start/finish. Call reset() for a new session.
    """

    def __init__(self, profile: Profile) -> None:
        if not isinstance(profile, Profile):
            raise ValueError("profile must be a Profile")
        schedule = []
        for marker in profile.markers:
            distances = marker.distances
            if len(CUE_NAMES) != len(distances):
                raise ValueError("cue names and marker distances must have equal lengths")
            schedule.extend(
                (marker.name, kind, distances[index])
                for index, kind in enumerate(CUE_NAMES)
            )
        self._schedule = tuple(schedule)
        self.reset()

    def reset(self) -> None:
        self._lap = None
        self._distance = 0
        self._next = 0
        self._wrapped = False

    def update(self, lap: int, distance: float) -> tuple[Cue, ...]:
        if isinstance(lap, bool) or not isinstance(lap, int) or lap < 0:
            raise ValueError("lap must be a non-negative integer")
        _distance(distance, "lap distance")
        if lap != self._lap:
            self.reset()
            self._lap = lap
        elif distance < self._distance:
            self._wrapped = True
        self._distance = distance
        if self._wrapped:
            return ()
        cues = []
        while self._next < len(self._schedule):
            marker, kind, target = self._schedule[self._next]
            if target > distance:
                break
            cues.append(Cue(lap, marker, kind, target))
            self._next += 1
        return tuple(cues)
