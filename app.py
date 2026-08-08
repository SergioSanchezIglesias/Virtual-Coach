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
"""
import sys


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
    else:
        import gui
        gui.main()


if __name__ == "__main__":
    main()
