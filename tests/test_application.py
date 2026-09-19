"""Application services require neither Windows nor a running game."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lmu_corner_cues import application
from lmu_corner_cues.profile import CornerMarker, Profile


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile("Track", (CornerMarker("Turn", 10, 20, 30),), "Car")

    def test_load_profile_uses_domain_validation(self):
        with patch.object(Path, "read_text", return_value=self.profile.to_json()):
            self.assertEqual(application.load_profile("profile.json"), self.profile)
        with patch.object(Path, "read_text", return_value='{"status": "draft"}'), self.assertRaises(ValueError):
            application.load_profile("draft.json")

    def test_load_draft_reuses_stopped_review_validation(self):
        draft = {"status": "draft", "calibrated": False,
                 "lap_validity": "unverified; only observed telemetry continuity checked",
                 "observed": {"circuit": "Track", "vehicle": "Car", "vehicle_class": "GT3"},
                 "candidates": json.loads(self.profile.to_json())["markers"]}
        with patch.object(Path, "read_text", return_value=json.dumps(draft)):
            self.assertEqual(application.load_draft("draft.json"), (self.profile, "GT3"))

    def test_save_requires_explicit_confirmation_and_safe_name(self):
        for confirmed in (False, None, 1, "yes"):
            with patch.object(Path, "mkdir") as mkdir, self.assertRaises(ValueError):
                application.save_profile("test", self.profile, confirmed=confirmed)
            mkdir.assert_not_called()
        with self.assertRaises(ValueError):
            application.save_profile("../bad", self.profile, confirmed=True)

    def test_save_is_exclusive_unless_overwrite_explicit(self):
        for overwrite in (False, True):
            output = mock_open()
            with patch.object(Path, "mkdir"), patch.object(Path, "open", output):
                path = application.save_profile("test", self.profile, confirmed=True,
                                                overwrite=overwrite)
            self.assertEqual(path, Path("profiles/test.json"))
            output.assert_called_once_with("w" if overwrite else "x", encoding="utf-8")
            self.assertEqual(output().write.call_args.args[0], self.profile.to_json())
        with patch.object(Path, "mkdir"), patch.object(Path, "open", side_effect=FileExistsError), self.assertRaises(FileExistsError):
            application.save_profile("test", self.profile, confirmed=True)

    def test_discovery_excludes_drafts_and_invalid_files_and_sorts(self):
        paths = [Path(name) for name in ("z.json", "draft.json", "bad.json", "a.json")]
        texts = {paths[0]: self.profile.to_json(), paths[1]: '{"status":"draft"}',
                 paths[2]: 'broken', paths[3]: self.profile.to_json()}
        with patch.object(Path, "glob", return_value=paths), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **kw: texts[path]):
            self.assertEqual(application.discover_profiles(), [paths[3], paths[0]])
        with patch.object(Path, "glob", return_value=[]):
            self.assertEqual(application.discover_profiles(), [])

    def test_discovery_propagates_io_errors(self):
        with patch.object(Path, "glob", return_value=[Path("a.json")]), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", side_effect=PermissionError), self.assertRaises(PermissionError):
            application.discover_profiles()

    def test_edit_profile_uses_full_domain_validation(self):
        edited = application.edit_profile(self.profile, [["New turn", "12.5", "22", "32"]])
        self.assertEqual(edited.markers[0], CornerMarker("New turn", 12.5, 22, 32))
        self.assertEqual((edited.circuit, edited.vehicle), ("Track", "Car"))
        for rows in ([], [["", "10", "20", "30"]], [["Turn", "x", "20", "30"]],
                     [["Turn", "nan", "20", "30"]], [["Turn", "-1", "20", "30"]],
                     [["Turn", "20", "10", "30"]],
                     [["Turn", "10", "20", "30"], ["Turn", "40", "50", "60"]],
                     [["Turn", "10", "20", "30"], ["Other", "25", "50", "60"]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                application.edit_profile(self.profile, rows)

    def test_run_cues_reports_connection_and_closes_on_cancel_or_failure(self):
        for failure in ("cancel", "connect", "read", "audio", "mismatch"):
            with self.subTest(failure=failure):
                cancel = application.Event()
                reader, sink, report = Mock(), Mock(), Mock()
                reader.read.return_value = Mock(track="Track", vehicle="Car", vehicle_class="GT3",
                                                lap=1, distance=0)
                if failure == "cancel":
                    reader.read.side_effect = lambda cancel=cancel: cancel.set()
                elif failure == "connect":
                    reader.connect.side_effect = OSError("connection failed")
                elif failure == "read":
                    reader.read.side_effect = OSError("read failed")
                elif failure == "mismatch":
                    reader.read.return_value.track = "Other"
                else:
                    reader.read.side_effect = [
                        Mock(track="Track", vehicle="Car", vehicle_class="GT3", lap=1, distance=0),
                        Mock(track="Track", vehicle="Car", vehicle_class="GT3", lap=1, distance=11)]
                    sink.play.side_effect = RuntimeError("audio failed")
                with self.assertRaises((application.OperationCancelled, OSError, ValueError, RuntimeError)):
                    application.run_cues(self.profile, reader, sink, cancel=cancel, report=report)
                reader.close.assert_called_once_with()
                if failure == "connect":
                    report.assert_not_called()
                else:
                    report.assert_called_once_with("Active")
                if failure == "audio":
                    sink.play.assert_called_once()

    def test_probe_service_closes_on_failure(self):
        reader = Mock()
        reader.read.side_effect = OSError("lost telemetry")
        with self.assertRaises(OSError):
            application.probe(reader, report=Mock())
        reader.close.assert_called_once_with()
