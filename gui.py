#!/usr/bin/env python3
"""
gui.py — Ventana del coach.

Eliges la vuelta de referencia (CSV de Garage61), la procesa sola, afinas los
avisos al oido y lanzas el coach. Nada mas.

Decision de arquitectura (intacta desde la primera version): esta ventana NO
conoce la logica del coach. Lanza analyzer.py y coach.py como procesos APARTE,
con los mismos comandos que se teclearian a mano. El core validado en pista no
se importa ni se toca: la ventana solo lo orquesta desde fuera. Un bug aqui
nunca puede tumbar el coach.

Sobre los ajustes: todo lo que antes solo existia por linea de comandos y se
afinaba al oido (--lead, --volume, --countdown, --countdown-interval,
--voice-volume, --count-volume) esta arriba, a mano. Lo que casi nunca se toca
(--margin, --speed-tol, --review-top) vive plegado en "Ajuste fino", porque una
ventana que lo ensena todo a la vez no ensena nada.

El modo prueba (--replay) NO esta aqui a proposito: es una herramienta de
desarrollo, y en la ventana solo estorbaba. Sigue en el CLI.

    python gui.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

try:
    import customtkinter as ctk
except ImportError:  # mensaje claro en vez de un traceback de 20 lineas
    sys.exit("Falta customtkinter. Instalalo con:  pip install customtkinter")

HERE = Path(__file__).resolve().parent

# Windows: evita que cada subproceso abra una ventana de consola negra.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# --- Paleta ---------------------------------------------------------------
# El color es lenguaje del dominio, no decoracion: cada tipo de aviso tiene el
# suyo y es el MISMO en los ajustes y en el registro. De un vistazo sabes que
# ha sonado sin leer la linea entera.
BG        = "#0D1015"
SURFACE   = "#151A21"
SURFACE_2 = "#1C222B"
LINE      = "#28303C"
TEXT      = "#E9EEF4"
DIM       = "#8892A0"
FAINT     = "#5C6674"
ACCENT    = "#7CE38B"   # gas / todo en orden
BRAKE     = "#FF5C4D"   # frenada
LIFT      = "#4DA3FF"   # suelta (lift)
MANAGE    = "#B98CFF"   # zona de gestion (medio gas)
VOICE     = "#FFB020"   # voz

HOVER     = "#222A35"
ACCENT_HV = "#6BC978"
# Tk no entiende canal alfa (#RRGGBBAA): estos son los tonos del diseno ya
# mezclados sobre el fondo, en solido.
BRAKE_BG  = "#1E1416"
BRAKE_LN  = "#6E2E2B"
READY_BG  = "#132018"

MONO = "Menlo" if sys.platform == "darwin" else "Consolas"

# Parametros por defecto: los mismos que el coach, salvo la cuenta atras, que
# se afino al oido en pista.
DEFAULTS = {
    "lead": 0.35,
    "volume": 0.35,
    "voice_volume": 0.60,
    "countdown": 3,
    "countdown_interval": 0.75,
    "count_volume": 0.20,
    "margin": 0,
    "speed_tol": 0.10,
    "review_top": 2,
}


def _tool_cmd(tool: str) -> list[str]:
    """Comando base para invocar analyzer/coach, empaquetado o en desarrollo.

    Empaquetado (PyInstaller): el propio ejecutable se llama a si mismo con el
    nombre de la herramienta ("VirtualCoach.exe coach ..."). En desarrollo:
    "python app.py coach ...". Asi no hace falta un python ni los .py sueltos.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, tool]
    return [sys.executable, str(HERE / "app.py"), tool]


class Stepper(ctk.CTkFrame):
    """Un ajuste numerico: etiqueta, [-] valor [+] y una barra de posicion.

    Botones y no un slider a proposito: con un slider no clavas 0.35, y estos
    numeros se afinan al oido en saltos concretos, no arrastrando el raton.
    """

    def __init__(self, master, label: str, hint: str, *, vmin: float,
                 vmax: float, step: float, value: float, fmt, color: str = ACCENT):
        super().__init__(master, fg_color=SURFACE_2, corner_radius=10)
        self.vmin, self.vmax, self.step = vmin, vmax, step
        self.value = value
        self.fmt = fmt

        self.grid_columnconfigure(0, weight=1)

        texts = ctk.CTkFrame(self, fg_color="transparent")
        texts.grid(row=0, column=0, sticky="w", padx=(14, 0), pady=(11, 0))
        self.label = ctk.CTkLabel(texts, text=label, font=ctk.CTkFont(size=13, weight="bold"),
                                  text_color=TEXT, anchor="w")
        self.label.pack(anchor="w")
        self.hint = ctk.CTkLabel(texts, text=hint, font=ctk.CTkFont(size=11),
                                 text_color=FAINT, anchor="w")
        self.hint.pack(anchor="w")

        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.grid(row=0, column=1, sticky="e", padx=(0, 12), pady=(11, 0))
        self.minus = ctk.CTkButton(ctrl, text="−", width=30, height=30, corner_radius=8,
                                   fg_color=SURFACE, hover_color=HOVER, border_width=1,
                                   border_color=LINE, text_color=DIM,
                                   font=ctk.CTkFont(size=15), command=lambda: self._bump(-1))
        self.minus.pack(side="left")
        self.readout = ctk.CTkLabel(ctrl, text="", width=84, height=30, corner_radius=8,
                                    fg_color=SURFACE, text_color=TEXT,
                                    font=ctk.CTkFont(family=MONO, size=13))
        self.readout.pack(side="left", padx=6)
        self.plus = ctk.CTkButton(ctrl, text="+", width=30, height=30, corner_radius=8,
                                  fg_color=SURFACE, hover_color=HOVER, border_width=1,
                                  border_color=LINE, text_color=DIM,
                                  font=ctk.CTkFont(size=15), command=lambda: self._bump(1))
        self.plus.pack(side="left")

        self.bar = ctk.CTkProgressBar(self, height=4, corner_radius=2,
                                      fg_color=LINE, progress_color=color)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(9, 13))

        self._refresh()

    def _bump(self, sign: int) -> None:
        v = self.value + sign * self.step
        # Redondeo al paso: sin esto, sumar 0.05 quince veces da 0.7500000001.
        v = round(round(v / self.step) * self.step, 6)
        self.value = max(self.vmin, min(self.vmax, v))
        self._refresh()

    def _refresh(self) -> None:
        self.readout.configure(text=self.fmt(self.value))
        span = self.vmax - self.vmin
        self.bar.set((self.value - self.vmin) / span if span else 0)

    def get(self) -> float:
        return self.value

    def set_enabled(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.minus.configure(state=state)
        self.plus.configure(state=state)
        self.readout.configure(text_color=TEXT if on else FAINT)
        self.label.configure(text_color=TEXT if on else FAINT)


class ToggleRow(ctk.CTkFrame):
    """Una opcion de si/no con su explicacion y una barra de color al canto."""

    def __init__(self, master, title: str, hint: str, color: str,
                 value: bool = False, command=None):
        super().__init__(master, fg_color=SURFACE_2, corner_radius=10)
        self.var = ctk.BooleanVar(value=value)

        ctk.CTkFrame(self, width=3, height=34, corner_radius=2,
                     fg_color=color).pack(side="left", padx=(12, 12), pady=12)

        texts = ctk.CTkFrame(self, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, pady=11)
        self.title = ctk.CTkLabel(texts, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                                  text_color=TEXT, anchor="w")
        self.title.pack(anchor="w")
        self.hint = ctk.CTkLabel(texts, text=hint, font=ctk.CTkFont(size=11),
                                 text_color=FAINT, anchor="w")
        self.hint.pack(anchor="w")

        self.switch = ctk.CTkSwitch(self, text="", width=44, variable=self.var,
                                    progress_color=color, button_color=TEXT,
                                    fg_color=LINE, command=command)
        self.switch.pack(side="right", padx=(0, 16))

    def get(self) -> bool:
        return self.var.get()

    def set_enabled(self, on: bool) -> None:
        self.switch.configure(state="normal" if on else "disabled")
        self.title.configure(text_color=TEXT if on else FAINT)


class CoachGUI:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.csv: Path | None = None         # CSV de referencia elegido
        self.reference: Path | None = None   # JSON que genera analyzer
        self.coach_proc: subprocess.Popen | None = None

        root.title("Virtual Coach")
        root.geometry("780x920")
        root.minsize(720, 780)
        root.configure(fg_color=BG)

        self._build_header()
        body = ctk.CTkFrame(root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._build_reference(body)
        self._build_settings(body)
        self._build_fine(body)
        self._build_toggles(body)
        self._build_actions(body)
        self._build_log(body)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Elige una vuelta de referencia para empezar.", "dim")

    # -----------------------------------------------------------------------
    # Construccion de la ventana
    # -----------------------------------------------------------------------
    def _build_header(self) -> None:
        head = ctk.CTkFrame(self.root, fg_color=SURFACE, corner_radius=0, height=66)
        head.pack(fill="x")
        head.pack_propagate(False)

        mark = ctk.CTkFrame(head, width=34, height=34, corner_radius=9, fg_color=ACCENT)
        mark.pack(side="left", padx=(20, 12))
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="VC", text_color=BG,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(expand=True)

        texts = ctk.CTkFrame(head, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(texts, text="VIRTUAL COACH", text_color=TEXT, anchor="w",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")
        self.tagline = ctk.CTkLabel(texts, text="Ninguna vuelta cargada", text_color=FAINT,
                                    anchor="w", font=ctk.CTkFont(size=11))
        self.tagline.pack(anchor="w")

        self.chip = ctk.CTkLabel(head, text="  ●  En espera  ", corner_radius=99,
                                 fg_color=SURFACE_2, text_color=DIM,
                                 font=ctk.CTkFont(size=12, weight="bold"), height=28)
        self.chip.pack(side="right", padx=20)

    def _build_reference(self, parent) -> None:
        card = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12,
                            border_width=1, border_color=LINE)
        card.pack(fill="x", pady=(18, 16))

        texts = ctk.CTkFrame(card, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, padx=16, pady=14)
        self.ref_title = ctk.CTkLabel(texts, text="Elige la vuelta de referencia",
                                      text_color=TEXT, anchor="w",
                                      font=ctk.CTkFont(size=14, weight="bold"))
        self.ref_title.pack(anchor="w")
        self.ref_meta = ctk.CTkLabel(texts, text="CSV exportado de Garage61 — se procesa solo",
                                     text_color=DIM, anchor="w", font=ctk.CTkFont(size=12))
        self.ref_meta.pack(anchor="w")

        self.pick_btn = ctk.CTkButton(card, text="Elegir CSV…", width=140, height=34,
                                      corner_radius=9, fg_color=ACCENT, hover_color=ACCENT_HV,
                                      text_color=BG, font=ctk.CTkFont(size=13, weight="bold"),
                                      command=self.pick_reference)
        self.pick_btn.pack(side="right", padx=16)

    def _section(self, parent, title: str, hint: str = "") -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(row, text=title, text_color=DIM,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        if hint:
            ctk.CTkLabel(row, text=hint, text_color=FAINT,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=8)

    @staticmethod
    def _new_row(parent):
        """Fila de dos ajustes. Los Stepper se crean DENTRO de ella: un
        pack(in_=...) entre hermanos deja el widget detras del contenedor."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))
        return row

    @staticmethod
    def _pack_pair(left, right) -> None:
        left.pack(side="left", fill="x", expand=True, padx=(0, 7))
        right.pack(side="left", fill="x", expand=True, padx=(7, 0))

    def _build_settings(self, parent) -> None:
        self._section(parent, "AVISOS", "afinalo al oido, rodando")
        row = self._new_row(parent)
        self.s_lead = Stepper(row, "Antelacion", "cuanto antes suena el pitido",
                              vmin=0.05, vmax=1.0, step=0.05, value=DEFAULTS["lead"],
                              fmt=lambda v: f"{v:.2f} s")
        self.s_volume = Stepper(row, "Volumen de pitidos", "los cuatro tonos, a la vez",
                                vmin=0.05, vmax=1.0, step=0.05, value=DEFAULTS["volume"],
                                fmt=lambda v: f"{v:.2f}", color=BRAKE)
        self._pack_pair(self.s_lead, self.s_volume)

        row = self._new_row(parent)
        self.s_countdown = Stepper(row, "Cuenta atras", "ticks de preparacion antes de frenar",
                                   vmin=0, vmax=8, step=1, value=DEFAULTS["countdown"],
                                   fmt=lambda v: "sin cuenta" if v < 1 else f"{int(v)} ticks")
        self.s_interval = Stepper(row, "Ritmo de la cuenta", "segundos entre tick y tick",
                                  vmin=0.20, vmax=1.5, step=0.05,
                                  value=DEFAULTS["countdown_interval"],
                                  fmt=lambda v: f"{v:.2f} s")
        self._pack_pair(self.s_countdown, self.s_interval)

        row = self._new_row(parent)
        self.s_voice_vol = Stepper(row, "Volumen de voz", "para que gane al ruido del motor",
                                   vmin=0.0, vmax=1.5, step=0.05,
                                   value=DEFAULTS["voice_volume"],
                                   fmt=lambda v: f"{v:.2f}", color=VOICE)
        self.s_count_vol = Stepper(row, "Volumen de los ticks", "la cuenta atras, no el pitido",
                                   vmin=0.0, vmax=1.0, step=0.05,
                                   value=DEFAULTS["count_volume"], fmt=lambda v: f"{v:.2f}")
        self._pack_pair(self.s_voice_vol, self.s_count_vol)

    def _build_fine(self, parent) -> None:
        """Ajuste fino: plegado por defecto. Esta aqui el dia que haga falta."""
        box = ctk.CTkFrame(parent, fg_color="#12161C", corner_radius=12,
                           border_width=1, border_color=LINE)
        box.pack(fill="x", pady=(2, 16))

        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=12)
        self.fine_btn = ctk.CTkButton(head, text="▸  AJUSTE FINO", width=140, height=22,
                                      fg_color="transparent", hover_color=SURFACE_2,
                                      text_color=DIM, anchor="w",
                                      font=ctk.CTkFont(size=11, weight="bold"),
                                      command=self._toggle_fine)
        self.fine_btn.pack(side="left")
        ctk.CTkLabel(head, text="no lo toques sin motivo", text_color=FAINT,
                     font=ctk.CTkFont(size=11)).pack(side="left")

        self.fine_box = ctk.CTkFrame(box, fg_color="transparent")
        self.fine_open = False

        row = self._new_row(self.fine_box)
        self.s_margin = Stepper(row, "Margen de seguridad",
                                "metros extra de antelacion",
                                vmin=0, vmax=50, step=1, value=DEFAULTS["margin"],
                                fmt=lambda v: f"{int(v)} m")
        self.s_speed_tol = Stepper(row, "Tolerancia de velocidad",
                                   "si llegas muy distinto, no avisa",
                                   vmin=0.02, vmax=0.40, step=0.01,
                                   value=DEFAULTS["speed_tol"], fmt=lambda v: f"{v * 100:.0f} %")
        self._pack_pair(self.s_margin, self.s_speed_tol)

        row = self._new_row(self.fine_box)
        self.s_review = Stepper(row, "Consejos por vuelta", "como mucho, los peores",
                                vmin=0, vmax=5, step=1, value=DEFAULTS["review_top"],
                                fmt=lambda v: "ninguno" if v < 1 else f"{int(v)}",
                                color=MANAGE)
        self.s_review.pack(fill="x", expand=True)

    def _toggle_fine(self) -> None:
        self.fine_open = not self.fine_open
        if self.fine_open:
            self.fine_box.pack(fill="x", padx=14, pady=(0, 6))
            self.fine_btn.configure(text="▾  AJUSTE FINO")
        else:
            self.fine_box.pack_forget()
            self.fine_btn.configure(text="▸  AJUSTE FINO")

    def _build_toggles(self, parent) -> None:
        self._section(parent, "QUE QUIERES OIR")
        self.t_voice = ToggleRow(parent, "Voz",
                                 "\"Frena, 40%, tercera\" antes de cada pitido",
                                 VOICE, value=True, command=self._sync_training)
        self.t_voice.pack(fill="x", pady=(0, 8))

        # Entrenamiento CUELGA de la voz: sin frase no hay donde meter la
        # correccion (un pitido no puede decirte "suave"), asi que al apagar la
        # voz esta fila se apaga y se agrisa. Nada de opciones que parecen
        # hacer algo y no hacen nada.
        indent = ctk.CTkFrame(parent, fg_color="transparent")
        indent.pack(fill="x", pady=(0, 16))
        self.t_training = ToggleRow(indent, "Entrenamiento",
                                    "corrige la curva que peor te sale (\"…tercera, suave\")",
                                    MANAGE)
        self.t_training.pack(fill="x", padx=(26, 0))

    def _build_actions(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 16))
        self.start_btn = ctk.CTkButton(row, text="▶   Empezar", height=48, corner_radius=11,
                                       fg_color=ACCENT, hover_color=ACCENT_HV, text_color=BG,
                                       font=ctk.CTkFont(size=15, weight="bold"),
                                       state="disabled", command=self.start_coach)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.stop_btn = ctk.CTkButton(row, text="■   Parar", width=190, height=48,
                                      corner_radius=11, fg_color=SURFACE, hover_color=HOVER,
                                      border_width=1, border_color=LINE, text_color=FAINT,
                                      font=ctk.CTkFont(size=15, weight="bold"),
                                      state="disabled", command=self.stop_coach)
        self.stop_btn.pack(side="right")

    def _build_log(self, parent) -> None:
        box = ctk.CTkFrame(parent, fg_color="#0A0D11", corner_radius=12,
                           border_width=1, border_color=LINE)
        box.pack(fill="both", expand=True)

        head = ctk.CTkFrame(box, fg_color=SURFACE, corner_radius=0, height=34)
        head.pack(fill="x", padx=1, pady=(1, 0))
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="REGISTRO", text_color=DIM,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=14)
        ctk.CTkButton(head, text="Limpiar", width=60, height=22, fg_color="transparent",
                      hover_color=SURFACE_2, text_color=FAINT,
                      font=ctk.CTkFont(size=11), command=self.clear_log).pack(side="right", padx=8)

        self.log_box = ctk.CTkTextbox(box, fg_color="#0A0D11", text_color=DIM, wrap="word",
                                      border_width=0, font=(MONO, 12))
        self.log_box.pack(fill="both", expand=True, padx=12, pady=10)
        for tag, color in (("brake", BRAKE), ("gas", ACCENT), ("lift", LIFT),
                           ("manage", MANAGE), ("voice", VOICE), ("dim", DIM),
                           ("faint", FAINT)):
            self.log_box.tag_config(tag, foreground=color)
        self.log_box.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Estado
    # -----------------------------------------------------------------------
    def _sync_training(self) -> None:
        """La fila de entrenamiento sigue a la de voz."""
        on = self.t_voice.get()
        self.t_training.set_enabled(on)
        if not on:
            self.t_training.var.set(False)

    def _set_chip(self, text: str, color: str, bg: str) -> None:
        self.chip.configure(text=f"  ●  {text}  ", text_color=color, fg_color=bg)

    def _set_controls_enabled(self, on: bool) -> None:
        """Rodando no se toca nada: los flags ya viajaron con el proceso."""
        for s in (self.s_lead, self.s_volume, self.s_countdown, self.s_interval,
                  self.s_voice_vol, self.s_count_vol, self.s_margin,
                  self.s_speed_tol, self.s_review):
            s.set_enabled(on)
        self.t_voice.set_enabled(on)
        self.t_training.set_enabled(on and self.t_voice.get())
        self.pick_btn.configure(state="normal" if on else "disabled")

    # -----------------------------------------------------------------------
    # Paso 1: procesar la referencia (analyzer es rapido, va sincrono)
    # -----------------------------------------------------------------------
    def pick_reference(self) -> None:
        path = filedialog.askopenfilename(
            title="Elige la vuelta de referencia (CSV de Garage61)",
            filetypes=[("CSV de telemetria", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return

        csv = Path(path)
        track = csv.stem
        out = csv.with_name(f"ref_{track}.json")

        self.log(f"\nProcesando {csv.name}…", "dim")
        cmd = _tool_cmd("analyzer") + [str(csv), "--track", track, "-o", str(out)]
        # Sincrono a proposito: analyzer tarda <1 s y necesitamos su resultado
        # antes de dejar rodar. El parpadeo de la ventana es imperceptible.
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=CREATE_NO_WINDOW)
        self.log(result.stdout.strip(), "dim")
        if result.returncode != 0 or not out.exists():
            self.log(f"[!] No se pudo procesar: {result.stderr.strip()}", "brake")
            return

        self.csv = csv
        self.reference = out
        self._show_reference(out, csv)
        self.start_btn.configure(state="normal")

    def _show_reference(self, ref: Path, csv: Path) -> None:
        """Lee el JSON del analyzer y cuenta lo que hay. Sin importar el core."""
        try:
            data = json.loads(ref.read_text())
        except (OSError, ValueError):
            self.ref_title.configure(text=csv.name)
            self.ref_meta.configure(text="cargada")
            return

        events = data.get("events", [])
        n = {k: sum(1 for e in events if e.get("type") == k)
             for k in ("brake", "throttle", "lift", "manage")}
        partes = [f"{len(events)} avisos"]
        for kind, nombre in (("brake", "frenadas"), ("throttle", "salidas"),
                             ("lift", "lifts"), ("manage", "gestion")):
            if n[kind]:
                partes.append(f"{n[kind]} {nombre}")

        self.ref_title.configure(text=csv.name)
        self.ref_meta.configure(text=" · ".join(partes))
        self.pick_btn.configure(text="Cambiar vuelta", fg_color=SURFACE_2,
                                hover_color=HOVER, text_color=DIM)

        largo = data.get("track_length_m")
        track = data.get("track", csv.stem)
        cola = f" · {largo:,.0f} m estimados".replace(",", ".") if largo else ""
        self.tagline.configure(text=f"{track}{cola}")
        self._set_chip("Listo", ACCENT, READY_BG)

    # -----------------------------------------------------------------------
    # Paso 2: el coach (loop infinito + audio, va como proceso aparte)
    # -----------------------------------------------------------------------
    def start_coach(self) -> None:
        if self.reference is None or self.coach_proc is not None:
            return

        cmd = _tool_cmd("coach") + [
            str(self.reference),
            "--lead", f"{self.s_lead.get():.2f}",
            "--volume", f"{self.s_volume.get():.2f}",
            "--margin", f"{self.s_margin.get():.0f}",
            "--speed-tol", f"{self.s_speed_tol.get():.2f}",
            "--countdown", f"{int(self.s_countdown.get())}",
            "--countdown-interval", f"{self.s_interval.get():.2f}",
            "--count-volume", f"{self.s_count_vol.get():.2f}",
            "--voice-volume", f"{self.s_voice_vol.get():.2f}",
            "--review-top", f"{int(self.s_review.get())}",
        ]
        if self.t_voice.get():
            cmd += ["--voice"]
            if self.t_training.get():
                cmd += ["--training"]

        self.log("\n▶  Arrancando coach — iRacing en vivo…", "gas")

        self.coach_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
        )
        # Su salida se lee en un hilo y se vuelca al registro con root.after,
        # que es la unica forma segura de tocar widgets desde otro hilo en Tk.
        threading.Thread(target=self._pump_output, daemon=True).start()

        self.start_btn.configure(state="disabled", text="Rodando…",
                                 fg_color=SURFACE, text_color=FAINT)
        self.stop_btn.configure(state="normal", fg_color=BRAKE_BG,
                                border_color=BRAKE_LN, text_color=BRAKE)
        self._set_controls_enabled(False)
        self._set_chip("En pista", BRAKE, BRAKE_BG)

    def _pump_output(self) -> None:
        assert self.coach_proc is not None and self.coach_proc.stdout is not None
        for line in self.coach_proc.stdout:
            self.root.after(0, self.log, line.rstrip())
        self.root.after(0, self._coach_ended)

    def stop_coach(self) -> None:
        if self.coach_proc is not None and self.coach_proc.poll() is None:
            self.coach_proc.terminate()  # el SO libera el audio al morir el proceso

    def _coach_ended(self) -> None:
        self.coach_proc = None
        self.log("■  Coach detenido.", "dim")
        self.start_btn.configure(state="normal" if self.reference else "disabled",
                                 text="▶   Empezar", fg_color=ACCENT, text_color=BG)
        self.stop_btn.configure(state="disabled", fg_color=SURFACE,
                                border_color=LINE, text_color=FAINT)
        self._set_controls_enabled(True)
        self._sync_training()
        self._set_chip("Listo" if self.reference else "En espera",
                       ACCENT if self.reference else DIM,
                       READY_BG if self.reference else SURFACE_2)

    # -----------------------------------------------------------------------
    # Registro
    # -----------------------------------------------------------------------
    @staticmethod
    def _tag_for(msg: str) -> str:
        """Colorea por tipo de aviso. El orden importa: "MEDIO GAS" contiene
        "GAS", y la voz dice "Frena" igual que el pitido de frenada."""
        s = msg.strip()
        if s.startswith("[voz]"):
            return "voice"
        if s.startswith("MEDIO GAS"):
            return "manage"
        if s.startswith("FRENA"):
            return "brake"
        if s.startswith("SUELTA"):
            return "lift"
        if s.startswith("GAS"):
            return "gas"
        if s in {".", ""} or s.startswith("."):
            return "faint"
        return "dim"

    def log(self, msg: str, tag: str | None = None) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n", tag or self._tag_for(msg))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def on_close(self) -> None:
        # No dejar un coach huerfano sonando tras cerrar la ventana.
        if self.coach_proc is not None and self.coach_proc.poll() is None:
            self.coach_proc.terminate()
        self.root.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    CoachGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
