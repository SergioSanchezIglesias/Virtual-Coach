"""Non-interactive services shared by CLI and future worker-thread clients.

Operations run synchronously on the caller's thread. Callers own scheduling and
mutual exclusion (stopped_flow_guard is available for record/review flows).
Create a fresh threading.Event per record/run operation and set it to stop;
OperationCancelled signals cancellation after reader cleanup. Reporting callbacks
run on that same thread: GUI clients must enqueue messages, not touch widgets.
"""

from pathlib import Path
from threading import Event

from .profile import Profile
from .recording import draft_path, record
from .runtime import OperationCancelled, run
from .session import probe
from .wizard import _draft_profile, stopped_flow_guard

# Domain orchestration is exported directly, preserving existing call contracts.
__all__ = ["Event", "OperationCancelled", "probe", "record", "run",
           "load_draft", "load_profile", "save_profile", "discover_profiles",
           "stopped_flow_guard"]


def load_draft(path):
    """Return validated candidate Profile and observed class, still unverified."""
    return _draft_profile(path)


def load_profile(path):
    return Profile.from_json(Path(path).read_text(encoding="utf-8"))


def save_profile(name, profile, *, confirmed: object = False, overwrite=False,
                 directory=Path("profiles")):
    """Persist reviewed references only after explicit caller confirmation.

    The caller must keep driving/recording stopped throughout review and save.
    Exclusive creation prevents silently replacing a concurrently created file.
    """
    if not isinstance(confirmed, bool) or not confirmed:
        raise ValueError("Explicit confirmation of reviewed fixed references is required.")
    path = draft_path(name, directory)
    text = profile.to_json()
    # Use the same domain validation as profile loading, before any filesystem I/O.
    Profile.from_json(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as output:
        output.write(text)
    return path


def discover_profiles(directory=Path("profiles")):
    """Return sorted valid driving-profile paths; exclude drafts/invalid JSON.

    Missing directories yield no profiles. Filesystem errors propagate so a UI
    can distinguish inaccessible files from an empty collection.
    """
    paths = []
    for path in sorted(Path(directory).glob("*.json")):
        if not path.is_file():
            continue
        try:
            load_profile(path)
        except ValueError:
            continue
        paths.append(path)
    return paths
