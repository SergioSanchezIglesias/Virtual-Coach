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

# nombre de fichero -> texto a pronunciar
CLIPS = {
    "frena": "Frena",
    "suelta": "Suelta",
    "mediogas": "Medio gas",
    "p20": "veinte", "p40": "cuarenta", "p60": "sesenta",
    "p80": "ochenta", "p100": "cien",
    "g1": "primera", "g2": "segunda", "g3": "tercera",
    "g4": "cuarta", "g5": "quinta", "g6": "sexta",
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


def synth(text: str, wav_path: Path) -> None:
    """Sintetiza `text` a un WAV mono 16-bit 44100 con voz neuronal."""
    mp3 = wav_path.with_suffix(".mp3")
    subprocess.run(
        ["edge-tts", "--voice", VOZ, "--text", text, "--write-media", str(mp3)],
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
    OUT.mkdir(exist_ok=True)
    for name, text in CLIPS.items():
        synth(text, OUT / f"{name}.wav")
        print(f"  {name:10} <- \"{text}\"")
    print(f"\n{len(CLIPS)} clips ({VOZ}) en {OUT}/")


if __name__ == "__main__":
    main()
