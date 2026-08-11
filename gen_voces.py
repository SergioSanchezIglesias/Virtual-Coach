#!/usr/bin/env python3
"""
gen_voces.py — Genera los clips de voz del coach, UNA vez.

Usa voces NEURONALES de Microsoft (edge-tts) — las mismas de Windows/Edge, en
espanol de Espana, casi humanas. Genera un MP3 por palabra, lo decodifica con
miniaudio (no hace falta ffmpeg) y lo guarda como WAV mono 16-bit a 44100 Hz.

Los WAV se versionan: en Windows solo se REPRODUCEN, sin edge-tts ni internet.
Solo hace falta internet para REGENERAR (este script llama al servicio de voz).

    pip install edge-tts miniaudio
    python gen_voces.py

Voces alternativas (es-ES): AlvaroNeural (h), ElviraNeural (m). Ver todas:
    edge-tts --list-voices | grep es-
"""
import subprocess
import wave
from pathlib import Path

import miniaudio
import numpy as np

VOZ = "es-ES-AlvaroNeural"  # masculina, Espana, neuronal
SR = 44100
OUT = Path(__file__).resolve().parent / "voces"

# Velocidad del habla. La voz por defecto de edge-tts va deprisa: probando en
# pista costaba entenderla con el ruido del coche encima. Se genera mas lenta.
#
# No es gratis: una voz mas lenta dura mas, y la frase tiene que caber ANTES de
# la curva (voz + cuenta atras + antelacion). En Hockenheim y Winton ya hay
# curvas donde la frase arranca antes de pasar la anterior (-36 m y -64 m
# medidos); esto lo agrava un poco. Se sostiene porque el motor de audio SUMA
# los sonidos en vez de cortarlos. Si algun dia estorba, las palancas son
# acortar la cuenta atras o la propia frase, no volver a acelerar la voz.
RATE = "-15%"

# nombre de fichero -> texto a pronunciar
CLIPS = {
    "frena": "Frena",
    "suelta": "Suelta",
    "mediogas": "Medio gas",
    "p20": "veinte", "p40": "cuarenta", "p60": "sesenta",
    "p80": "ochenta", "p100": "cien",
    "g1": "primera", "g2": "segunda", "g3": "tercera",
    "g4": "cuarta", "g5": "quinta", "g6": "sexta",
    # Modo entrenamiento: la correccion de la vuelta anterior. Son ORDENES,
    # no reproches. "Suave" se puede obedecer sin pensar; "aqui te pasaste"
    # solo te mete duda tres segundos antes de frenar, y la duda cuesta mas
    # tiempo que el error que intenta corregir.
    "suave": "suave",
    "aprieta": "aprieta",
}


def trim_silence(samples: np.ndarray, thresh: int = 200,
                 pad_ms: int = 30) -> np.ndarray:
    """Recorta el silencio inicial y final (edge-tts mete relleno generoso).

    Deja un pequeno margen (pad_ms) para no cortar en seco el ataque/caida.
    """
    loud = np.where(np.abs(samples) > thresh)[0]
    if len(loud) == 0:
        return samples
    pad = int(SR * pad_ms / 1000)
    a = max(0, loud[0] - pad)
    b = min(len(samples), loud[-1] + pad)
    return samples[a:b]


def synth(text: str, wav_path: Path, rate: str = RATE) -> None:
    """Sintetiza `text` a un WAV mono 16-bit 44100 con voz neuronal."""
    import sys

    mp3 = wav_path.with_suffix(".mp3")
    # Se invoca como modulo del MISMO Python que corre este script. Llamar al
    # comando "edge-tts" a secas falla si el venv no esta activado: el binario
    # vive dentro de .venv/bin y no esta en el PATH.
    # OJO con --rate: el valor empieza por guion ("-15%") y separado en dos
    # argumentos argparse lo toma por otro flag y falla. Va pegado con "=".
    subprocess.run(
        [sys.executable, "-m", "edge_tts", "--voice", VOZ, f"--rate={rate}",
         "--text", text, "--write-media", str(mp3)],
        check=True, capture_output=True,
    )
    dec = miniaudio.decode_file(str(mp3), nchannels=1, sample_rate=SR)
    samples = trim_silence(np.array(dec.samples, dtype=np.int16))
    with wave.open(str(wav_path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())
    mp3.unlink()  # el MP3 era temporal


def main() -> None:
    import sys

    # Por defecto solo se generan los que faltan. Los clips existentes estan
    # versionados y validados al oido: regenerarlos por accidente al anadir una
    # palabra nueva cambiaria sin querer lo que ya suena bien.
    forzar = "--force" in sys.argv
    rate = RATE
    for arg in sys.argv[1:]:
        if arg.startswith("--rate="):
            rate = arg.split("=", 1)[1]

    OUT.mkdir(exist_ok=True)
    nuevos = 0
    for name, text in CLIPS.items():
        destino = OUT / f"{name}.wav"
        if destino.exists() and not forzar:
            continue
        synth(text, destino, rate)
        nuevos += 1
        print(f"  {name:10} <- \"{text}\"")

    if not nuevos:
        print("Nada que generar: estan todos. Usa --force para rehacerlos.")
    print(f"\n{len(CLIPS)} clips ({VOZ}, velocidad {rate}) en {OUT}/")


if __name__ == "__main__":
    main()
