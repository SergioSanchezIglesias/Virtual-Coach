#!/usr/bin/env python3
"""
gen_voces.py — Genera los clips de voz del coach, UNA vez, en el Mac.

Usa `say` (nativo de macOS) para sintetizar palabras sueltas a WAV. El coach
las concatena en RAM ("frena" + "cuarenta" + "tercera") en tiempo de ejecucion.
Los WAV se versionan: en Windows solo se REPRODUCEN, no hace falta ningun motor
de voz ni dependencia. Regenera todo con:

    python gen_voces.py

Clips atomicos, no frases compuestas: asi 13 ficheros cubren cualquier
combinacion de tramo% y marcha, y cambiar el formato no obliga a regenerar
decenas de clips.
"""
import subprocess
from pathlib import Path

# Nombre COMPLETO con locale: "Eddy" a secas existe en 14 idiomas y `say`
# elegiria cualquiera. Este formato (el que lista `say -v '?'`) fuerza es_ES.
VOZ = "Eddy (Español (España))"
OUT = Path(__file__).resolve().parent / "voces"

# nombre de fichero -> texto a pronunciar
CLIPS = {
    "frena": "Frena",
    "suelta": "Suelta",
    "mediogas": "Medio gas",
    # tramos de freno (%)
    "p20": "veinte", "p40": "cuarenta", "p60": "sesenta",
    "p80": "ochenta", "p100": "cien",
    # marchas
    "g1": "primera", "g2": "segunda", "g3": "tercera",
    "g4": "cuarta", "g5": "quinta", "g6": "sexta",
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in CLIPS.items():
        path = OUT / f"{name}.wav"
        subprocess.run(
            ["say", "-v", VOZ, "-o", str(path),
             "--data-format=LEI16@44100", text],
            check=True,
        )
        print(f"  {path.name:10} <- \"{text}\"")
    print(f"\n{len(CLIPS)} clips en {OUT}/")


if __name__ == "__main__":
    main()
