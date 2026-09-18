"""Validated, immutable corner profiles with deterministic JSON serialization."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

CUE_NAMES = ("BRAKE", "RELEASE_BRAKE", "THROTTLE")


def _identifier(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _distance(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite non-negative number")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{field} must be a finite non-negative number")


@dataclass(frozen=True)
class CornerMarker:
    name: str
    brake: float
    release_brake: float
    throttle: float

    def __post_init__(self) -> None:
        _identifier(self.name, "marker name")
        for index, cue in enumerate(CUE_NAMES):
            _distance(self.distances[index], f"{self.name}.{cue}")
        if not self.brake < self.release_brake < self.throttle:
            raise ValueError(f"{self.name}: require BRAKE < RELEASE_BRAKE < THROTTLE")

    @property
    def distances(self) -> tuple[float, float, float]:
        return (self.brake, self.release_brake, self.throttle)


@dataclass(frozen=True)
class Profile:
    circuit: str
    markers: tuple[CornerMarker, ...]
    vehicle: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.circuit, "circuit")
        if self.vehicle is not None:
            _identifier(self.vehicle, "vehicle")
        if not isinstance(self.markers, (tuple, list)) or not self.markers:
            raise ValueError("markers must be a non-empty list of corner markers")
        object.__setattr__(self, "markers", tuple(self.markers))
        previous = -1
        names = set()
        for marker in self.markers:
            if not isinstance(marker, CornerMarker):
                raise ValueError("markers must contain CornerMarker values")
            if marker.name in names:
                raise ValueError(f"duplicate marker name: {marker.name}")
            if marker.brake <= previous:
                raise ValueError("markers must have strictly increasing, non-overlapping cue distances")
            names.add(marker.name)
            previous = marker.throttle

    @classmethod
    def from_json(cls, text: str) -> Profile:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON field: {key}")
                result[key] = value
            return result

        if not isinstance(text, str):
            raise ValueError("profile JSON must be text")
        try:
            data = json.loads(text, object_pairs_hook=unique_object)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid profile JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("profile must be a JSON object")
        if not {"circuit", "markers"} <= data.keys() or data.keys() - {"circuit", "vehicle", "markers"}:
            raise ValueError("profile requires circuit and markers; only vehicle is optional")
        if not isinstance(data["markers"], list):
            raise ValueError("markers must be a JSON array")
        markers = []
        for item in data["markers"]:
            if not isinstance(item, dict) or set(item) != {"name", *CUE_NAMES}:
                raise ValueError("each marker requires name, BRAKE, RELEASE_BRAKE, and THROTTLE")
            markers.append(CornerMarker(item["name"], *(item[key] for key in CUE_NAMES)))
        return cls(data["circuit"], tuple(markers), data.get("vehicle"))

    def to_json(self) -> str:
        data = {"circuit": self.circuit, "markers": [
            {"name": marker.name, **{cue: marker.distances[index] for index, cue in enumerate(CUE_NAMES)}}
            for marker in self.markers
        ]}
        if self.vehicle is not None:
            data["vehicle"] = self.vehicle
        return json.dumps(data, indent=2, allow_nan=False) + "\n"
