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
from dataclasses import dataclass

from source import CarState, SessionSnapshot

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
    known = [r for r in iratings if r > 0]
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
    known = [(i, r, p) for i, (r, p) in enumerate(zip(iratings, positions)) if r > 0]
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


@dataclass(frozen=True)
class Row:
    car: CarState
    pos: int
    gap: float  # al lider de la clase, s
    interval: float  # al coche de delante en la clase, s
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


def _order_key(c: CarState):
    # En carrera manda la posicion del SDK; si aun no hay (practica, o justo
    # al cargar), ordena por vueltas y distancia, y al final por mejor vuelta.
    if c.class_pos > 0:
        return (0, c.class_pos)
    best = c.best_lap if c.best_lap > 0 else float("inf")
    return (1, -c.lap, -c.lap_dist_pct, best)


def build_standings(snap: SessionSnapshot) -> list[ClassBlock]:
    by_class: dict[int, list[CarState]] = {}
    for c in snap.cars:
        if _in_session(c):
            by_class.setdefault(c.class_id, []).append(c)

    my_class = snap.me.class_id if snap.me else None
    blocks = []
    for cid, cars in by_class.items():
        cars.sort(key=_order_key)
        positions = list(range(1, len(cars) + 1))
        deltas = irating_changes([c.irating for c in cars], positions)
        bests = [c.best_lap for c in cars if c.best_lap > 0]
        fastest = min(bests) if bests else None
        leader_f2 = cars[0].f2_time
        rows = []
        prev_f2 = leader_f2
        for c, p, d in zip(cars, positions, deltas):
            gap = c.f2_time - leader_f2
            rows.append(Row(
                car=c, pos=p, gap=gap, interval=c.f2_time - prev_f2, delta=d,
                fastest=fastest is not None and c.best_lap == fastest,
            ))
            prev_f2 = c.f2_time
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


def visible_rows(block: ClassBlock, top: int = 3, around: int = 2) -> list[Row]:
    """Los `top` primeros y una ventana de ±`around` alrededor de mi.

    Si no estoy en el bloque (otra clase), los primeros `top + 2*around + 1`.
    """
    rows = block.rows
    me = next((i for i, r in enumerate(rows) if r.is_me), None)
    if me is None:
        return list(rows[: top + 2 * around + 1])
    keep = set(range(min(top, len(rows))))
    keep.update(range(max(0, me - around), min(len(rows), me + around + 1)))
    return [rows[i] for i in sorted(keep)]


def fmt_lap(seconds: float) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    m, s = divmod(seconds, 60.0)
    return f"{int(m)}:{s:06.3f}"


def fmt_gap(seconds: float, leader: bool = False) -> str:
    if leader:
        return "—"
    return f"+{seconds:.1f}"


def fmt_ir(ir: int) -> str:
    if ir <= 0:
        return "—"
    return f"{ir / 1000:.1f}K" if ir >= 1000 else str(ir)


def fmt_delta(d: float | None) -> str:
    if d is None:
        return "—"
    sign = "+" if d >= 0 else "−"
    return f"≈{sign}{abs(round(d))}"
