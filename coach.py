#!/usr/bin/env python3
"""
coach.py — El coach en vivo: posicion -> ¿toca aviso? -> pitido.

Uso en el Mac (sin iRacing, reproduciendo un CSV):
    python coach.py ref_hockenheim.json --replay vuelta.csv --console

Uso en el PC de juego (iRacing abierto y en pista):
    python coach.py ref_hockenheim.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import wave
from pathlib import Path

import numpy as np

from source import make_source

SR = 44100  # frecuencia de muestreo del audio

# Voz: clips pregenerados (ver gen_voces.py). El coach los concatena en RAM.
VOCES_DIR = Path(__file__).resolve().parent / "voces"
VOICE_GAP = 0.30  # segundos de colchon entre el fin de la voz y el primer tick
CLIP_NAMES = ("frena", "suelta", "p20", "p40", "p60", "p80", "p100",
              "g1", "g2", "g3", "g4", "g5", "g6")


def load_wav(path: Path) -> np.ndarray:
    """Carga un WAV PCM 16-bit mono a float32 [-1, 1]. Solo stdlib."""
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def make_tone(freq: float, ms: int, volume: float = 0.35) -> np.ndarray:
    """Genera un tono con envolvente suave.

    La envolvente no es estetica: un seno que arranca y corta en seco produce
    un click audible en cada aviso, y a 12 avisos por vuelta acabas odiando
    el programa.
    """
    n = int(SR * ms / 1000)
    t = np.arange(n) / SR
    wave = np.sin(2 * math.pi * freq * t)

    edge = int(SR * 0.006)  # 6 ms de ataque y de caida
    env = np.ones(n)
    env[:edge] = np.linspace(0, 1, edge)
    env[-edge:] = np.linspace(1, 0, edge)

    return (wave * env * volume).astype(np.float32)


class AudioEngine:
    """Reproductor de latencia minima.

    Mantiene UN stream abierto durante toda la sesion y los tonos
    pregenerados en RAM. Abrir un stream o cargar un fichero en cada aviso
    mete decenas de milisegundos justo donde no te los puedes permitir.
    """

    def __init__(self, blocksize: int = 128):
        import sounddevice as sd  # import tardio: el modo consola no lo necesita

        self._buf: np.ndarray | None = None
        self._idx = 0

        def callback(outdata, frames, time_info, status):
            outdata.fill(0)
            if self._buf is None:
                return
            chunk = self._buf[self._idx : self._idx + frames]
            outdata[: len(chunk), 0] = chunk
            self._idx += len(chunk)
            if self._idx >= len(self._buf):
                self._buf = None

        self.stream = sd.OutputStream(
            samplerate=SR,
            channels=1,
            blocksize=blocksize,
            dtype="float32",
            callback=callback,
        )
        self.stream.start()
        self.latency_ms = self.stream.latency * 1000

    def play(self, tone: np.ndarray):
        self._buf = tone
        self._idx = 0

    def close(self):
        self.stream.stop()
        self.stream.close()


class ConsoleEngine:
    """Sustituto sin sonido. Para desarrollar en una maquina sin audio,
    para tests, y para ver los avisos escritos mientras afinas umbrales."""

    latency_ms = 0.0

    def __init__(self, labels: dict):
        self.labels = labels

    def play(self, tone):
        print(tone, flush=True)

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Logica del coach
# ---------------------------------------------------------------------------


class Coach:
    def __init__(self, reference: dict, engine, cfg):
        self.track_length = reference["track_length_m"]
        self.events = sorted(reference["events"], key=lambda e: e["pos"])
        self.engine = engine
        self.cfg = cfg
        self.fired: set[tuple[int, int]] = set()
        self.last_pos = 0.0

        console = isinstance(engine, ConsoleEngine)
        self.tones = {
            "brake": "FRENA" if console else make_tone(cfg.brake_freq, cfg.beep_ms),
            "throttle": "GAS  "
            if console
            else make_tone(cfg.throttle_freq, cfg.beep_ms),
            # El tick de cuenta atras es el MISMO tono del freno, pero corto y
            # bajito. Asi se lee como "esto que viene es una frenada" y no
            # como un aviso distinto que hay que aprender aparte.
            "count": "  ."
            if console
            else make_tone(cfg.brake_freq, cfg.count_ms, volume=cfg.count_volume),
            # Lift = levantar sin frenar. Tono propio, entre el grave del freno
            # y el agudo del gas, para que no se confunda con ninguno.
            "lift": "SUELTA"
            if console
            else make_tone(cfg.lift_freq, cfg.beep_ms),
        }

        # --- Voz (opcional): frase de preparacion antes de cada frenada/lift ---
        self.voice = getattr(cfg, "voice", False)
        if self.voice:
            clips = {} if console else {
                n: load_wav(VOCES_DIR / f"{n}.wav") for n in CLIP_NAMES
            }
            for ev in self.events:
                if console:
                    ev["_voice"] = self._voice_text(ev)
                    ev["_voice_dur"] = 1.6 if ev["_voice"] else 0.0
                else:
                    buf = self._voice_buffer(ev, clips)
                    ev["_voice"] = buf
                    ev["_voice_dur"] = len(buf) / SR if buf is not None else 0.0

    @staticmethod
    def _pct_clip(peak: float) -> str:
        """Redondea el pico de freno a un tramo de 20 % -> nombre de clip."""
        tramo = max(1, min(5, round(peak * 5)))
        return f"p{tramo * 20}"

    def _voice_buffer(self, ev, clips):
        """Concatena los clips de una frase: 'frena' + tramo% + marcha."""
        if ev["type"] == "brake":
            parts = [clips["frena"], clips[self._pct_clip(ev.get("peak", 1.0))]]
            g = ev.get("gear")
            if g and 1 <= g <= 6:
                parts.append(clips[f"g{g}"])
        elif ev["type"] == "lift":
            parts = [clips["suelta"]]
        else:
            return None
        gap = np.zeros(int(SR * 0.04), dtype=np.float32)  # 40 ms entre palabras
        buf = parts[0]
        for p in parts[1:]:
            buf = np.concatenate([buf, gap, p])
        return buf

    def _voice_text(self, ev):
        """La misma frase, en texto, para el modo consola."""
        if ev["type"] == "brake":
            parts = ["Frena", f"{self._pct_clip(ev.get('peak', 1.0))[1:]}%"]
            g = ev.get("gear")
            if g and 1 <= g <= 6:
                parts.append(f"{g}a")
            return "[voz] " + ", ".join(parts)
        if ev["type"] == "lift":
            return "[voz] Suelta"
        return None

    def gap_to(self, event_pos: float, pos: float) -> float:
        """Metros que faltan hasta el evento, resolviendo el paso por meta."""
        delta = event_pos - pos
        if delta < -0.5:  # el evento esta pasada la linea de meta
            delta += 1.0
        return delta * self.track_length

    def on_frame(self, f) -> None:
        # Vuelta nueva: se rearman todos los avisos.
        if f.lap_pos < self.last_pos - 0.5:
            self.fired.clear()
        self.last_pos = f.lap_pos

        if not f.on_track or f.speed_ms < 5.0:
            return

        # Todo se razona en SEGUNDOS hasta el evento, no en metros. A 250 km/h
        # recorres 24 metros en el mismo tiempo que 8 metros a 80 km/h: un
        # offset fijo en metros seria correcto en una curva y absurdo en las
        # demas. El margen de seguridad si va en metros y se convierte aqui.
        lead = self.cfg.lead + self.cfg.margin / max(f.speed_ms, 1.0)

        for i, ev in enumerate(self.events):
            gap = self.gap_to(ev["pos"], f.lap_pos)
            if gap < 0:
                continue
            ttc = gap / max(f.speed_ms, 1.0)

            # Solo las frenadas llevan cuenta atras. El aviso de gas es un
            # "ya puedes", no algo para lo que haga falta prepararse.
            n_ticks = self.cfg.countdown if ev["type"] == "brake" else 0

            # Voz de preparacion: suena ANTES de la cuenta atras, con antelacion
            # suficiente para terminar antes del primer tick. La voz dice "que"
            # viene; los ticks el "cuando"; el pitido el "ahora".
            if self.voice and ev.get("_voice") is not None:
                if (i, -1) not in self.fired:
                    voice_lead = (lead + n_ticks * self.cfg.countdown_interval
                                  + ev["_voice_dur"] + VOICE_GAP)
                    if ttc <= voice_lead:
                        self.fired.add((i, -1))
                        self.engine.play(ev["_voice"])

            # Se recorre de k mas alto (el tick mas temprano) a k = 0, que es
            # el aviso de verdad.
            for k in range(n_ticks, -1, -1):
                if (i, k) in self.fired:
                    continue
                if ttc > lead + k * self.cfg.countdown_interval:
                    continue

                self.fired.add((i, k))

                if k > 0:
                    self.engine.play(self.tones["count"])
                    break

                # ¿Llego a este punto a una velocidad comparable a la
                # referencia? Si no, el punto de frenada del otro piloto no
                # es aplicable al mio, y avisar seria peor que callarse.
                ref_v = ev.get("speed_ms", f.speed_ms)
                mismatch = abs(f.speed_ms - ref_v) / max(ref_v, 1.0)
                flag = ""
                if mismatch > self.cfg.speed_tol:
                    flag = f"  [!] {(f.speed_ms - ref_v) * 3.6:+.0f} km/h vs referencia"
                    if self.cfg.skip_mismatch:
                        print(
                            f"      (omitido {ev['type']} @ {ev['pos'] * 100:.2f}%){flag}"
                        )
                        break

                self.engine.play(self.tones[ev["type"]])
                if self.cfg.verbose:
                    print(
                        f"{f.t:7.2f}s  {ev['type']:<8} @ {ev['pos'] * 100:6.2f}%  "
                        f"aviso {gap:5.1f} m antes  v={f.speed_ms * 3.6:3.0f} km/h{flag}"
                    )
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", help="JSON generado por analyzer.py")
    ap.add_argument("--replay", help="CSV a reproducir en lugar de leer iRacing")
    ap.add_argument(
        "--replay-speed",
        type=float,
        default=1.0,
        help="1.0 = tiempo real, 5.0 = cinco veces mas rapido",
    )
    ap.add_argument(
        "--laps",
        type=int,
        default=None,
        help="parar tras N vueltas de replay (por defecto, bucle infinito)",
    )
    ap.add_argument(
        "--console", action="store_true", help="imprimir los avisos en vez de sonarlos"
    )
    ap.add_argument(
        "--lead", type=float, default=0.35, help="segundos de antelacion del aviso"
    )
    ap.add_argument(
        "--margin",
        type=float,
        default=0.0,
        help="metros extra de antelacion (margen de seguridad)",
    )
    ap.add_argument(
        "--speed-tol",
        type=float,
        default=0.10,
        help="desviacion de velocidad tolerada frente a la referencia",
    )
    ap.add_argument(
        "--skip-mismatch",
        action="store_true",
        help="callar el aviso si la velocidad se desvia demasiado",
    )
    ap.add_argument(
        "--countdown",
        type=int,
        default=0,
        help="ticks de preparacion antes de cada frenada (0 = ninguno)",
    )
    ap.add_argument(
        "--countdown-interval",
        type=float,
        default=0.25,
        help="segundos entre ticks de la cuenta atras",
    )
    ap.add_argument("--count-ms", type=int, default=45)
    ap.add_argument("--count-volume", type=float, default=0.20)
    ap.add_argument("--brake-freq", type=float, default=620.0)
    ap.add_argument("--throttle-freq", type=float, default=1050.0)
    ap.add_argument("--lift-freq", type=float, default=820.0)
    ap.add_argument(
        "--voice", action="store_true",
        help="voz de preparacion antes de cada frenada/lift (ademas de los pitidos)",
    )
    ap.add_argument("--beep-ms", type=int, default=90)
    ap.add_argument("-q", "--quiet", dest="verbose", action="store_false")
    cfg = ap.parse_args()

    with open(cfg.reference, encoding="utf-8") as fh:
        reference = json.load(fh)

    if cfg.console:
        engine = ConsoleEngine({})
    else:
        try:
            engine = AudioEngine()
            print(f"Audio listo. Latencia de salida: {engine.latency_ms:.1f} ms")
        except Exception as exc:
            print(f"No hay audio disponible ({type(exc).__name__}). Modo consola.")
            engine = ConsoleEngine({})

    print(
        f"Referencia: {reference['track']} / {reference['car']} "
        f"({len(reference['events'])} avisos por vuelta)"
    )
    cuenta = (
        f", cuenta atras de {cfg.countdown} ticks cada {cfg.countdown_interval:.2f} s"
        if cfg.countdown
        else ""
    )
    print(f"Antelacion: {cfg.lead:.2f} s + {cfg.margin:.0f} m{cuenta}\n")

    coach = Coach(reference, engine, cfg)

    try:
        with make_source(cfg.replay, cfg.replay_speed, cfg.laps) as src:
            for frame in src.frames():
                coach.on_frame(frame)
        print("\nReplay terminado.")
    except KeyboardInterrupt:
        print("\nFin.")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
