"""Stopped profile creation without live telemetry or filesystem writes."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lmu_corner_cues.__main__ import main
from lmu_corner_cues.profile import Profile
from lmu_corner_cues.wizard import create_profile, stopped_flow_guard


def draft():
    return {"status": "draft", "calibrated": False,
            "lap_validity": "unverified; only observed telemetry continuity checked",
            "observed": {"circuit": "Track", "vehicle": "Car", "vehicle_class": "GT3"},
            "candidates": [{"name": "Corner 1", "BRAKE": 100, "RELEASE_BRAKE": 120, "THROTTLE": 150},
                           {"name": "Corner 2", "BRAKE": 200, "RELEASE_BRAKE": 220, "THROTTLE": 250}]}


class WizardTests(unittest.TestCase):
    def run_wizard(self, answers, *, data=None, exists=False, overwrite=False):
        output, report = mock_open(), Mock()
        with patch.object(Path, "read_text", return_value=json.dumps(draft() if data is None else data)), patch.object(Path, "exists", return_value=exists), patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open", output):
            result = create_profile("recordings/lap.json", ask=Mock(side_effect=answers), report=report, overwrite=overwrite)
        return result, output, report, mkdir

    def test_accept_all_and_round_trip_driving_profile(self):
        result, output, report, _ = self.run_wizard(["STOPPED"] + [""] * 8 + ["my-car", "SAVE"])
        self.assertEqual(result, Path("profiles/my-car.json"))
        output.assert_called_once_with("x", encoding="utf-8")
        profile = Profile.from_json(output.return_value.write.call_args.args[0])
        self.assertEqual((profile.circuit, profile.vehicle), ("Track", "Car"))
        self.assertEqual(len(profile.markers), 2)
        shown = "\n".join(call.args[0] for call in report.call_args_list)
        for text in ("Track", "Car", "GT3", "100 m", "250 m", "UNVERIFIED"):
            self.assertIn(text, shown)
        with patch.object(Path, "read_text", return_value=profile.to_json()), patch("lmu_corner_cues.__main__.run") as run, patch("lmu_corner_cues.__main__.LMUReader"), patch("lmu_corner_cues.__main__.BeepSink"):
            self.assertEqual(main(["drive", str(result)]), 0)
        self.assertEqual(run.call_args.args[0], profile)

    def test_edit_retry_invalid_order_nonfinite_and_duplicate(self):
        answers = ["STOPPED", "Turn", "nan", "120", "150", "Turn", "130", "120", "150",
                   "Turn", "90", "110", "140", "Turn", "", "", "",
                   "Second", "210", "230", "260", "revised", "SAVE"]
        _, output, report, _ = self.run_wizard(answers)
        profile = Profile.from_json(output.return_value.write.call_args.args[0])
        self.assertEqual(profile.markers[0].distances, (90, 110, 140))
        self.assertEqual(profile.markers[1].name, "Second")
        self.assertEqual(sum("Invalid corner" in call.args[0] for call in report.call_args_list), 3)

    def test_cancellation_at_every_stage_never_creates_output(self):
        for answers in (["no"], ["STOPPED", "cancel"], ["STOPPED", EOFError()],
                        ["STOPPED", KeyboardInterrupt()], ["STOPPED"] + [""] * 8 + ["cancel"],
                        ["STOPPED"] + [""] * 8 + ["name", "yes"]):
            with self.subTest(answers=answers):
                result, output, _, mkdir = self.run_wizard(answers)
                self.assertIsNone(result)
                output.assert_not_called()
                mkdir.assert_not_called()

    def test_rejects_non_drafts_bad_identity_and_empty_candidates_before_prompt(self):
        variants = [{}, {**draft(), "calibrated": True}, {**draft(), "calibrated": 0},
                    {**draft(), "status": "confirmed"}, {**draft(), "lap_validity": "verified"},
                    {**draft(), "observed": {}}, {**draft(), "candidates": []}]
        for data in variants:
            with self.subTest(data=data), patch.object(Path, "read_text", return_value=json.dumps(data)), patch.object(Path, "open") as output:
                ask = Mock()
                with self.assertRaises(ValueError):
                    create_profile("draft.json", ask=ask)
                ask.assert_not_called()
                output.assert_not_called()

    def test_safe_name_overwrite_and_existing_profile_cancellation(self):
        _, output, _, _ = self.run_wizard(["STOPPED"] + [""] * 8 + ["../escape", "CON", "safe", "SAVE"])
        output.assert_called_once_with("x", encoding="utf-8")
        _, output, _, _ = self.run_wizard(["STOPPED"] + [""] * 8 + ["safe", "cancel"], exists=True)
        output.assert_not_called()
        _, output, _, _ = self.run_wizard(["STOPPED"] + [""] * 8 + ["safe", "SAVE"], exists=True, overwrite=True)
        output.assert_called_once_with("w", encoding="utf-8")

    def test_exclusive_creation_race_does_not_overwrite(self):
        with patch.object(Path, "read_text", return_value=json.dumps(draft())), patch.object(Path, "exists", return_value=False), patch.object(Path, "mkdir"), patch.object(Path, "open", side_effect=FileExistsError) as output, self.assertRaises(FileExistsError):
            create_profile("draft", ask=Mock(side_effect=["STOPPED"] + [""] * 8 + ["safe", "SAVE"]), report=Mock())
        output.assert_called_once_with("x", encoding="utf-8")

    def test_drafts_rejected_by_drive_before_telemetry_or_audio(self):
        with patch.object(Path, "read_text", return_value=json.dumps(draft())), patch("lmu_corner_cues.__main__.LMUReader") as reader, patch("lmu_corner_cues.__main__.BeepSink") as audio, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["drive", "recordings/lap.json"]), 1)
        reader.assert_not_called()
        audio.assert_not_called()

    def test_guard_blocks_both_commands_before_io(self):
        with patch("lmu_corner_cues.wizard.socket.socket") as socket_factory:
            socket_factory.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with patch("lmu_corner_cues.__main__.record") as record, patch("lmu_corner_cues.__main__.create_profile") as create, patch("lmu_corner_cues.__main__.LMUReader") as reader, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["record", "lap"]), 1)
                self.assertEqual(main(["profile", "create", "recordings/lap.json"]), 1)
            record.assert_not_called()
            create.assert_not_called()
            reader.assert_not_called()

    def test_os_guard_excludes_second_owner_and_allows_reentry_after_exit(self):
        with stopped_flow_guard(), self.assertRaisesRegex(RuntimeError, "already active"), stopped_flow_guard():
            self.fail("A second owner acquired the guard")
        with stopped_flow_guard():
            pass

    def test_guard_released_on_interrupt(self):
        with patch("lmu_corner_cues.wizard.socket.socket") as factory:
            with self.assertRaises(KeyboardInterrupt), stopped_flow_guard():
                raise KeyboardInterrupt()
            factory.return_value.__exit__.assert_called_once()

    def test_create_cli_is_separate_from_recording_and_audio(self):
        with patch("lmu_corner_cues.__main__.stopped_flow_guard"), patch("lmu_corner_cues.__main__.create_profile") as create, patch("lmu_corner_cues.__main__.record") as record, patch("lmu_corner_cues.__main__.LMUReader") as reader, patch("lmu_corner_cues.__main__.BeepSink") as audio:
            self.assertEqual(main(["profile", "create", "recordings/lap.json", "--overwrite"]), 0)
            create.assert_called_once_with(Path("recordings/lap.json"), overwrite=True)
            record.assert_not_called()
            reader.assert_not_called()
            audio.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exited:
            main(["profile", "create", "--help"])
        self.assertEqual(exited.exception.code, 0)
        self.assertIn("--overwrite", output.getvalue())
        self.assertIn("stop driving", output.getvalue())


if __name__ == "__main__":
    unittest.main()
