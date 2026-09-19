"""Headless lifecycle coverage: no Windows, Tk display, or LMU required."""
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lmu_corner_cues import application
from lmu_corner_cues.gui import Controller, Window, launch
from lmu_corner_cues.__main__ import main


class GuiTests(unittest.TestCase):
    def services(self, **overrides):
        values = dict(probe=Mock(return_value="session"),
                      record=Mock(return_value=Path("recordings/lap.json")),
                      stopped_flow_guard=nullcontext)
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
        window = Window.__new__(Window)
        window.root = Mock()
        window.controller = Controller(self.services(), Mock())
        for name in ("phase", "status", "error", "session", "check", "start", "entry", "cancel_button"):
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

    def test_gui_command_and_platform_guard(self):
        with patch("lmu_corner_cues.gui.launch") as gui:
            self.assertEqual(main(["gui"]), 0)
            gui.assert_called_once_with()
        with patch("lmu_corner_cues.gui.sys.platform", "linux"), self.assertRaisesRegex(RuntimeError, "Windows"):
            launch()


if __name__ == "__main__":
    unittest.main()
