"""Stopped, explicitly confirmed conversion of unverified lap candidates."""

import json
import socket
from contextlib import contextmanager
from pathlib import Path

from .profile import CUE_NAMES, CornerMarker, Profile
from .recording import draft_path


@contextmanager
def stopped_flow_guard():
    """Exclude concurrent CLI record/create processes, even in different folders.

    A loopback socket is only an OS-owned lock: no listen, accept, or data.
    A busy/unavailable port fails closed; process exit releases the lock.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as lock:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            lock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        try:
            lock.bind(("127.0.0.1", 47863))
        except OSError as exc:
            raise RuntimeError("Recording/profile wizard already active, or local guard port 47863 unavailable. Stop the other process before retrying.") from exc
        yield


class _Cancelled(Exception):
    pass


def _draft_profile(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read recording draft: {exc}") from exc
    if (not isinstance(data, dict) or data.get("status") != "draft"
            or type(data.get("calibrated")) is not bool or data["calibrated"]
            or data.get("lap_validity") != "unverified; only observed telemetry continuity checked"):
        raise ValueError("Expected an unverified, non-calibrated recording draft, not a driving profile.")
    observed = data.get("observed")
    if not isinstance(observed, dict) or any(
        not isinstance(observed.get(key), str) or not observed[key].strip()
        for key in ("circuit", "vehicle", "vehicle_class")
    ):
        raise ValueError("Draft requires observed circuit, vehicle and vehicle_class.")
    profile = Profile.from_json(json.dumps({
        "circuit": observed["circuit"], "vehicle": observed["vehicle"],
        "markers": data.get("candidates"),
    }))
    return profile, observed["vehicle_class"]


def create_profile(draft, *, overwrite=False, ask=input, report=print):
    """No telemetry/audio; callers must hold stopped_flow_guard for this flow."""
    def prompt(message):
        answer = ask(message).strip()
        if answer.lower() in {"q", "quit", "cancel"}:
            raise _Cancelled()
        return answer

    def show(marker):
        report(f"{marker.name}: brake {marker.brake:g} m | release {marker.release_brake:g} m | throttle {marker.throttle:g} m")

    profile, vehicle_class = _draft_profile(draft)
    report(f"Circuit: {profile.circuit}\nVehicle: {profile.vehicle}\nClass: {vehicle_class}")
    report("UNVERIFIED: continuity only, not sporting lap validity or safe/calibrated driving points.")
    for marker in profile.markers:
        show(marker)
    report("Review only after the lap has finished and you have stopped driving. Type cancel at any prompt to exit without saving.")
    try:
        if prompt("Are you stopped, with recording finished? Type STOPPED to continue: ") != "STOPPED":
            raise _Cancelled()
        markers = []
        for marker in profile.markers:
            while True:
                report("Accept each value with Enter, or type its replacement (meters from lap start).")
                name = prompt(f"Corner label [{marker.name}]: ") or marker.name
                values = [prompt(f"{cue} [{marker.distances[index]:g} m]: ") or str(marker.distances[index])
                          for index, cue in enumerate(CUE_NAMES)]
                try:
                    candidate = CornerMarker(name, *(float(value) for value in values))
                    Profile(profile.circuit, tuple(markers + [candidate]), profile.vehicle)
                except ValueError as exc:
                    report(f"Invalid corner: {exc}. Review this corner again.")
                    continue
                markers.append(candidate)
                break
        confirmed = Profile(profile.circuit, tuple(markers), profile.vehicle)
        while True:
            name = prompt("Profile name (1–64 letters/digits/hyphens/underscores): ")
            try:
                path = draft_path(name, Path("profiles"))
                if path.exists() and not overwrite:
                    raise ValueError("Profile exists; choose another name or cancel and rerun with --overwrite.")
            except ValueError as exc:
                report(str(exc))
                continue
            break
        report(f"Final profile: {confirmed.circuit} / {confirmed.vehicle}")
        for marker in confirmed.markers:
            show(marker)
        report(f"Save to {path}" + (" (replacement permitted)" if overwrite else " (no overwrite)"))
        if prompt("These are your reviewed fixed references, not a safety guarantee. Type SAVE to confirm: ") != "SAVE":
            raise _Cancelled()
        text = confirmed.to_json()
    except (_Cancelled, EOFError, KeyboardInterrupt):
        report("Cancelled; no profile saved.")
        return None
    # Cancellation applies to review; do not misreport interrupted I/O as a
    # successful cancellation after the user has authorized the write.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as output:
        output.write(text)
    report(f"Saved profile: {path}. Start drive before your first marker.")
    return path
