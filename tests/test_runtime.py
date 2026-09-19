"""Runtime contracts exercised without LMU or Windows."""

import contextlib
import io
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_native_layout import RawMap

from lmu_corner_cues.__main__ import main
from lmu_corner_cues.audio import PATTERNS, BeepSink
from lmu_corner_cues.engine import Cue
from lmu_corner_cues.lmu import LMUReader, Snapshot, TelemetryError
from lmu_corner_cues.profile import CornerMarker, Profile
from lmu_corner_cues.runtime import OperationCancelled, _closing_reader, run


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile("Track", (CornerMarker("Turn", 10, 20, 30),), "GT3")
        self.sample = Snapshot("Track", "Car", "GT3", 2, 35)

    def native(self, index=0, player=True, track=b"Track"):
        return RawMap(index=index, player=player, track=track)

    def test_pre_cancelled_runtime_closes_without_connecting(self):
        cancel = Event()
        cancel.set()
        reader, sink = Mock(), Mock()
        with self.assertRaises(OperationCancelled):
            run(self.profile, reader, sink, cancel=cancel)
        reader.connect.assert_not_called()
        sink.play.assert_not_called()
        reader.close.assert_called_once_with()

    def test_cancel_after_first_cue_prevents_remaining_audio(self):
        cancel = Event()
        reader, sink = Mock(), Mock()
        reader.read.return_value = self.sample
        sink.play.side_effect = lambda cue: cancel.set()
        with self.assertRaises(OperationCancelled):
            run(self.profile, reader, sink, cancel=cancel)
        self.assertEqual(sink.play.call_count, 1)
        reader.close.assert_called_once_with()

    def test_cancellable_wait_replaces_uninterruptible_sleep(self):
        cancel = Mock()
        cancel.is_set.side_effect = [False, False, False, False, False, False, True]
        reader, sink, sleep = Mock(), Mock(), Mock()
        reader.read.return_value = self.sample
        with self.assertRaises(OperationCancelled):
            run(self.profile, reader, sink, interval=60, sleep=sleep, cancel=cancel)
        cancel.wait.assert_called_once_with(60)
        sleep.assert_not_called()
        reader.close.assert_called_once_with()

    def test_snapshot_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.sample.lap = 3  # pyright: ignore[reportAttributeAccessIssue]

    def test_adapter_lifecycle_and_snapshot(self):
        info = self.native()
        factory = Mock(return_value=info)
        reader = LMUReader(factory)
        factory.assert_not_called()
        reader.connect()
        reader.connect()
        factory.assert_called_once_with()
        self.assertEqual(reader.read(), self.sample)
        reader.close()
        reader.close()
        info.close.assert_called_once_with()

    def test_unsupported_platform_and_missing_map(self):
        with patch("lmu_corner_cues.lmu.sys.platform", "darwin"), self.assertRaisesRegex(TelemetryError, "Windows"):
            LMUReader().connect()
        with self.assertRaisesRegex(TelemetryError, "LMU_Data"):
            LMUReader(Mock(side_effect=OSError("missing map"))).connect()

    def test_no_player_or_missing_identity(self):
        for info in (self.native(index=104), self.native(index=255), self.native(player=False), self.native(track=b"")):
            with self.subTest(info=info):
                reader = LMUReader(lambda info=info: info)
                reader.connect()
                with self.assertRaisesRegex(TelemetryError, "driving session"):
                    reader.read()
                reader.close()
        info = self.native()
        info[128468 + 32:128468 + 96] = bytes(64)
        reader = LMUReader(lambda: info)
        reader.connect()
        with self.assertRaises(TelemetryError):
            reader.read()
        reader.close()

    def test_polling_emits_once_and_closes_on_interrupt(self):
        reader, sink = Mock(), Mock()
        reader.read.side_effect = [self.sample, self.sample, Snapshot("Track", "Car", "GT3", 3, 35), KeyboardInterrupt()]
        sleep = Mock()
        with self.assertRaises(KeyboardInterrupt):
            run(self.profile, reader, sink, sleep=sleep)
        self.assertEqual([call.args[0].kind for call in sink.play.call_args_list], list(PATTERNS) * 2)
        self.assertEqual(sleep.call_count, 3)
        reader.close.assert_called_once_with()

    def test_mismatch_prevents_audio_and_closes(self):
        for sample in (Snapshot("Other", "Car", "GT3", 2, 35), Snapshot("Track", "Other", "Other", 2, 35)):
            reader, sink = Mock(), Mock()
            reader.read.return_value = sample
            with self.assertRaisesRegex(ValueError, "select a matching profile"):
                run(self.profile, reader, sink)
            sink.play.assert_not_called()
            reader.close.assert_called_once_with()

    def test_vehicle_name_and_unspecified_vehicle(self):
        for vehicle in ("Car", None):
            reader, sink = Mock(), Mock()
            reader.read.side_effect = [self.sample, KeyboardInterrupt()]
            with self.assertRaises(KeyboardInterrupt):
                run(Profile("Track", self.profile.markers, vehicle), reader, sink, sleep=Mock())
            self.assertEqual(sink.play.call_count, 3)

    def test_invalid_interval_before_connect(self):
        for interval in (0, -1, float("nan"), float("inf")):
            reader = Mock()
            with self.assertRaisesRegex(ValueError, "interval"):
                run(self.profile, reader, Mock(), interval)
            reader.connect.assert_not_called()

    def test_connection_failure_closes(self):
        reader = Mock()
        reader.connect.side_effect = TelemetryError("connection failed")
        with self.assertRaises(TelemetryError):
            run(self.profile, reader, Mock())
        reader.close.assert_called_once_with()

    def test_close_failure_preserves_original_runtime_error(self):
        for stage in ("connect", "read", "play", "sleep"):
            for original in (TelemetryError("runtime failed"), KeyboardInterrupt()):
                with self.subTest(stage=stage, error=type(original).__name__):
                    reader, sink, sleep = Mock(), Mock(), Mock()
                    reader.read.return_value = self.sample
                    target = {"connect": reader.connect, "read": reader.read,
                              "play": sink.play, "sleep": sleep}[stage]
                    target.side_effect = original
                    reader.close.side_effect = OSError("close failed")
                    with self.assertRaises(type(original)) as raised:
                        run(self.profile, reader, sink, sleep=sleep)
                    self.assertIs(raised.exception, original)
                    reader.close.assert_called_once_with()

    def test_close_failure_propagates_without_original_error(self):
        reader = Mock()
        failure = OSError("close failed")
        reader.close.side_effect = failure
        with self.assertRaises(OSError) as raised, _closing_reader(reader):
            pass
        self.assertIs(raised.exception, failure)
        reader.close.assert_called_once_with()

    def test_audio_patterns_and_non_windows(self):
        self.assertEqual(len(set(PATTERNS.values())), 3)
        for kind, pattern in PATTERNS.items():
            beep = Mock()
            BeepSink(beep).play(Cue(1, "Turn", kind, 10))
            self.assertEqual([call.args for call in beep.call_args_list], list(pattern))
        with patch("lmu_corner_cues.audio.sys.platform", "darwin"), self.assertRaisesRegex(RuntimeError, "requires Windows"):
            BeepSink().play(Cue(1, "Turn", "BRAKE", 10))

    def test_cli_help_without_native_dependency(self):
        with patch.dict(sys.modules, {"pyLMUSharedMemory": None}), contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exit_info:
            main(["--help"])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn("--interval", output.getvalue())

    def test_explicit_drive_command_preserves_runtime(self):
        with patch("pathlib.Path.read_text", return_value=self.profile.to_json()), patch("lmu_corner_cues.__main__.run") as runner, patch("lmu_corner_cues.__main__.LMUReader") as reader, patch("lmu_corner_cues.__main__.BeepSink") as audio:
            self.assertEqual(main(["drive", "profile.json", "--interval", "0.1"]), 0)
        runner.assert_called_once_with(self.profile, reader.return_value, audio.return_value, .1)

    def test_cli_reports_errors_and_handles_interrupt(self):
        for error in (TelemetryError("Cannot open LMU_Data"), KeyboardInterrupt()):
            with patch("pathlib.Path.read_text", return_value=self.profile.to_json()), patch("lmu_corner_cues.__main__.run", side_effect=error), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(["profile.json"]), 0 if isinstance(error, KeyboardInterrupt) else 1)
            if isinstance(error, TelemetryError):
                self.assertIn("Cannot open LMU_Data", output.getvalue())


if __name__ == "__main__":
    unittest.main()
