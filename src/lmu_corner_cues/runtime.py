"""Injectable polling orchestration, independent of native LMU bindings."""

import math
import time
from contextlib import contextmanager, suppress

from .engine import CueEngine


@contextmanager
def _closing_reader(reader):
    try:
        yield reader
    except BaseException:
        # Cleanup must not replace a runtime failure or an interrupt.
        with suppress(BaseException):
            reader.close()
        raise
    else:
        reader.close()


class OperationCancelled(RuntimeError):
    """Cooperative stop requested; distinct from telemetry or validation failure."""


def check_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise OperationCancelled("Operation cancelled.")


def wait_interval(interval, sleep, cancel):
    if cancel is None:
        sleep(interval)
    else:
        # Event.wait wakes immediately on stop, even with long poll intervals.
        cancel.wait(interval)
        check_cancelled(cancel)


def run(profile, reader, sink, interval=0.02, *, sleep=time.sleep, cancel=None):
    """Run on the caller's thread; an optional threading.Event requests stop.

    Cancellation raises OperationCancelled and closes the reader. Native reads
    and a single sink.play call must finish before cancellation can be observed.
    """
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Polling interval must be a finite positive number of seconds.")
    engine = CueEngine(profile)
    with _closing_reader(reader):
        check_cancelled(cancel)
        reader.connect()
        while True:
            check_cancelled(cancel)
            sample = reader.read()
            check_cancelled(cancel)
            if profile.circuit != sample.track:
                raise ValueError(
                    f"Profile circuit {profile.circuit!r} does not match LMU track {sample.track!r}; select a matching profile."
                )
            if profile.vehicle is not None and profile.vehicle not in (sample.vehicle, sample.vehicle_class):
                raise ValueError(
                    f"Profile vehicle {profile.vehicle!r} does not match LMU vehicle {sample.vehicle!r} "
                    f"or class {sample.vehicle_class!r}; select a matching profile."
                )
            for cue in engine.update(sample.lap, sample.distance):
                check_cancelled(cancel)
                sink.play(cue)
            wait_interval(interval, sleep, cancel)
