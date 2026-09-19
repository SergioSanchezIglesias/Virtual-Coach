"""Windows Tk view and display-independent worker/controller boundary."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any

from . import application
from .audio import BeepSink
from .lmu import LMUReader
from .profile import Profile


CALIBRATION_WARNING = (
    "Unverified: only telemetry continuity checked, not sporting lap validity. "
    "These candidates are not safe or calibrated driving points. "
    "Confirm only while stopped, after reviewing your fixed references; "
    "they are not a safety guarantee."
)


@dataclass
class ViewState:
    phase: str = "Idle"
    status: str = "Not checked. LMU is not required to open this window."
    session: Any = None
    draft: object = None
    review: Profile | None = None
    profiles: tuple = ()
    cue_status: str = "Stopped"
    error: str = ""
    busy: bool = False
    closing: bool = False


class Controller:
    """Only drain() changes state from worker results; workers never call Tk.

    Close is cooperative: keep polling until the service has returned and closed
    its reader. Never close a reader concurrently with an in-flight native read.
    """

    def __init__(self, services: Any = application, reader_factory: Any = LMUReader,
                 sink_factory: Any = BeepSink):
        self.services = services
        self.reader_factory = reader_factory
        self.sink_factory = sink_factory
        self.operation = None
        self.state = ViewState()
        self.messages = Queue()
        self.worker = None
        self.cancel_event = Event()

    def _start(self, operation, name=None):
        if self.state.busy or self.state.closing:
            return False
        self.operation = operation
        self.state.busy = True
        self.state.error = ""
        self.state.phase = "Waiting" if operation == "record" else "Idle"
        self.state.status = "Waiting for next lap" if operation == "record" else "Checking connection…"
        if operation == "probe":
            self.state.session = None
        elif operation == "record":
            self.state.draft = None
            self.state.review = None
        elif operation == "cues":
            self.state.cue_status = "Starting"
            self.state.status = "Starting cues…"
        self.cancel_event = Event()

        def report(text):
            self.messages.put(("progress", text))

        def work():
            try:
                if operation == "probe":
                    result = self.services.probe(self.reader_factory(), report=report)
                    if self.cancel_event.is_set():
                        raise application.OperationCancelled()
                elif operation == "cues":
                    profile = self.services.load_profile(name)
                    sink = self.sink_factory()
                    self.services.run_cues(profile, self.reader_factory(), sink,
                                           cancel=self.cancel_event, report=report)
                    result = None
                else:
                    with self.services.stopped_flow_guard():
                        result = self.services.record(name, self.reader_factory(),
                                                      report=report, cancel=self.cancel_event)
                if self.cancel_event.is_set():
                    raise application.OperationCancelled()
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

    def refresh_profiles(self):
        if self.state.busy or self.state.closing:
            return False
        try:
            self.state.profiles = tuple(self.services.discover_profiles())
            return True
        except Exception as exc:
            self.state.error = str(exc)
            return False

    def review_draft(self):
        if self.state.busy or self.state.closing or self.state.draft is None:
            return False
        try:
            self.state.review, _ = self.services.load_draft(self.state.draft)
            return True
        except Exception as exc:
            self.state.error = str(exc)
            return False

    def save(self, name, rows, confirm, confirm_overwrite):
        if self.state.busy or self.state.closing or self.state.review is None:
            return False
        self.state.error = ""
        try:
            with self.services.stopped_flow_guard():
                original = self.state.review
                original_rows = [[marker.name, *(str(distance) for distance in marker.distances)]
                                 for marker in original.markers]
                # Keep valid original numbers, including integers beyond float precision.
                profile = (original if rows == original_rows
                           else self.services.edit_profile(original, rows))
                if not confirm(CALIBRATION_WARNING + f"\nSave profile as {name!r}?"):
                    return False
                if self.state.busy or self.state.closing:
                    return False
                try:
                    path = self.services.save_profile(name, profile, confirmed=True)
                except FileExistsError:
                    if not confirm_overwrite(f"Replace existing profile {name!r}? This cannot be undone."):
                        return False
                    if self.state.busy:
                        return False
                    if self.state.closing:
                        return False
                    path = self.services.save_profile(name, profile, confirmed=True, overwrite=True)
            self.state.review = profile
            self.state.status = f"Saved profile: {path}"
            self.refresh_profiles()
            return True
        except Exception as exc:
            self.state.error = str(exc)
            return False

    def start_cues(self, path):
        if path not in self.state.profiles:
            self.state.error = "Select a confirmed profile; drafts cannot be played."
            return False
        return self._start("cues", path)

    def stop_cues(self):
        if self.operation == "cues":
            self.cancel()

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
                if self.operation == "cues" and value == "Active":
                    self.state.cue_status = "Active"
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
            elif kind == "cues":
                self.state.cue_status = "Stopped"
                self.state.status = "Cues stopped."
            elif kind == "cancelled":
                if self.operation == "cues":
                    self.state.cue_status = "Stopped"
                self.state.phase = "Cancelled"
                self.state.status = "Operation cancelled."
            elif kind == "error":
                if self.operation == "cues":
                    self.state.cue_status = "Error"
                self.state.phase = "Error"
                self.state.error = value + " Check LMU/session availability, matching profile, audio and output path, then retry. Existing drafts are not replaced; choose a new name."
                self.state.status = "Operation failed."
            elif kind == "done":
                self.state.busy = False
        return self.state


class Window:
    def __init__(self, root, controller=None):
        from tkinter import Canvas, StringVar, ttk

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
        ttk.Separator(frame).grid(sticky="ew", pady=6)
        ttk.Label(frame, text="Review and save — stopped only").grid(sticky="w")
        self.warning = StringVar()
        ttk.Label(frame, textvariable=self.warning, wraplength=620).grid(sticky="w")
        editor = ttk.Frame(frame)
        editor.grid(sticky="ew")
        editor.columnconfigure(0, weight=1)
        canvas = Canvas(editor, height=180, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(editor, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        self.table = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self.table, anchor="nw")
        self.table.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        self.rows = []
        self.edit_widgets = []
        self.loaded_draft = None
        self.output_name = StringVar(value="lap")
        ttk.Label(frame, text="Output profile name (letters/digits/hyphens/underscores)").grid(sticky="w")
        self.output_entry = ttk.Entry(frame, textvariable=self.output_name)
        self.output_entry.grid(sticky="ew")
        self.save_button = ttk.Button(frame, text="Confirm and save profile", command=self.save)
        self.save_button.grid(sticky="w")
        ttk.Separator(frame).grid(sticky="ew", pady=6)
        ttk.Label(frame, text="Drive cues — confirmed profiles only").grid(sticky="w")
        self.selected_profile = StringVar()
        self.selector = ttk.Combobox(frame, textvariable=self.selected_profile, state="readonly")
        self.selector.grid(sticky="ew")
        self.refresh_button = ttk.Button(frame, text="Refresh profiles", command=self.controller.refresh_profiles)
        self.refresh_button.grid(sticky="w")
        self.cue_start = ttk.Button(frame, text="Start cues", command=self.start_cues)
        self.cue_start.grid(sticky="w")
        self.cue_stop = ttk.Button(frame, text="Stop cues", command=self.controller.stop_cues)
        self.cue_stop.grid(sticky="w")
        self.cue_status = StringVar(value="Stopped")
        ttk.Label(frame, textvariable=self.cue_status).grid(sticky="w")
        self.controller.refresh_profiles()
        self.poll_id = None
        self.poll()

    def save(self):
        from tkinter import messagebox

        self.controller.save(
            self.output_name.get(), [[value.get() for value in row] for row in self.rows],
            lambda text: messagebox.askyesno("Confirm reviewed references", text, parent=self.root),
            lambda text: messagebox.askyesno("Confirm replacement", text, parent=self.root))

    def start_cues(self):
        selected = self.selected_profile.get()
        path = next((path for path in self.controller.state.profiles if str(path) == selected), None)
        self.controller.start_cues(path)

    def render_review(self):
        from tkinter import StringVar, ttk

        for widget in self.table.winfo_children():
            widget.destroy()
        self.rows = []
        self.edit_widgets = []
        profile = self.controller.state.review
        if profile is None:
            return
        for column, title in enumerate(("Corner", "Brake (m)", "Release brake (m)", "Throttle (m)")):
            ttk.Label(self.table, text=title).grid(row=0, column=column)
        for index, marker in enumerate(profile.markers, 1):
            row = []
            for column, value in enumerate((marker.name, *(str(distance) for distance in marker.distances))):
                variable = StringVar(value=value)
                entry = ttk.Entry(self.table, textvariable=variable, width=18)
                entry.grid(row=index, column=column, sticky="ew")
                row.append(variable)
                self.edit_widgets.append(entry)
            self.rows.append(row)

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
        if state.draft is None and self.loaded_draft is not None:
            self.loaded_draft = None
            self.render_review()
        if state.draft != self.loaded_draft and not state.busy and not state.closing:
            self.loaded_draft = state.draft
            if state.draft is not None:
                self.controller.review_draft()
            self.render_review()
        self.warning.set(CALIBRATION_WARNING if state.draft is not None else "")
        editable = not state.busy and not state.closing and state.review is not None
        for widget in (*self.edit_widgets, self.output_entry, self.save_button):
            widget.configure(state="normal" if editable else "disabled")
        available = not state.busy and not state.closing
        self.selector.configure(values=tuple(str(path) for path in state.profiles),
                                state="readonly" if available else "disabled")
        self.refresh_button.configure(state="normal" if available else "disabled")
        self.cue_start.configure(state="normal" if available and state.profiles else "disabled")
        self.cue_stop.configure(state="normal" if state.busy and self.controller.operation == "cues"
                                and not state.closing else "disabled")
        self.cue_status.set(state.cue_status)
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
