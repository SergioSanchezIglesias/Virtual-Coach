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


def run(profile, reader, sink, interval=0.02, *, sleep=time.sleep):
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Polling interval must be a finite positive number of seconds.")
    engine = CueEngine(profile)
    with _closing_reader(reader):
        reader.connect()
        while True:
            sample = reader.read()
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
                sink.play(cue)
            sleep(interval)
