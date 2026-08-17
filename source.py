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

import json
import time
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

SAMPLE_RATE = 60.0


@dataclass(frozen=True)
class Frame:
    """Un instante de telemetria, en unidades normalizadas."""

    t: float  # segundos desde que arranco la fuente
    lap_pos: float  # 0.0 - 1.0 sobre la vuelta
    speed_ms: float  # metros por segundo
    brake: float  # 0.0 - 1.0
    throttle: float  # 0.0 - 1.0
    gear: int
    lap: int
    on_track: bool
    # El ABS trabajando = le has pedido al coche mas freno del que la goma da.
    # Solo lo usa el analisis POST-vuelta, nunca el aviso en vivo: un "¡ABS!"
    # mientras frenas es la peor distraccion posible y ademas llega tarde.
    abs_active: bool = False


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

    def __init__(self, csv_path: str, speed: float = 1.0, max_laps: int | None = None):
        df = pd.read_csv(csv_path)
        self.pos = df["LapDistPct"].to_numpy()
        self.speed_ms = df["Speed"].to_numpy()
        self.brake = df["Brake"].to_numpy().clip(0.0, 1.0)
        self.throttle = df["Throttle"].to_numpy().clip(0.0, 1.0)
        self.gear = df["Gear"].to_numpy().astype(int)
        # Un CSV viejo puede no traerlo; entonces es como si nunca saltase.
        if "ABSActive" in df.columns:
            self.abs_active = df["ABSActive"].to_numpy().astype(bool)
        else:
            self.abs_active = np.zeros(len(df), dtype=bool)
        self.rate = speed
        self.max_laps = max_laps
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
                abs_active=bool(self.abs_active[i]),
            )

            emitted += 1
            i += 1
            if i >= self.n:
                i = 0
                lap += 1
                if self.max_laps is not None and lap >= self.max_laps:
                    return


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
        except (
            Exception
        ) as exc:  # ImportError en Mac/Linux, ValueError en algunos casos
            raise SystemExit(
                "pyirsdk solo funciona en Windows con iRacing instalado.\n"
                "Para desarrollar en Mac usa --replay con un CSV.\n"
                f"({type(exc).__name__}: {exc})"
            )

        self._irsdk = irsdk
        self.ir = irsdk.IRSDK()
        self.poll_interval = 1.0 / poll_hz

        if not self.ir.startup():
            raise SystemExit(
                "No se encuentra iRacing. Arranca el juego y entra en sesion."
            )

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
                    on_track=bool(self.ir["IsOnTrack"])
                    and not bool(self.ir["OnPitRoad"]),
                    # PENDIENTE DE CONFIRMAR CON EL JUEGO ABIERTO: el nombre
                    # del canal. Si no acierta, el SDK devuelve None y esto se
                    # queda en False, que degrada bien (el analisis dira "sin
                    # ABS" en vez de romper). Comprobar con:
                    #     ir.var_headers_names  ->  buscar "ABS"
                    abs_active=bool(self.ir["BrakeABSactive"]),
                )

            self.ir.unfreeze_var_buffer_latest()
            time.sleep(self.poll_interval)

    def close(self):
        try:
            self.ir.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Segundo canal: la SESION (todos los coches), para el overlay de clasificacion
# ---------------------------------------------------------------------------
#
# Frame es TU coche a 60 Hz. La clasificacion necesita otra cosa: una foto de
# todos los coches unas pocas veces por segundo. Es un contrato distinto, con
# sus propias fuentes, pero vive aqui por la misma regla de siempre: este es
# el unico modulo que sabe de donde salen los datos. El overlay consume
# SessionSnapshot y no sabe si detras hay iRacing o un fichero grabado.
#
# El CSV de Garage61 no sirve de fixture para esto (solo trae tu coche), asi
# que la grabacion se hace con SessionRecorder en el PC de juego y se
# reproduce en el Mac con ReplaySessionSource. Mismo patron que ReplaySource.


@dataclass(frozen=True)
class CarState:
    """Un coche de la sesion en un instante."""

    idx: int  # CarIdx del SDK
    number: str
    name: str
    class_id: int
    class_name: str
    irating: int
    class_pos: int  # 1-based; 0 = sin posicion todavia
    pos: int  # posicion absoluta, 1-based; 0 = sin posicion
    lap: int
    lap_dist_pct: float
    f2_time: float  # segundos detras del lider ABSOLUTO (CarIdxF2Time)
    last_lap: float  # segundos; <= 0 = sin vuelta
    best_lap: float
    on_pit_road: bool
    in_world: bool  # ha estado en pista en esta sesion
    is_me: bool


@dataclass(frozen=True)
class SessionSnapshot:
    """Foto de la sesion: que sesion es, cuanto queda, y todos los coches."""

    t: float
    session_type: str  # "Race", "Practice", "Qualify", "Lone Qualify"...
    time_remain: float  # segundos; puede ser enorme si es "sin limite"
    laps_total: int  # 0 = sin limite de vueltas
    laps_done: int  # vueltas completadas por el lider
    session_num: int
    cars: tuple[CarState, ...]

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "SessionSnapshot":
        d = json.loads(line)
        cars = tuple(CarState(**c) for c in d.pop("cars"))
        return cls(cars=cars, **d)

    @property
    def me(self) -> CarState | None:
        for c in self.cars:
            if c.is_me:
                return c
        return None


class SessionSource:
    """Interfaz comun del segundo canal. Se itera y suelta SessionSnapshots."""

    def snapshots(self):
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SessionRecorder:
    """Vuelca snapshots a un JSONL (uno por linea) para reproducirlos luego.

    Es lo que convierte una carrera real en un fixture: se graba en el PC con
    el juego abierto y se reproduce en el Mac tantas veces como haga falta.
    """

    def __init__(self, path):
        self.path = path
        self._fh = open(path, "w", encoding="utf-8")

    def write(self, snap: SessionSnapshot) -> None:
        self._fh.write(snap.to_json() + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ReplaySessionSource(SessionSource):
    """Reproduce un JSONL grabado con SessionRecorder respetando sus tiempos.

    speed=1.0 tiempo real; speed=0 tan rapido como pueda (tests).
    """

    def __init__(self, path: str, speed: float = 1.0):
        with open(path, encoding="utf-8") as fh:
            self._snaps = [SessionSnapshot.from_json(l) for l in fh if l.strip()]
        self.rate = speed

    def snapshots(self):
        if not self._snaps:
            return
        t0 = time.perf_counter()
        base = self._snaps[0].t
        for snap in self._snaps:
            if self.rate > 0:
                delay = t0 + (snap.t - base) / self.rate - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            yield snap


class IRacingSessionSource(SessionSource):
    """Fotos de la sesion leidas de la memoria compartida de iRacing.

    Solo Windows. La lista de pilotos (DriverInfo) va en el YAML de sesion y
    cambia poco: se relee solo cuando el SDK dice que ha cambiado. Las
    posiciones, gaps y tiempos van en los arrays CarIdx*, que se leen en cada
    foto.
    """

    PACE_CAR = "safety pcfr500s"

    def __init__(self, hz: float = 2.0):
        try:
            import irsdk
        except Exception as exc:
            raise SystemExit(
                "pyirsdk solo funciona en Windows con iRacing instalado.\n"
                "Para desarrollar en Mac usa --replay con un JSONL grabado.\n"
                f"({type(exc).__name__}: {exc})"
            )
        self.ir = irsdk.IRSDK()
        self.interval = 1.0 / hz
        if not self.ir.startup():
            raise SystemExit(
                "No se encuentra iRacing. Arranca el juego y entra en sesion."
            )
        self._drivers: dict[int, dict] = {}
        self._drivers_version = None
        self._my_idx = -1

    def _refresh_drivers(self) -> None:
        version = self.ir["SessionInfoUpdate"]
        if version == self._drivers_version and self._drivers:
            return
        info = self.ir["DriverInfo"] or {}
        self._my_idx = int(info.get("DriverCarIdx", -1))
        self._drivers = {}
        for d in info.get("Drivers", []):
            if d.get("IsSpectator") or d.get("CarIsPaceCar"):
                continue
            self._drivers[int(d["CarIdx"])] = d
        self._drivers_version = version

    def _session_meta(self, num: int) -> tuple[str, int]:
        sessions = (self.ir["SessionInfo"] or {}).get("Sessions", [])
        for s in sessions:
            if int(s.get("SessionNum", -1)) == num:
                laps = s.get("SessionLaps", "unlimited")
                try:
                    laps_total = int(laps)
                except (TypeError, ValueError):
                    laps_total = 0
                return str(s.get("SessionType", "?")), laps_total
        return "?", 0

    def _read(self, name, idx, default=0):
        arr = self.ir[name]
        try:
            v = arr[idx]
        except (TypeError, IndexError):
            return default
        return default if v is None else v

    def snapshot(self, t: float) -> SessionSnapshot | None:
        if not self.ir.is_connected:
            return None
        self.ir.freeze_var_buffer_latest()
        try:
            self._refresh_drivers()
            num = int(self.ir["SessionNum"] or 0)
            stype, laps_total = self._session_meta(num)
            if laps_total >= 32767:
                laps_total = 0
            cars = []
            leader_laps = 0
            for idx, d in self._drivers.items():
                surface = self._read("CarIdxTrackSurface", idx, -1)
                lap = int(self._read("CarIdxLap", idx, -1))
                car = CarState(
                    idx=idx,
                    number=str(d.get("CarNumber", "?")),
                    name=str(d.get("UserName", "?")),
                    class_id=int(d.get("CarClassID", 0)),
                    class_name=str(d.get("CarClassShortName") or d.get("CarScreenNameShort") or ""),
                    irating=int(d.get("IRating", 0)),
                    class_pos=int(self._read("CarIdxClassPosition", idx)),
                    pos=int(self._read("CarIdxPosition", idx)),
                    lap=max(lap, 0),
                    lap_dist_pct=float(self._read("CarIdxLapDistPct", idx, 0.0)),
                    f2_time=float(self._read("CarIdxF2Time", idx, 0.0)),
                    last_lap=float(self._read("CarIdxLastLapTime", idx, -1.0)),
                    best_lap=float(self._read("CarIdxBestLapTime", idx, -1.0)),
                    on_pit_road=bool(self._read("CarIdxOnPitRoad", idx, False)),
                    in_world=surface != -1 or lap > 0,
                    is_me=idx == self._my_idx,
                )
                cars.append(car)
                if car.pos == 1:
                    leader_laps = max(car.lap - 1, 0)
            return SessionSnapshot(
                t=t,
                session_type=stype,
                time_remain=float(self.ir["SessionTimeRemain"] or 0.0),
                laps_total=laps_total,
                laps_done=leader_laps,
                session_num=num,
                cars=tuple(cars),
            )
        finally:
            self.ir.unfreeze_var_buffer_latest()

    def snapshots(self):
        t0 = time.perf_counter()
        while True:
            snap = self.snapshot(time.perf_counter() - t0)
            if snap is not None:
                yield snap
            time.sleep(self.interval)

    def close(self):
        try:
            self.ir.shutdown()
        except Exception:
            pass


def make_session_source(replay: str | None, speed: float = 1.0) -> SessionSource:
    """Fabrica del segundo canal: JSONL grabado si se pasa, iRacing en vivo si no."""
    if replay:
        return ReplaySessionSource(replay, speed=speed)
    return IRacingSessionSource()


def make_source(
    replay: str | None, speed: float = 1.0, max_laps: int | None = None
) -> TelemetrySource:
    """Fabrica: CSV si se pasa --replay, iRacing en vivo si no.

    max_laps solo aplica al replay: en vivo el coach corre hasta que lo pares.
    """
    if replay:
        return ReplaySource(replay, speed=speed, max_laps=max_laps)
    return IRacingSource()
