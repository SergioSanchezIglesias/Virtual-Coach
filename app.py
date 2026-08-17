#!/usr/bin/env python3
"""
app.py — Punto de entrada unico para el ejecutable empaquetado.

Un solo binario hace de GUI, coach y analyzer segun el primer argumento. Lo
necesita PyInstaller: dentro de un .exe no hay un `python` suelto ni los `.py`
sueltos, asi que la GUI no puede lanzar "python coach.py". En su lugar la GUI
lanza el PROPIO ejecutable con "coach"/"analyzer" delante, y este despachador lo
enruta al modulo correcto. En desarrollo funciona igual: `python app.py coach ...`.

    app.py               -> abre la GUI
    app.py coach ...     -> ejecuta coach.main() con el resto de argumentos
    app.py analyzer ...  -> ejecuta analyzer.main() con el resto de argumentos
    app.py overlay ...   -> ejecuta overlay.main() (clasificacion encima del juego)
"""
import sys
from pathlib import Path

LOG = "VirtualCoach-error.log"


def _base_dir() -> Path:
    """La carpeta del ejecutable (o del proyecto, en desarrollo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _reportar(exc: BaseException) -> None:
    """Deja constancia de un fallo de arranque.

    El .exe se construye con console=False (es una GUI, no queremos una
    ventana negra detras). El precio es que si algo revienta al arrancar,
    Windows no ensena NADA: la app "no se abre" y no hay forma de saber por
    que. Asi que el fallo se escribe a un fichero junto al ejecutable y, si
    Tk responde, se ensena en una ventana.
    """
    import traceback

    detalle = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        (_base_dir() / LOG).write_text(detalle, encoding="utf-8")
        donde = str(_base_dir() / LOG)
    except OSError:  # carpeta de solo lectura (Archivos de programa)
        import tempfile
        destino = Path(tempfile.gettempdir()) / LOG
        destino.write_text(detalle, encoding="utf-8")
        donde = str(destino)

    try:
        import tkinter as tk
        from tkinter import messagebox
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(
            "Virtual Coach",
            f"La aplicacion no pudo arrancar.\n\n{type(exc).__name__}: {exc}"
            f"\n\nDetalle completo en:\n{donde}",
        )
        raiz.destroy()
    except Exception:  # si ni Tk arranca, al menos queda el fichero
        pass


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "coach":
        sys.argv = ["coach", *args[1:]]
        import coach
        coach.main()
    elif args and args[0] == "analyzer":
        sys.argv = ["analyzer", *args[1:]]
        import analyzer
        analyzer.main()
    elif args and args[0] == "overlay":
        sys.argv = ["overlay", *args[1:]]
        import overlay
        overlay.main()
    else:
        # Solo la GUI: el coach y el analyzer corren como subproceso con su
        # salida enganchada al registro de la ventana, ahi ya se ve todo.
        try:
            import gui
            gui.main()
        except Exception as exc:
            _reportar(exc)
            raise


if __name__ == "__main__":
    main()
