"""Probe and recording contracts with no game, audio, or filesystem writes."""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lmu_corner_cues.__main__ import main
from lmu_corner_cues.lmu import Snapshot
from lmu_corner_cues.recording import draft_path, record
from lmu_corner_cues.session import probe


def sample(lap, distance, brake: float = 0.0, throttle: float = 0.0, track="Track"):
    return Snapshot(track, "Car", "GT3", lap, distance, throttle, brake)


class RecordingTests(unittest.TestCase):
    def capture(self, samples, **kwargs):
        reader = Mock()
        reader.read.side_effect = samples
        output = mock_open()
        report = Mock()
        with patch.object(Path, "exists", return_value=False), patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open", output):
            result = record("test", reader, sleep=Mock(), clock=Mock(side_effect=[0, 10, 70]), report=report, **kwargs)
        reader.close.assert_called_once_with()
        return result, json.loads(output.return_value.write.call_args.args[0]), output, report, mkdir

    def test_probe_reads_once_reports_and_closes(self):
        reader = Mock()
        reader.read.return_value = sample(4, 123)
        report = Mock()
        self.assertEqual(probe(reader, report=report), reader.read.return_value)
        reader.connect.assert_called_once_with()
        reader.read.assert_called_once_with()
        reader.close.assert_called_once_with()
        for value in ("Track", "Car", "GT3", "4", "123.00"):
            self.assertIn(value, report.call_args.args[0])

    def test_complete_lap_only_and_ordered_candidates(self):
        result, draft, output, report, mkdir = self.capture([
            sample(3, 400, .8), sample(3, 500), sample(3, 600, throttle=.8),
            sample(4, 2), sample(4, 100, .3), sample(4, 110, .1),
            sample(4, 120, .04), sample(4, 130, throttle=.3),
            sample(4, 200, .7), sample(4, 220), sample(4, 230, throttle=.8),
            sample(4, 300, .8), sample(4, 320), sample(5, 1),
        ])
        self.assertEqual(result, Path("recordings/test.json"))
        self.assertEqual(draft["lap"], 4)
        self.assertEqual(draft["duration_seconds"], 60)
        self.assertEqual(draft["status"], "draft")
        self.assertFalse(draft["calibrated"])
        self.assertEqual(draft["observed"], {"circuit": "Track", "vehicle": "Car", "vehicle_class": "GT3"})
        self.assertEqual([(c["BRAKE"], c["RELEASE_BRAKE"], c["THROTTLE"]) for c in draft["candidates"]], [(100, 120, 130), (200, 220, 230)])
        output.assert_called_once_with("x", encoding="utf-8")
        self.assertIn("Circuit: Track", report.call_args_list[0].args[0])
        mkdir.assert_called_once()

    def test_incomplete_or_same_distance_sequences_are_ignored(self):
        _, draft, *_ = self.capture([sample(1, 500), sample(2, 0), sample(2, 10, .3), sample(2, 10), sample(2, 20, throttle=.4), sample(2, 100, .3), sample(3, 0)])
        self.assertEqual(draft["candidates"], [])

    def test_failures_never_write_and_always_close(self):
        for failure in (sample(2, 10, track="Other"), sample(4, 0), sample(1, 0), sample(2, 1), KeyboardInterrupt(), OSError("lost telemetry")):
            with self.subTest(failure=failure):
                reader = Mock()
                reader.read.side_effect = [sample(1, 500), sample(2, 5), failure]
                with patch.object(Path, "exists", return_value=False), patch.object(Path, "open") as output, patch.object(Path, "mkdir") as mkdir:
                    with self.assertRaises((ValueError, KeyboardInterrupt, OSError)):
                        record("test", reader, sleep=Mock(), report=Mock())
                output.assert_not_called()
                mkdir.assert_not_called()
                reader.close.assert_called_once_with()

    def test_safe_names_and_existing_drafts_fail_before_connection(self):
        for name in ("../evil", "a/b", "CON", "nul", "LPT1", "", "a.b", "a" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                draft_path(name)
        reader = Mock()
        with patch.object(Path, "exists", return_value=True), self.assertRaisesRegex(ValueError, "overwrite"):
            record("existing", reader)
        reader.connect.assert_not_called()

    def test_explicit_overwrite_and_injected_directory(self):
        _, _, output, *_ = self.capture([sample(1, 500), sample(2, 0), sample(2, 500), sample(3, 0)], overwrite=True, directory=Path("custom"))
        output.assert_called_once_with("w", encoding="utf-8")

    def test_new_commands_never_construct_audio(self):
        with patch("lmu_corner_cues.__main__.BeepSink") as audio, patch("lmu_corner_cues.__main__.LMUReader") as reader, patch("lmu_corner_cues.__main__.probe") as inspect, patch("lmu_corner_cues.__main__.record") as recorder:
            self.assertEqual(main(["session"]), 0)
            inspect.assert_called_once_with(reader.return_value)
            self.assertEqual(main(["record", "lap", "--overwrite", "--interval", "0.1"]), 0)
            recorder.assert_called_once_with("lap", reader.return_value, .1, overwrite=True)
            audio.assert_not_called()

    def test_invalid_intervals_do_not_connect(self):
        for interval in (0, -1, float("nan"), float("inf")):
            reader = Mock()
            with self.assertRaisesRegex(ValueError, "interval"):
                record("test", reader, interval)
            reader.connect.assert_not_called()

    def test_connection_failure_and_probe_failure_close(self):
        for operation in (probe, lambda reader: record("test", reader)):
            reader = Mock()
            reader.connect.side_effect = OSError("connection failed")
            with patch.object(Path, "exists", return_value=False), self.assertRaisesRegex(OSError, "connection failed"):
                operation(reader)
            reader.close.assert_called_once_with()

    def test_draft_created_during_lap_is_not_overwritten(self):
        reader = Mock()
        reader.read.side_effect = [sample(1, 500), sample(2, 0), sample(2, 500), sample(3, 0)]
        with patch.object(Path, "exists", return_value=False), patch.object(Path, "mkdir"), patch.object(Path, "open", side_effect=FileExistsError("draft appeared")) as output, self.assertRaises(FileExistsError):
            record("test", reader, sleep=Mock(), report=Mock())
        output.assert_called_once_with("x", encoding="utf-8")
        reader.close.assert_called_once_with()

    def test_command_help(self):
        for command in ("session", "record", "drive"):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main([command, "--help"])
            self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
