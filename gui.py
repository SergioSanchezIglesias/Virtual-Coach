#!/usr/bin/env python3
"""
gui.py — Ventana del coach.

Eliges la vuelta de referencia (CSV de Garage61), la procesa sola, decides
que quieres oir y ver (pitidos, voz, clasificacion) y lanzas el coach. Nada mas.

Decision de arquitectura (intacta desde la primera version): esta ventana NO
conoce la logica del coach. Lanza analyzer.py y coach.py como procesos APARTE,
con los mismos comandos que se teclearian a mano. El core validado en pista no
se importa ni se toca: la ventana solo lo orquesta desde fuera. Un bug aqui
nunca puede tumbar el coach.

Sobre los ajustes: ya no hay. La ventana tuvo steppers para --lead, --volume,
--countdown, --countdown-interval, --voice-volume, --count-volume y un "ajuste
fino" plegado; tras varias sesiones rodando con los valores de fabrica, Sergio
no tocaba ninguno (ago-2026), y una fila de ajustes que nadie toca solo es
ruido delante del boton de Empezar. Los valores afinados en pista viven en
DEFAULTS y viajan al coach en cada arranque. Quien quiera afinar sigue teniendo
el CLI de coach.py con todos los flags.

El modo prueba (--replay) NO esta aqui a proposito: es una herramienta de
desarrollo, y en la ventana solo estorbaba. Sigue en el CLI.

    python gui.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog

try:
    import customtkinter as ctk
except ImportError as exc:  # se relanza: app.py lo escribe al log de arranque
    raise ImportError(
        "Falta customtkinter. En desarrollo: pip install customtkinter. "
        "En el .exe: revisa collect_all('customtkinter') en VirtualCoach.spec"
    ) from exc

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

# Parametros afinados en pista. Son los que la ventana pasa SIEMPRE al coach:
# coinciden con los del CLI salvo la cuenta atras (0.75, decidido en ago-2026).
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
        self.overlay_proc: subprocess.Popen | None = None

        root.title("Virtual Coach")
        # Alta como el contenido pero nunca mas que la pantalla: en un monitor
        # de 1080p con barra de tareas se comia el registro y los botones.
        alto = min(760, root.winfo_screenheight() - 90)
        root.geometry(f"780x{alto}")
        root.minsize(720, 560)
        root.configure(fg_color=BG)

        self._build_header()
        # Con scroll: si la ventana no cabe entera, se llega a todo igual.
        body = ctk.CTkScrollableFrame(root, fg_color="transparent",
                                      scrollbar_button_color=SURFACE_2,
                                      scrollbar_button_hover_color=LINE)
        body.pack(fill="both", expand=True, padx=(20, 8), pady=(0, 20))
        self._build_reference(body)
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

    def _build_toggles(self, parent) -> None:
        self._section(parent, "QUE QUIERES OIR")
        self.t_beeps = ToggleRow(parent, "Pitidos",
                                 "freno, gas, suelta y medio gas, con su cuenta atras",
                                 BRAKE, value=True)
        self.t_beeps.pack(fill="x", pady=(0, 8))
        self.t_voice = ToggleRow(parent, "Voz",
                                 "\"Frena, 40%, tercera\" antes de cada pitido",
                                 VOICE, value=True)
        self.t_voice.pack(fill="x", pady=(0, 16))

        self._section(parent, "QUE QUIERES VER")
        self.t_overlay = ToggleRow(parent, "Clasificacion en pantalla",
                                   "tabla por clases con el iRating estimado, encima del juego",
                                   LIFT, value=True)
        self.t_overlay.pack(fill="x", pady=(0, 16))

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
                                      border_width=0, font=(MONO, 12), height=240)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=10)
        for tag, color in (("brake", BRAKE), ("gas", ACCENT), ("lift", LIFT),
                           ("manage", MANAGE), ("voice", VOICE), ("dim", DIM),
                           ("faint", FAINT)):
            self.log_box.tag_config(tag, foreground=color)
        self.log_box.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Estado
    # -----------------------------------------------------------------------
    def _set_chip(self, text: str, color: str, bg: str) -> None:
        self.chip.configure(text=f"  ●  {text}  ", text_color=color, fg_color=bg)

    def _set_controls_enabled(self, on: bool) -> None:
        """Rodando no se toca nada: los flags ya viajaron con el proceso."""
        for t in (self.t_beeps, self.t_voice, self.t_overlay):
            t.set_enabled(on)
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

        d = DEFAULTS
        # "Pitidos" apagado = tonos y ticks a volumen cero. El coach sigue
        # calculando y registrando cada aviso igual (y la voz, si esta, suena
        # sola): no hay un flag de silencio en el core y no hace falta uno.
        volume = d["volume"] if self.t_beeps.get() else 0.0
        count_volume = d["count_volume"] if self.t_beeps.get() else 0.0
        cmd = _tool_cmd("coach") + [
            str(self.reference),
            "--lead", f"{d['lead']:.2f}",
            "--volume", f"{volume:.2f}",
            "--margin", f"{d['margin']:.0f}",
            "--speed-tol", f"{d['speed_tol']:.2f}",
            "--countdown", f"{int(d['countdown'])}",
            "--countdown-interval", f"{d['countdown_interval']:.2f}",
            "--count-volume", f"{count_volume:.2f}",
            "--voice-volume", f"{d['voice_volume']:.2f}",
            "--review-top", f"{int(d['review_top'])}",
        ]
        if self.t_voice.get():
            cmd += ["--voice"]

        self.log("\n▶  Arrancando coach — iRacing en vivo…", "gas")

        self.coach_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
        )
        # Su salida se lee en un hilo y se vuelca al registro con root.after,
        # que es la unica forma segura de tocar widgets desde otro hilo en Tk.
        threading.Thread(target=self._pump_output, daemon=True).start()
        if self.t_overlay.get():
            self._start_overlay()

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

    def _start_overlay(self) -> None:
        """El overlay va como proceso aparte, igual que el coach.

        Cada sesion se graba sola en sesiones/ (JSONL de fotos de la sesion):
        es lo que permite reproducir una carrera en el Mac y afinar el overlay
        sin el juego. Pesa poco (unas decenas de KB por minuto).
        """
        sesiones = HERE / "sesiones"
        sesiones.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M")
        cmd = _tool_cmd("overlay") + ["--record", str(sesiones / f"{stamp}.jsonl")]
        # Su salida va a un log junto a las grabaciones: si el overlay no
        # aparece, ahi esta el porque (con DEVNULL se moria en silencio).
        self._overlay_log = open(sesiones / "overlay.log", "a", encoding="utf-8")
        self.overlay_proc = subprocess.Popen(
            cmd, stdout=self._overlay_log, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        self.log("▦  Overlay de clasificacion en pantalla (Esc sobre el, o Parar, lo cierra).", "lift")
        self.log(f"   graba en {sesiones / (stamp + '.jsonl')}; log en sesiones/overlay.log", "dim")
        self.root.after(3000, self._check_overlay)

    def _check_overlay(self) -> None:
        p = self.overlay_proc
        if p is not None and p.poll() is not None:
            self.log(f"[!] El overlay se ha cerrado solo (codigo {p.returncode}). "
                     "Mira sesiones/overlay.log.", "brake")

    def _stop_overlay(self) -> None:
        if self.overlay_proc is not None and self.overlay_proc.poll() is None:
            self.overlay_proc.terminate()
        self.overlay_proc = None
        log = getattr(self, "_overlay_log", None)
        if log is not None:
            log.close()
            self._overlay_log = None

    def stop_coach(self) -> None:
        self._stop_overlay()
        if self.coach_proc is not None and self.coach_proc.poll() is None:
            self.coach_proc.terminate()  # el SO libera el audio al morir el proceso

    def _coach_ended(self) -> None:
        self.coach_proc = None
        self._stop_overlay()
        self.log("■  Coach detenido.", "dim")
        self.start_btn.configure(state="normal" if self.reference else "disabled",
                                 text="▶   Empezar", fg_color=ACCENT, text_color=BG)
        self.stop_btn.configure(state="disabled", fg_color=SURFACE,
                                border_color=LINE, text_color=FAINT)
        self._set_controls_enabled(True)
        self._set_chip("Listo" if self.reference else "En espera",
                       ACCENT if self.reference else DIM,
                       READY_BG if self.reference else SURFACE_2)

    # -----------------------------------------------------------------------
    # Registro
    # -----------------------------------------------------------------------
    @staticmethod
    def _tag_for(msg: str) -> str:
        """Colorea por tipo de aviso. El orden importa: "MEDIO GAS" contiene
        "GAS", la voz dice "Frena" igual que el pitido, y la linea "(omitido
        brake...)" contiene el nombre del evento pero es un descarte.

        Rodando de verdad el coach no imprime "FRENA"/"GAS" (eso es el modo
        consola): imprime lineas verbose tipo "  86.17s  brake  @ ...". El
        color se decide tambien por esa palabra, que es lo que de verdad
        llega al registro con el audio puesto."""
        s = msg.strip()
        if s.startswith("[voz]") or " voz " in s:
            return "voice"
        if s.startswith("(omitido"):
            return "faint"
        if s.startswith("MEDIO GAS") or " manage " in s:
            return "manage"
        if s.startswith("FRENA") or " brake " in s:
            return "brake"
        if s.startswith("SUELTA") or " lift " in s:
            return "lift"
        if s.startswith("GAS") or " throttle " in s:
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
        self._stop_overlay()
        self.root.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    CoachGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
