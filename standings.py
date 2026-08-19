#!/usr/bin/env python3
"""
standings.py — La clasificacion por clases y el iRating ESTIMADO.

Logica pura sobre SessionSnapshot: ni Tk ni iRacing. Es lo que se puede
testear en el Mac y lo que el overlay pinta sin pensar.

Sobre el iRating: iRacing NO publica el iRating en vivo, solo al acabar la
sesion. Lo que muestran los overlays es una ESTIMACION con la formula que la
comunidad tiene reconstruida (tipo Elo con SoF). Es bastante fiel, pero es
una prediccion, y la pantalla lo dice ("≈"). Dentro de cada clase la suma de
los cambios es cero: lo que unos ganan lo pierden otros.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from source import CarState, SessionSnapshot, laps_done  # noqa: F401 (laps_done: lo usa el overlay)

# La constante de la formula: 1600 / ln 2. Con ella, 1600 puntos de
# diferencia son "el doble de probable ganar".
BR1 = 1600.0 / math.log(2.0)


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------


def _win_prob(a: float, b: float) -> float:
    """Probabilidad de que un piloto de iRating a acabe delante de uno de b."""
    ea = math.exp(-a / BR1)
    eb = math.exp(-b / BR1)
    return ((1.0 - ea) * eb) / ((1.0 - eb) * ea + (1.0 - ea) * eb)


def sof(iratings: list[int]) -> float:
    """Strength of Field: la media "logaritmica" que usa iRacing.

    Queda por debajo de la media aritmetica cuando el campo es desigual: los
    flojos pesan mas de lo que parece. Los iRating desconocidos (0: coches de
    IA, pilotos sin licencia) no cuentan.
    """
    known = [r for r in iratings if r > IR_UNKNOWN]
    if not known:
        return 0.0
    n = len(known)
    return -BR1 * math.log(sum(math.exp(-r / BR1) for r in known) / n)


def irating_changes(iratings: list[int], positions: list[int]) -> list[float | None]:
    """Cambio estimado de iRating de cada piloto (misma clase).

    positions es 1-based. Devuelve una lista alineada con iratings. Un
    iRating desconocido (<= 0) no puntua ni resta a los demas: sale None.
    Sin esto, dos ceros en la misma clase (IA en practica) dividen por cero.
    """
    known = [(i, r, p) for i, (r, p) in enumerate(zip(iratings, positions)) if r > IR_UNKNOWN]
    out: list[float | None] = [None] * len(iratings)
    n = len(known)
    if n < 2:
        for i, _, _ in known:
            out[i] = 0.0
        return out
    # Las posiciones se recomprimen entre los que puntuan.
    order = sorted(known, key=lambda k: k[2])
    rank = {i: k + 1 for k, (i, _, _) in enumerate(order)}
    for i, r, _ in known:
        p = rank[i]
        expected = sum(_win_prob(r, o) for j, o, _ in known if j != i)
        fudge = ((n - 1) / 2.0 - (p - 1)) / 100.0
        out[i] = ((n - p) - expected - fudge) * 200.0 / n
    return out


# ---------------------------------------------------------------------------
# Bloques por clase
# ---------------------------------------------------------------------------


# Sin ninguna vuelta cronometrada en la sesion no hay con que convertir metros
# en segundos; se usa esto hasta que alguien marque una vuelta.
FALLBACK_LAP_S = 100.0

# iRacing da IRating 0 o 1 a la IA y a quien no puntua: eso no es un iRating.
IR_UNKNOWN = 1


@dataclass(frozen=True)
class Row:
    car: CarState
    pos: int
    gap: float  # al lider de la clase, s (+ detras, - delante en pista)
    interval: float  # al coche de delante en la lista, s
    laps_down: int  # vueltas perdidas respecto al lider de la clase
    delta: float | None  # iRating estimado; None = sin iRating (IA)
    fastest: bool  # mejor vuelta de la clase

    @property
    def number(self) -> str:
        return self.car.number

    @property
    def is_me(self) -> bool:
        return self.car.is_me


@dataclass(frozen=True)
class ClassBlock:
    class_id: int
    class_name: str
    sof: float
    n: int
    rows: tuple[Row, ...]
    is_mine: bool


def _in_session(c: CarState) -> bool:
    return c.in_world


class CarMemory:
    """Recuerda, EN CARRERA, a quien se va de la sala.

    Cuando un piloto acaba y sale (o abandona), el SDK deja de darlo: surface
    -1, lap -1, o directamente desaparece de DriverInfo. Si se descarta, los
    de detras "suben" puestos que no son suyos (Sergio: 14 -> 10 -> 7 segun
    acababan los primeros). Aqui se le congela la ultima foto en la que
    estuvo en pista, marcada `gone`, y la clasificacion lo sigue contando
    donde estaba. En practica/quali no: ahi irse es irse.
    """

    def __init__(self):
        self._last: dict[int, CarState] = {}
        self._session: tuple[str, int] | None = None

    def apply(self, snap: SessionSnapshot) -> SessionSnapshot:
        key = (snap.session_type, snap.session_num)
        if key != self._session:
            self._last, self._session = {}, key
        if snap.session_type != "Race":
            return snap
        seen = {c.idx: c for c in snap.cars}
        for c in snap.cars:
            if c.in_world:
                self._last[c.idx] = c
        cars = list(snap.cars)
        out = []
        for c in cars:
            if c.in_world:
                out.append(c)
                continue
            old = self._last.get(c.idx)
            # Slot reocupado por otro piloto: el anterior no resucita.
            if old is not None and old.name == c.name:
                out.append(replace(old, gone=True, incidents=c.incidents))
            else:
                self._last.pop(c.idx, None)
                out.append(c)
        for idx, old in self._last.items():
            if idx not in seen:
                out.append(replace(old, gone=True))
        return replace(snap, cars=tuple(out))


def _track_pos(c: CarState) -> float:
    """Posicion absoluta en pista, en vueltas (vuelta + fraccion)."""
    return c.lap + max(0.0, min(1.0, c.lap_dist_pct))


def _order_key(c: CarState):
    # Fuera de carrera manda la posicion del SDK (en practica/quali es la
    # de mejor vuelta y no envejece); si aun no hay, por vueltas y distancia,
    # y al final por mejor vuelta.
    if c.class_pos > 0:
        return (0, c.class_pos)
    best = c.best_lap if c.best_lap > 0 else float("inf")
    return (1, -c.lap, -c.lap_dist_pct, best)


def _race_key(c: CarState):
    # EN CARRERA manda la pista. CarIdxClassPosition solo cambia en los
    # puntos de cronometraje: entre dos, un adelantamiento tarda en verse
    # (Sergio lo noto como "cierto delay"). Misma leccion que el gap. La
    # posicion del SDK queda de desempate cuando dos coches van clavados.
    return (-_track_pos(c), c.class_pos if c.class_pos > 0 else 10**6)


# Rueda a rueda dos coches se alternan por centimetros y a 2 Hz la tabla
# parpadearia: un intercambio menor que esto (en vueltas: ~10 m en 5 km) no
# se aplica hasta que se consolide. Solo en carrera, que es donde se ordena
# por pista.
HYST_LAP = 0.002


def _settle(cars: list[CarState], prev: dict[int, int]) -> None:
    """Deshace los intercambios menores que HYST_LAP respecto al orden
    anterior (idx -> puesto). Una pasada basta: a 2 Hz converge solo."""
    for i in range(len(cars) - 1):
        a, b = cars[i], cars[i + 1]
        pa, pb = prev.get(a.idx), prev.get(b.idx)
        if pa is None or pb is None or pb >= pa:
            continue
        if _track_pos(a) - _track_pos(b) < HYST_LAP:
            cars[i], cars[i + 1] = b, a


def ranks(blocks: list["ClassBlock"]) -> dict[int, int]:
    """idx -> puesto en su clase, para pasarselo a la foto siguiente."""
    return {r.car.idx: r.pos for b in blocks for r in b.rows}


def build_standings(snap: SessionSnapshot,
                    prev: dict[int, int] | None = None) -> list[ClassBlock]:
    """La clasificacion por clases. `prev` es ranks() de la foto anterior:
    con el, dos coches pegados no bailan (ver HYST_LAP)."""
    by_class: dict[int, list[CarState]] = {}
    for c in snap.cars:
        if _in_session(c):
            by_class.setdefault(c.class_id, []).append(c)

    my_class = snap.me.class_id if snap.me else None
    # Con que convertir distancia en segundos si una clase no tiene vuelta.
    all_bests = [c.best_lap for c in snap.cars if c.best_lap > 0]
    session_lap = min(all_bests) if all_bests else FALLBACK_LAP_S

    blocks = []
    race = snap.session_type == "Race"
    for cid, cars in by_class.items():
        cars.sort(key=_race_key if race else _order_key)
        if race and prev:
            _settle(cars, prev)
        positions = list(range(1, len(cars) + 1))
        deltas = irating_changes([c.irating for c in cars], positions)
        bests = [c.best_lap for c in cars if c.best_lap > 0]
        fastest = min(bests) if bests else None
        lap_s = fastest if fastest else session_lap
        # El gap es DISTANCIA EN PISTA en todo momento (vuelta + fraccion),
        # pasada a segundos con la mejor vuelta de la clase. CarIdxF2Time no
        # sirve: en carrera solo se actualiza en los puntos de control y en
        # practica es un delta de mejor vuelta, no una distancia.
        leader_d = _track_pos(cars[0])
        rows = []
        prev_d = leader_d
        for c, p, d in zip(cars, positions, deltas):
            here = _track_pos(c)
            behind = leader_d - here  # en vueltas; + = detras del lider
            laps_down = int(behind) if behind >= 1.0 else 0
            rows.append(Row(
                car=c, pos=p,
                gap=(behind - laps_down) * lap_s,
                interval=(prev_d - here) * lap_s,
                laps_down=laps_down,
                delta=d,
                fastest=fastest is not None and c.best_lap == fastest,
            ))
            prev_d = here
        blocks.append(ClassBlock(
            class_id=cid,
            class_name=cars[0].class_name,
            sof=sof([c.irating for c in cars]),
            n=len(cars),
            rows=tuple(rows),
            is_mine=cid == my_class,
        ))
    # Mi clase primero; el resto por fuerza (los prototipos arriba).
    blocks.sort(key=lambda b: (not b.is_mine, -b.sof))
    return blocks


# ---------------------------------------------------------------------------
# Relatives: quien tengo delante y detras EN PISTA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelRow:
    car: CarState
    rel_s: float  # segundos respecto a mi: + delante, - detras
    laps_diff: int  # +1 va una vuelta por delante (me dobla), -1 le doblo yo
    class_pos: int  # puesto en su clase (en vivo)

    @property
    def is_me(self) -> bool:
        return self.car.is_me


def build_relative(snap: SessionSnapshot, around: int = 3,
                   blocks: list[ClassBlock] | None = None) -> list[RelRow]:
    """Los `around` coches por delante y por detras de mi en PISTA, sean de la
    clase que sean, con yo en medio. Vacio si no estoy en la sesion.

    Es DISTANCIA circular sobre la vuelta: el que me dobla a 2 s esta "delante"
    aunque vaya una vuelta mas; la vuelta de diferencia se dice aparte
    (laps_diff). Los segundos salen con la mejor vuelta de la sesion (aqui
    conviven clases: no hay una "vuelta de la clase" que valga para todos).
    """
    me = snap.me
    if me is None or not me.in_world:
        return []
    bests = [c.best_lap for c in snap.cars if c.best_lap > 0]
    lap_s = min(bests) if bests else FALLBACK_LAP_S
    if blocks is None:
        blocks = build_standings(snap)
    pos = ranks(blocks)
    my_d = _track_pos(me)
    ahead: list[tuple[float, CarState]] = []
    behind: list[tuple[float, CarState]] = []
    for c in snap.cars:
        if not c.in_world or c.gone or c.is_me:
            continue
        rel = ((c.lap_dist_pct - me.lap_dist_pct + 0.5) % 1.0) - 0.5  # (-0.5, 0.5]
        (ahead if rel > 0 else behind).append((rel, c))
    ahead.sort(key=lambda t: t[0])
    behind.sort(key=lambda t: -t[0])

    def row(rel: float, c: CarState) -> RelRow:
        laps = round((_track_pos(c) - my_d) - rel)
        if me.est_time > 0 and c.est_time > 0:
            # Tiempo del SDK: la diferencia, corregida de vuelta para que
            # caiga del lado (delante/detras) que dice la distancia.
            t = c.est_time - me.est_time
            if rel > 0 and t < 0:
                t += lap_s
            elif rel <= 0 and t > 0:
                t -= lap_s
        else:
            t = rel * lap_s
        return RelRow(car=c, rel_s=t, laps_diff=int(laps),
                      class_pos=pos.get(c.idx, 0))

    rows = [row(rel, c) for rel, c in reversed(ahead[:around])]
    rows.append(RelRow(car=me, rel_s=0.0, laps_diff=0, class_pos=pos.get(me.idx, 0)))
    rows += [row(rel, c) for rel, c in behind[:around]]
    return rows


def visible_rows(block: ClassBlock, top: int = 3, around: int = 2) -> list[Row]:
    """Los `top` primeros y una ventana de ±`around` alrededor de mi.

    En las otras clases solo los `top` primeros: encima del juego cada fila
    tapa pista, y de las otras clases basta saber quien manda.
    """
    rows = block.rows
    me = next((i for i, r in enumerate(rows) if r.is_me), None)
    if me is None:
        return list(rows[:top])
    keep = set(range(min(top, len(rows))))
    keep.update(range(max(0, me - around), min(len(rows), me + around + 1)))
    return [rows[i] for i in sorted(keep)]


def fmt_lap(seconds: float) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    m, s = divmod(seconds, 60.0)
    return f"{int(m)}:{s:06.3f}"


def fmt_gap(seconds: float, leader: bool = False, laps_down: int = 0) -> str:
    if leader:
        return "—"
    if laps_down:
        return f"+{laps_down} L"
    sign = "+" if seconds >= 0 else "−"
    return f"{sign}{abs(seconds):.1f}"


def fmt_ir(ir: int) -> str:
    if ir <= IR_UNKNOWN:
        return "—"
    return f"{ir / 1000:.1f}K" if ir >= 1000 else str(ir)


def fmt_inc(n: int) -> str:
    """Incidentes. iRacing no publica los de los rivales en todas las
    sesiones (CurDriverIncidentCount = -1): eso es "no se sabe", no "-1x"."""
    return "—" if n < 0 else f"{n}x"


def fmt_delta(d: float | None) -> str:
    if d is None:
        return "—"
    sign = "+" if d >= 0 else "−"
    return f"≈{sign}{abs(round(d))}"
