"""Short, distinct Windows beep patterns; no game inputs are sent."""

import sys

PATTERNS = {
    "BRAKE": ((440, 120),),
    "RELEASE_BRAKE": ((880, 60), (660, 60)),
    "THROTTLE": ((1320, 120),),
}


class BeepSink:
    def __init__(self, beep=None):
        self._beep = beep

    def play(self, cue):
        if self._beep is None:
            if sys.platform != "win32":
                raise RuntimeError("Audio playback requires Windows; run this CLI on your Windows LMU PC.")
            import winsound

            self._beep = winsound.Beep
        for frequency, duration in PATTERNS[cue.kind]:
            self._beep(frequency, duration)
