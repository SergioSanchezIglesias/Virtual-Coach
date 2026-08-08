#!/usr/bin/env python3
"""
source.py — La UNICA parte del proyecto que sabe de donde salen los datos.

Dos implementaciones:

  ReplaySource  — reproduce un CSV de Garage61 como si fuese el simulador
                  en vivo. Funciona en cualquier sistema operativo. Es lo
                  que te permite desarrollar el 90% del coach en el Mac.

  IRacingSource — lee la memoria compartida de iRacing. Solo Windows, y
                  solo con el juego abierto.

Todo lo demas del programa consume Frame y no sabe cual de las dos esta
detras. Si algun dia hay que tocar iRacing, se toca aqui y en ningun otro
sitio.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

SAMPLE_RATE = 60.0


@dataclass(frozen=True)
class Frame:
    """Un instante de telemetria, en unidades normalizadas."""
    t: float           # segundos desde que arranco la fuente
    lap_pos: float     # 0.0 - 1.0 sobre la vuelta
    speed_ms: float    # metros por segundo
    brake: float       # 0.0 - 1.0
    throttle: float    # 0.0 - 1.0
    gear: int
    lap: int
    on_track: bool


class TelemetrySource:
    """Interfaz comun. Se itera y va soltando Frames."""

    def frames(self):
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Reproduccion de CSV — el caballo de batalla del desarrollo
# ---------------------------------------------------------------------------

class ReplaySource(TelemetrySource):
    """Convierte un CSV de Garage61 en un flujo temporizado de Frames.

    El CSV es literalmente una grabacion del mismo flujo que produce iRacing,
    a la misma frecuencia y en las mismas unidades. Para el resto del
    programa es indistinguible del simulador.

    speed=1.0 reproduce a tiempo real; speed=5.0 va cinco veces mas rapido,
    que es como quieres iterar cuando estas depurando; speed=0 va tan rapido
    como pueda la maquina, para tests automaticos.
    """

    def __init__(self, csv_path: str, speed: float = 1.0, loop: bool = True):
        df = pd.read_csv(csv_path)
        self.pos = df["LapDistPct"].to_numpy()
        self.speed_ms = df["Speed"].to_numpy()
        self.brake = df["Brake"].to_numpy().clip(0.0, 1.0)
        self.throttle = df["Throttle"].to_numpy().clip(0.0, 1.0)
        self.gear = df["Gear"].to_numpy().astype(int)
        self.rate = speed
        self.loop = loop
        self.n = len(df)

    def frames(self):
        dt = 1.0 / SAMPLE_RATE
        t0 = time.perf_counter()
        lap = 0
        i = 0
        emitted = 0

        while True:
            if self.rate > 0:
                target = t0 + (emitted * dt) / self.rate
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

            yield Frame(
                t=emitted * dt,
                lap_pos=float(self.pos[i]),
                speed_ms=float(self.speed_ms[i]),
                brake=float(self.brake[i]),
                throttle=float(self.throttle[i]),
                gear=int(self.gear[i]),
                lap=lap,
                on_track=True,
            )

            emitted += 1
            i += 1
            if i >= self.n:
                if not self.loop:
                    return
                i = 0
                lap += 1


# ---------------------------------------------------------------------------
# iRacing en vivo — solo Windows
# ---------------------------------------------------------------------------

class IRacingSource(TelemetrySource):
    """Lee la memoria compartida de iRacing via pyirsdk.

    OJO: esta clase es la unica que NO se puede probar fuera del PC de
    juego. Todo lo que hay debajo de Frame si.
    """

    def __init__(self, poll_hz: float = 120.0):
        try:
            import irsdk
        except Exception as exc:  # ImportError en Mac/Linux, ValueError en algunos casos
            raise SystemExit(
                "pyirsdk solo funciona en Windows con iRacing instalado.\n"
                "Para desarrollar en Mac usa --replay con un CSV.\n"
                f"({type(exc).__name__}: {exc})"
            )

        self._irsdk = irsdk
        self.ir = irsdk.IRSDK()
        self.poll_interval = 1.0 / poll_hz

        if not self.ir.startup():
            raise SystemExit("No se encuentra iRacing. Arranca el juego y entra en sesion.")

    def session_id(self) -> tuple[str, str]:
        """Devuelve (circuito, coche) para elegir el fichero de referencia."""
        weekend = self.ir["WeekendInfo"] or {}
        drivers = (self.ir["DriverInfo"] or {}).get("Drivers", [])
        idx = (self.ir["DriverInfo"] or {}).get("DriverCarIdx", 0)
        car = drivers[idx].get("CarPath", "unknown") if drivers else "unknown"
        track = weekend.get("TrackName", "unknown")
        return str(track), str(car)

    def frames(self):
        t0 = time.perf_counter()
        last_tick = -1

        while True:
            if not self.ir.is_connected:
                time.sleep(0.5)
                continue

            # Congela el buffer para que todos los canales de este Frame
            # correspondan al mismo instante y no a instantes distintos.
            self.ir.freeze_var_buffer_latest()
            tick = self.ir["SessionTick"]

            if tick is not None and tick != last_tick:
                last_tick = tick
                yield Frame(
                    t=time.perf_counter() - t0,
                    lap_pos=float(self.ir["LapDistPct"] or 0.0),
                    speed_ms=float(self.ir["Speed"] or 0.0),
                    brake=float(self.ir["Brake"] or 0.0),
                    throttle=float(self.ir["Throttle"] or 0.0),
                    gear=int(self.ir["Gear"] or 0),
                    lap=int(self.ir["Lap"] or 0),
                    on_track=bool(self.ir["IsOnTrack"]) and not bool(self.ir["OnPitRoad"]),
                )

            self.ir.unfreeze_var_buffer_latest()
            time.sleep(self.poll_interval)

    def close(self):
        try:
            self.ir.shutdown()
        except Exception:
            pass


def make_source(replay: str | None, speed: float = 1.0) -> TelemetrySource:
    """Fabrica: CSV si se pasa --replay, iRacing en vivo si no."""
    if replay:
        return ReplaySource(replay, speed=speed)
    return IRacingSource()
