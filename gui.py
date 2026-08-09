#!/usr/bin/env python3
"""
gui.py — Ventana minima para no teclear comandos.

Eliges la vuelta de referencia (CSV de Garage61), la procesa sola y lanza el
coach. Nada mas. El objetivo es quitarte el copiar-y-pegar de rutas y el tener
que recordar los flags.

Decision de arquitectura: esta ventana NO conoce la logica del coach. Lanza
analyzer.py y coach.py como procesos APARTE, con los mismos comandos que se
teclearian a mano. El core validado en pista no se importa ni se toca: la GUI
solo lo orquesta desde fuera. Es lo que permite que un bug en la ventana nunca
pueda tumbar el coach, y lo que mantiene la separacion del proyecto intacta.

    python gui.py
"""

from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

HERE = Path(__file__).resolve().parent

# Windows: evita que cada subproceso abra una ventana de consola negra.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _tool_cmd(tool: str) -> list[str]:
    """Comando base para invocar analyzer/coach, empaquetado o en desarrollo.

    Empaquetado (PyInstaller): el propio ejecutable se llama a si mismo con el
    nombre de la herramienta ("VirtualCoach.exe coach ..."). En desarrollo:
    "python app.py coach ...". Asi no hace falta un python ni los .py sueltos.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, tool]
    return [sys.executable, str(HERE / "app.py"), tool]

# Parametros de aviso por defecto, afinados al oido en pista.
COUNTDOWN = "3"
COUNTDOWN_INTERVAL = "0.75"


class CoachGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.csv: Path | None = None        # CSV de referencia elegido
        self.reference: Path | None = None   # JSON que genera analyzer
        self.coach_proc: subprocess.Popen | None = None

        root.title("Virtual Coach")
        root.minsize(560, 420)

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        # --- Paso 1: la referencia -----------------------------------------
        ttk.Label(frm, text="1 · Vuelta de referencia", font=("", 13, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.pick_btn = ttk.Button(
            frm, text="Elegir CSV de Garage61…", command=self.pick_reference
        )
        self.pick_btn.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        self.ref_lbl = ttk.Label(frm, text="Ninguna cargada", foreground="gray")
        self.ref_lbl.grid(row=2, column=0, sticky="w", pady=(0, 10))

        # --- Paso 2: rodar -------------------------------------------------
        ttk.Label(frm, text="2 · Coach", font=("", 13, "bold")).grid(
            row=3, column=0, sticky="w"
        )
        self.replay_var = tk.BooleanVar(value=False)
        self.replay_chk = ttk.Checkbutton(
            frm,
            text="Modo prueba: reproducir el CSV en vez de leer iRacing",
            variable=self.replay_var,
        )
        self.replay_chk.grid(row=4, column=0, sticky="w", pady=(4, 2))

        self.voice_var = tk.BooleanVar(value=True)
        self.voice_chk = ttk.Checkbutton(
            frm,
            text="Voz: \"Frena, 40%, tercera\" antes de cada aviso",
            variable=self.voice_var,
            command=self._sync_training,
        )
        self.voice_chk.grid(row=5, column=0, sticky="w", pady=(0, 2))

        # Entrenamiento: CUELGA de la voz. Si no hay frase, no hay donde meter
        # la correccion (un pitido no puede decirte "suave"), asi que al apagar
        # la voz esta casilla se apaga y se pone en gris. Nada de casillas que
        # parecen hacer algo y no hacen nada.
        self.training_var = tk.BooleanVar(value=False)
        self.training_chk = ttk.Checkbutton(
            frm,
            text="   └ Entrenamiento: corrige la curva que peor te sale "
                 "(\"…tercera, suave\")",
            variable=self.training_var,
        )
        self.training_chk.grid(row=6, column=0, sticky="w", pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self.start_btn = ttk.Button(
            btns, text="▶  Empezar", command=self.start_coach, state="disabled"
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_btn = ttk.Button(
            btns, text="■  Parar", command=self.stop_coach, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- Registro de salida --------------------------------------------
        self.log_box = scrolledtext.ScrolledText(
            frm, height=12, state="disabled", wrap="word", font=("Menlo", 11)
        )
        self.log_box.grid(row=8, column=0, sticky="nsew")
        frm.rowconfigure(8, weight=1)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Elige una vuelta de referencia para empezar.")

    def _sync_training(self) -> None:
        """La casilla de entrenamiento sigue a la de voz.

        Sin frase no hay donde meter la correccion: un pitido no puede decirte
        "suave". Asi que al apagar la voz, esta casilla se apaga y se agrisa.
        """
        if self.voice_var.get():
            self.training_chk.config(state="normal")
        else:
            self.training_var.set(False)
            self.training_chk.config(state="disabled")

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

        self.log(f"\nProcesando {csv.name}…")
        cmd = _tool_cmd("analyzer") + [str(csv), "--track", track, "-o", str(out)]
        # Sincrono a proposito: analyzer tarda <1 s y necesitamos su resultado
        # antes de dejar rodar. El parpadeo de la ventana es imperceptible.
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=CREATE_NO_WINDOW)
        self.log(result.stdout.strip())
        if result.returncode != 0 or not out.exists():
            self.log(f"[!] No se pudo procesar: {result.stderr.strip()}")
            return

        self.csv = csv
        self.reference = out
        self.ref_lbl.config(text=f"✓ {track}", foreground="green")
        self.start_btn.config(state="normal")

    # -----------------------------------------------------------------------
    # Paso 2: el coach (loop infinito + audio, va como proceso aparte)
    # -----------------------------------------------------------------------
    def start_coach(self) -> None:
        if self.reference is None or self.coach_proc is not None:
            return

        cmd = _tool_cmd("coach") + [
            str(self.reference),
            "--countdown", COUNTDOWN, "--countdown-interval", COUNTDOWN_INTERVAL,
        ]
        if self.replay_var.get() and self.csv is not None:
            cmd += ["--replay", str(self.csv)]
        if self.voice_var.get():
            cmd += ["--voice"]
            if self.training_var.get():
                cmd += ["--training"]

        modo = "prueba (replay)" if self.replay_var.get() else "iRacing en vivo"
        self.log(f"\n▶  Arrancando coach — modo {modo}…")

        self.coach_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
        )
        # Su salida se lee en un hilo y se vuelca al registro con root.after,
        # que es la unica forma segura de tocar widgets desde otro hilo en Tk.
        threading.Thread(target=self._pump_output, daemon=True).start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.pick_btn.config(state="disabled")
        self.replay_chk.config(state="disabled")
        self.voice_chk.config(state="disabled")
        self.training_chk.config(state="disabled")

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
        self.log("■  Coach detenido.")
        self.stop_btn.config(state="disabled")
        self.pick_btn.config(state="normal")
        self.replay_chk.config(state="normal")
        self.voice_chk.config(state="normal")
        self._sync_training()
        self.start_btn.config(state="normal" if self.reference else "disabled")

    # -----------------------------------------------------------------------
    def log(self, msg: str) -> None:
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def on_close(self) -> None:
        # No dejar un coach huerfano sonando tras cerrar la ventana.
        if self.coach_proc is not None and self.coach_proc.poll() is None:
            self.coach_proc.terminate()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CoachGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
