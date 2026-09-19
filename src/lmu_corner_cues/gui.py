"""Windows Tk view and display-independent worker/controller boundary."""

from dataclasses import dataclass
from queue import Empty, Queue
import sys
from threading import Event, Thread
from typing import Any

from . import application
from .lmu import LMUReader


@dataclass
class ViewState:
    phase: str = "Idle"
    status: str = "Not checked. LMU is not required to open this window."
    session: Any = None
    draft: object = None  # T3 owns stopped review and explicit confirmation.
    error: str = ""
    busy: bool = False
    closing: bool = False


class Controller:
    """Only drain() changes state from worker results; workers never call Tk.

    Close is cooperative: keep polling until the service has returned and closed
    its reader. Never close a reader concurrently with an in-flight native read.
    """

    def __init__(self, services: Any = application, reader_factory: Any = LMUReader):
        self.services = services
        self.reader_factory = reader_factory
        self.state = ViewState()
        self.messages = Queue()
        self.worker = None
        self.cancel_event = Event()

    def _start(self, operation, name=None):
        if self.state.busy or self.state.closing:
            return False
        self.state.busy = True
        self.state.error = ""
        self.state.phase = "Waiting" if operation == "record" else "Idle"
        self.state.status = "Waiting for next lap" if operation == "record" else "Checking connection…"
        if operation == "probe":
            self.state.session = None
        else:
            self.state.draft = None
        self.cancel_event = Event()

        def report(text):
            self.messages.put(("progress", text))

        def work():
            try:
                if operation == "probe":
                    result = self.services.probe(self.reader_factory(), report=report)
                    if self.cancel_event.is_set():
                        raise application.OperationCancelled()
                else:
                    with self.services.stopped_flow_guard():
                        result = self.services.record(name, self.reader_factory(),
                                                      report=report, cancel=self.cancel_event)
                self.messages.put((operation, result))
            except application.OperationCancelled:
                self.messages.put(("cancelled", None))
            except Exception as exc:
                self.messages.put(("error", str(exc)))
            finally:
                self.messages.put(("done", None))

        self.worker = Thread(target=work, name="lmu-gui-worker")
        try:
            self.worker.start()
        except Exception as exc:
            self.worker = None
            self.messages.put(("error", f"Cannot start background worker: {exc}. "
                               "Close unused applications and retry; restart this application if needed."))
            self.messages.put(("done", None))
            return False
        return True

    def probe(self):
        return self._start("probe")

    def record(self, name):
        return self._start("record", name)

    def cancel(self):
        if self.state.busy:
            self.cancel_event.set()
            self.state.status = "Cancellation requested; waiting for reader cleanup…"

    def close(self):
        self.state.closing = True
        self.cancel()

    @property
    def ready_to_close(self):
        return self.state.closing and not self.state.busy and (
            self.worker is None or not self.worker.is_alive())

    def drain(self):
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except Empty:
                break
            if kind == "progress":
                self.state.status = value
                if value.startswith("Recording one complete lap"):
                    self.state.phase = "Recording"
            elif kind == "probe":
                self.state.session = value
                self.state.status = "Connected"
                self.state.phase = "Idle"
            elif kind == "record":
                self.state.draft = value
                self.state.phase = "Draft ready"
                self.state.status = (f"Draft: {value}. Unverified: only telemetry continuity checked. "
                                     "Candidates are not safe or calibrated driving points. Review while stopped.")
            elif kind == "cancelled":
                self.state.phase = "Cancelled"
                self.state.status = "Operation cancelled."
            elif kind == "error":
                self.state.phase = "Error"
                self.state.error = value + " Check LMU/session availability and the recording name/output path, then retry. Existing drafts are not replaced; choose a new name."
                self.state.status = "Operation failed."
            elif kind == "done":
                self.state.busy = False
        return self.state


class Window:
    def __init__(self, root, controller=None):
        from tkinter import StringVar, ttk

        self.root = root
        self.controller = controller or Controller()
        root.title("LMU Corner Cues")
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=12)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.status = StringVar()
        self.session = StringVar(value="Circuit: — | Vehicle: — | Class: — | Lap: — | Distance: —")
        self.phase = StringVar()
        self.error = StringVar()
        self.name = StringVar(value="lap")
        ttk.Label(frame, text="LMU status").grid(sticky="w")
        self.check = ttk.Button(frame, text="Check connection", command=self.controller.probe)
        self.check.grid(sticky="w")
        ttk.Label(frame, textvariable=self.session, wraplength=520).grid(sticky="w", pady=6)
        ttk.Separator(frame).grid(sticky="ew", pady=6)
        ttk.Label(frame, text="Record a lap — start before driving").grid(sticky="w")
        ttk.Label(frame, text="Profile name").grid(sticky="w")
        self.entry = ttk.Entry(frame, textvariable=self.name)
        self.entry.grid(sticky="ew")
        self.start = ttk.Button(frame, text="Start recording", command=lambda: self.controller.record(self.name.get()))
        self.start.grid(sticky="w", pady=4)
        self.cancel_button = ttk.Button(frame, text="Cancel", command=self.controller.cancel)
        self.cancel_button.grid(sticky="w")
        for variable in (self.phase, self.status, self.error):
            ttk.Label(frame, textvariable=variable, wraplength=520).grid(sticky="w", pady=4)
        self.poll_id = None
        self.poll()

    def close(self):
        self.controller.close()

    def poll(self):
        self.poll_id = None
        state = self.controller.drain()
        if self.controller.ready_to_close:
            self.root.destroy()
            return
        self.phase.set(state.phase)
        self.status.set(state.status)
        self.error.set(state.error)
        sample = state.session
        self.session.set("Circuit: — | Vehicle: — | Class: — | Lap: — | Distance: —" if sample is None else
                         f"Circuit: {sample.track}\nVehicle: {sample.vehicle}\nClass: {sample.vehicle_class}\nLap: {sample.lap} | Distance: {sample.distance:.2f} m")
        for widget in (self.check, self.start, self.entry):
            widget.configure(state="disabled" if state.busy or state.closing else "normal")
        self.cancel_button.configure(state="normal" if state.busy and not state.closing else "disabled")
        self.poll_id = self.root.after(50, self.poll)


def launch():
    """Launch without probing LMU or importing Tk on unsupported platforms."""
    if sys.platform != "win32":
        raise RuntimeError("The GUI requires Windows with Python Tkinter installed.")
    try:
        import tkinter
        root = tkinter.Tk()
    except ImportError as exc:
        raise RuntimeError("Install Python for Windows with Tcl/Tk support to use the GUI.") from exc
    except tkinter.TclError as exc:
        raise RuntimeError(f"Cannot open Tk window: {exc}") from exc
    Window(root)
    root.mainloop()
