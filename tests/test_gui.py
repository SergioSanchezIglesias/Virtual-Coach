"""Headless lifecycle coverage: no Windows, Tk display, or LMU required."""
import unittest
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from lmu_corner_cues import application
from lmu_corner_cues.__main__ import main
from lmu_corner_cues.gui import CALIBRATION_WARNING, Controller, Window, launch
from lmu_corner_cues.profile import CornerMarker, Profile


class GuiTests(unittest.TestCase):
    def services(self, **overrides):
        values = {"probe": Mock(return_value="session"),
                  "record": Mock(return_value=Path("recordings/lap.json")),
                  "stopped_flow_guard": nullcontext}
        values.update(overrides)
        return SimpleNamespace(**values)

    def finish(self, controller):
        assert controller.worker is not None
        controller.worker.join(2)
        self.assertFalse(controller.worker.is_alive())
        controller.drain()

    def test_idle_does_not_connect_and_probe_delivers_only_on_drain(self):
        services = self.services()
        controller = Controller(services, Mock())
        self.assertEqual(controller.state.phase, "Idle")
        services.probe.assert_not_called()
        controller.probe()
        assert controller.worker is not None
        controller.worker.join(2)
        self.assertIsNone(controller.state.session)
        self.assertTrue(controller.state.busy)
        controller.drain()
        self.assertEqual(controller.state.session, "session")
        self.assertFalse(controller.state.busy)

    def test_record_transitions_and_mutual_exclusion(self):
        started, release = Event(), Event()

        def record(*args, report, **kwargs):
            report("Recording one complete lap automatically.")
            started.set()
            release.wait(2)
            return Path("recordings/lap.json")

        controller = Controller(self.services(record=record), Mock())
        try:
            self.assertTrue(controller.record("lap"))
            self.assertEqual(controller.state.phase, "Waiting")
            self.assertTrue(started.wait(2))
            self.assertFalse(controller.probe())
            self.assertFalse(controller.record("other"))
            controller.drain()
            self.assertEqual(controller.state.phase, "Recording")
        finally:
            release.set()
            self.finish(controller)
        self.assertEqual(controller.state.phase, "Draft ready")
        self.assertIn("Unverified", controller.state.status)
        self.assertIsNotNone(controller.state.draft)

    def test_errors_propagate_and_retry_is_possible(self):
        for operation in ("probe", "record"):
            with self.subTest(operation=operation):
                services = self.services(**{operation: Mock(side_effect=ValueError("Missing local player"))})
                controller = Controller(services, Mock())
                getattr(controller, operation)(*(["lap"] if operation == "record" else []))
                self.finish(controller)
                self.assertEqual(controller.state.phase, "Error")
                self.assertIn("Missing local player", controller.state.error)
                self.assertIn("retry", controller.state.error)
                self.assertFalse(controller.state.busy)
                self.assertTrue(controller.probe())
                self.finish(controller)

    def test_thread_start_failure_delivers_error_and_allows_retry_or_close(self):
        for operation in ("probe", "record"):
            for closing in (False, True):
                with self.subTest(operation=operation, closing=closing):
                    services, reader = self.services(), Mock()
                    controller = Controller(services, reader)
                    with patch("lmu_corner_cues.gui.Thread.start",
                               side_effect=RuntimeError("can't start new thread")):
                        args = ["lap"] if operation == "record" else []
                        self.assertFalse(getattr(controller, operation)(*args))
                    reader.assert_not_called()
                    services.probe.assert_not_called()
                    services.record.assert_not_called()
                    self.assertIsNone(controller.worker)
                    self.assertEqual(controller.state.error, "")
                    self.assertTrue(controller.state.busy)
                    if closing:
                        controller.close()
                    controller.drain()
                    self.assertFalse(controller.state.busy)
                    self.assertEqual(controller.state.phase, "Error")
                    self.assertIn("Cannot start background worker", controller.state.error)
                    self.assertIn("can't start new thread", controller.state.error)
                    self.assertIn("Close unused applications and retry", controller.state.error)
                    if closing:
                        self.assertTrue(controller.ready_to_close)
                        self.assertFalse(controller.probe())
                    else:
                        self.assertTrue(getattr(controller, operation)(*args))
                        self.finish(controller)
                        self.assertEqual(controller.state.error, "")
                        self.assertEqual(controller.state.phase,
                                         "Idle" if operation == "probe" else "Draft ready")

    def test_cancel_and_close_wait_for_service_cleanup(self):
        for closing in (False, True):
            cleaned = Event()

            def record(*args, cancel, cleaned=cleaned, **kwargs):
                try:
                    cancel.wait(2)
                    raise application.OperationCancelled()
                finally:
                    cleaned.set()

            controller = Controller(self.services(record=record), Mock())
            controller.record("lap")
            if closing:
                controller.close()
                self.assertFalse(controller.ready_to_close)
                self.assertFalse(controller.probe())
            else:
                controller.cancel()
            self.finish(controller)
            self.assertTrue(cleaned.is_set())
            self.assertEqual(controller.state.phase, "Cancelled")
            self.assertEqual(controller.ready_to_close, closing)

    def test_close_during_probe_waits_for_return(self):
        release = Event()
        def probe(*args, **kwargs):
            release.wait(2)
            return "sample"
        controller = Controller(self.services(probe=probe), Mock())
        controller.probe()
        try:
            controller.close()
            self.assertFalse(controller.ready_to_close)
        finally:
            release.set()
            self.finish(controller)
        self.assertTrue(controller.ready_to_close)
        self.assertIsNone(controller.state.session)

    def test_window_poll_schedules_and_destroys_only_after_cleanup(self):
        window: Any = Window.__new__(Window)
        window.root = Mock()
        window.controller = Controller(self.services(), Mock())
        window.loaded_draft = None
        window.edit_widgets = []
        for name in ("phase", "status", "error", "session", "check", "start", "entry", "cancel_button",
                     "warning", "output_entry", "save_button", "selector", "refresh_button",
                     "cue_start", "cue_stop", "cue_status"):
            setattr(window, name, Mock())
        window.poll()
        window.root.after.assert_called_once_with(50, window.poll)
        window.controller.state.busy = True
        window.poll()
        window.start.configure.assert_called_with(state="disabled")
        window.entry.configure.assert_called_with(state="disabled")
        window.close()
        window.poll()
        window.root.destroy.assert_not_called()
        window.controller.state.busy = False
        window.root.after.reset_mock()
        window.poll()
        window.root.destroy.assert_called_once()
        window.root.after.assert_not_called()

    def reviewed_controller(self, **overrides):
        profile = Profile("Track", (CornerMarker("Turn", 10, 20, 30),), "Car")
        services = self.services(load_draft=Mock(return_value=(profile, "GT3")),
                                 edit_profile=application.edit_profile,
                                 save_profile=Mock(return_value=Path("profiles/lap.json")),
                                 discover_profiles=Mock(return_value=[Path("profiles/lap.json")]),
                                 **overrides)
        controller = Controller(services, Mock(), Mock())
        controller.state.draft = Path("recordings/lap.json")
        self.assertTrue(controller.review_draft())
        return controller

    def test_review_save_validation_and_confirmation(self):
        controller = self.reviewed_controller()
        confirm = Mock(return_value=True)
        rows = [["Turn", "10", "20", "30"]]
        self.assertFalse(controller.save("lap", [["Turn", "nan", "20", "30"]], confirm, confirm))
        confirm.assert_not_called()
        controller.services.save_profile.assert_not_called()
        self.assertIn("finite", controller.state.error)
        self.assertFalse(controller.save("lap", rows, Mock(return_value=False), confirm))
        controller.services.save_profile.assert_not_called()
        self.assertTrue(controller.save("lap", rows, confirm, confirm))
        self.assertIn(CALIBRATION_WARNING, confirm.call_args.args[0])
        controller.services.save_profile.assert_called_once_with(
            "lap", controller.state.review, confirmed=True)
        self.assertEqual(controller.state.profiles, (Path("profiles/lap.json"),))

    def test_overwrite_requires_separate_confirmation(self):
        for replace in (False, True):
            controller = self.reviewed_controller()
            controller.services.save_profile.side_effect = [FileExistsError(), Path("profiles/lap.json")]
            overwrite = Mock(return_value=replace)
            self.assertEqual(controller.save("lap", [["Turn", "10", "20", "30"]],
                                             Mock(return_value=True), overwrite), replace)
            overwrite.assert_called_once()
            self.assertEqual(controller.services.save_profile.call_count, 2 if replace else 1)
            if replace:
                self.assertTrue(controller.services.save_profile.call_args.kwargs["overwrite"])

    def test_save_rechecks_close_after_dialog(self):
        controller = self.reviewed_controller()
        def confirm(text):
            controller.close()
            return True
        self.assertFalse(controller.save("lap", [["Turn", "10", "20", "30"]], confirm, Mock()))
        controller.services.save_profile.assert_not_called()

    def test_recording_excludes_review_save_and_cues(self):
        controller = self.reviewed_controller()
        controller.refresh_profiles()
        controller.state.busy = True
        self.assertFalse(controller.review_draft())
        self.assertFalse(controller.save("lap", [], Mock(), Mock()))
        self.assertFalse(controller.start_cues(Path("profiles/lap.json")))
        self.assertFalse(controller.refresh_profiles())
        controller.services.save_profile.assert_not_called()

    def test_cue_lifecycle_cancellation_and_close_wait_for_cleanup(self):
        for closing in (False, True):
            started, cleaned = Event(), Event()
            def run_cues(*args, cancel, report, started=started, cleaned=cleaned):
                try:
                    report("Active")
                    started.set()
                    cancel.wait(2)
                    raise application.OperationCancelled()
                finally:
                    cleaned.set()
            controller = self.reviewed_controller(run_cues=run_cues, load_profile=Mock())
            controller.refresh_profiles()
            self.assertFalse(controller.start_cues(Path("recordings/lap.json")))
            self.assertTrue(controller.start_cues(Path("profiles/lap.json")))
            self.assertTrue(started.wait(2))
            self.assertEqual(controller.state.cue_status, "Starting")
            controller.drain()
            self.assertEqual(controller.state.cue_status, "Active")
            self.assertFalse(controller.record("other"))
            self.assertFalse(controller.review_draft())
            self.assertFalse(controller.save("lap", [], Mock(), Mock()))
            if closing:
                controller.close()
                self.assertFalse(controller.ready_to_close)
            else:
                controller.stop_cues()
            self.finish(controller)
            self.assertTrue(cleaned.is_set())
            self.assertEqual(controller.state.cue_status, "Stopped")
            self.assertEqual(controller.ready_to_close, closing)

    def test_cue_failures_and_thread_start_recovery(self):
        for failure in ("Profile mismatch", "Audio failed", "Missing local player"):
            controller = self.reviewed_controller(load_profile=Mock(),
                run_cues=Mock(side_effect=RuntimeError(failure)))
            controller.refresh_profiles()
            controller.start_cues(Path("profiles/lap.json"))
            self.finish(controller)
            self.assertEqual(controller.state.cue_status, "Error")
            self.assertIn(failure, controller.state.error)
            self.assertFalse(controller.state.busy)
        controller = self.reviewed_controller()
        controller.refresh_profiles()
        with patch("lmu_corner_cues.gui.Thread.start", side_effect=RuntimeError("no thread")):
            self.assertFalse(controller.start_cues(Path("profiles/lap.json")))
        controller.drain()
        self.assertEqual(controller.state.cue_status, "Error")
        controller.close()
        self.assertTrue(controller.ready_to_close)

    def test_window_save_passes_text_rows_and_separate_dialogs(self):
        window: Any = Window.__new__(Window)
        window.root = Mock()
        window.controller = self.reviewed_controller()
        window.output_name = Mock(get=Mock(return_value="chosen"))
        window.rows = [[Mock(get=Mock(return_value=value)) for value in ("Edited", "11", "22", "33")]]
        dialogs = SimpleNamespace(askyesno=Mock(return_value=True))
        with patch.dict("sys.modules", {"tkinter": SimpleNamespace(messagebox=dialogs)}):
            window.save()
        dialogs.askyesno.assert_called_once()
        self.assertIn(CALIBRATION_WARNING, dialogs.askyesno.call_args.args[1])
        saved = window.controller.services.save_profile.call_args
        self.assertEqual(saved.args[0], "chosen")
        self.assertEqual(saved.args[1].markers[0], CornerMarker("Edited", 11, 22, 33))

    def test_render_and_save_untouched_distances_is_lossless(self):
        cases = (
            (1.2345678901234567, 2.345678901234567, 3.456789012345678),
            (1000.0000000000001, 1000.0000000000002, 1000.0000000000003),
            (5e-324, 1e-323, 1.5e-323),
            (1e100, 1.0000000000000002e100, 1.0000000000000004e100),
            (2**53, 2**53 + 1, 2**53 + 2),
        )
        for distances in cases:
            with self.subTest(distances=distances):
                window: Any = Window.__new__(Window)
                window.root = Mock()
                window.table = Mock(winfo_children=Mock(return_value=[]))
                window.controller = self.reviewed_controller()
                original = Profile("Track", (CornerMarker("Turn", *distances),), "Car")
                window.controller.state.review = original
                window.output_name = Mock(get=Mock(return_value="lap"))
                dialogs = SimpleNamespace(askyesno=Mock(return_value=True))
                tk = SimpleNamespace(
                    StringVar=lambda value: Mock(get=Mock(return_value=value)),
                    ttk=SimpleNamespace(Label=Mock(), Entry=Mock()), messagebox=dialogs)
                with patch.dict("sys.modules", {"tkinter": tk}):
                    window.render_review()
                    rendered = [value.get() for value in window.rows[0]]
                    self.assertEqual(rendered, ["Turn", *(str(value) for value in distances)])
                    window.save()
                self.assertEqual(window.controller.state.error, "")
                saved = window.controller.services.save_profile.call_args.args[1]
                self.assertEqual(saved, original)
                self.assertEqual(saved.to_json(), original.to_json())
                dialogs.askyesno.assert_called_once()

    def test_gui_command_and_platform_guard(self):
        with patch("lmu_corner_cues.gui.launch") as gui:
            self.assertEqual(main(["gui"]), 0)
            gui.assert_called_once_with()
        with patch("lmu_corner_cues.gui.sys.platform", "linux"), self.assertRaisesRegex(RuntimeError, "Windows"):
            launch()


if __name__ == "__main__":
    unittest.main()
