#!/usr/bin/env python3
"""
review.py — El analisis POST-vuelta: no solo cuanto, sino POR QUE.

El coach en vivo te dice DONDE frenar. Esto te dice, al cruzar meta, por que
has ido lento en una curva. Y eso importa porque hay dos formas de ir lento y
se corrigen AL REVES:

  - frenaste pronto y suave  -> llegas lento pero limpio  -> frena mas tarde
  - frenaste tarde y a saco  -> el ABS trabaja y la rueda no gira -> te vas
                                largo -> frena ANTES y mas suave

Desde dentro del coche las dos se sienten igual ("he ido lento ahi"), y si te
equivocas de diagnostico corriges en la direccion contraria y lo empeoras.

EL TESTIGO ES EL ABS, PERO NO COMO SI/NO. Medido sobre las dos referencias, el
piloto rapido activa el ABS en TODAS sus frenadas (7 de 7 en Hockenheim, 9 de 9
en Winton): frena al limite y deja que el sistema module. Lo que distingue una
frenada de otra es CUANTO rato trabaja, que ademas escala con la intensidad
(0.05 s en un roce, 2.33 s en la mas al limite de la vuelta).

Nada de esto suena EN VIVO. Un "¡ABS!" mientras frenas es la peor distraccion
posible y ademas llega tarde: cuando lo oyes, ya te has pasado.
"""

from __future__ import annotations

from dataclasses import dataclass

SAMPLE_RATE = 60.0

# Cuanto mas ABS que la referencia cuenta como pasarse. Hacen falta LAS DOS
# condiciones: un salto relativo y un salto absoluto.
#
# El absoluto no es un adorno. La frenada 5 de Hockenheim tiene 0.05 s de ABS;
# pasar a 0.35 s son siete veces mas, y en absoluto son tres decimas de nada.
# Sin minimo absoluto, el coach cantaria un error en cada roce del pedal.
ABS_MORE_RATIO = 1.4
ABS_MORE_ABS_S = 0.4

# Y al reves: cuanto menos ABS cuenta como que te sobra margen.
ABS_LESS_RATIO = 0.6

# Cuanto mas lento hay que pasar para que merezca la pena decir algo. Por
# debajo de esto es la variacion normal entre vueltas, no un error.
SLOWER_MS = 1.0


@dataclass(frozen=True)
class Diagnosis:
    """El veredicto de una frenada, con los numeros que lo justifican."""

    pos: float
    verdict: str  # ok | passed | short | limit
    cue: str | None  # la palabra que se le dice al piloto, o nada
    abs_s: float
    ref_abs_s: float
    min_speed_ms: float
    ref_min_speed_ms: float

    @property
    def delta_kmh(self) -> float:
        """Cuanto mas rapido (+) o mas lento (-) pasas que la referencia."""
        return (self.min_speed_ms - self.ref_min_speed_ms) * 3.6

    def describe(self) -> str:
        """Una linea de texto para el resumen escrito."""
        cuerpo = (f"Frenada @{self.pos * 100:5.1f}%   "
                  f"ABS {self.abs_s:4.2f}s (el {self.ref_abs_s:4.2f}s)   "
                  f"{self.delta_kmh:+5.1f} km/h")
        explicacion = {
            "passed": "te pasaste de frenada: frena antes y mas suave",
            "short": "te sobra margen: puedes frenar mas tarde o mas fuerte",
            "limit": "vas al limite, mismo resultado castigando mas la goma",
            "ok": "bien",
        }[self.verdict]
        return f"{cuerpo}\n     -> {explicacion}"


def diagnose(event: dict, abs_s: float, min_speed_ms: float) -> Diagnosis:
    """Compara una frenada tuya con la misma frenada de la referencia."""
    ref_abs = float(event.get("abs_s", 0.0))
    ref_min = float(event.get("min_speed_ms", min_speed_ms))

    mas_abs = (abs_s > ref_abs * ABS_MORE_RATIO
               and abs_s - ref_abs > ABS_MORE_ABS_S)
    menos_abs = abs_s < ref_abs * ABS_LESS_RATIO
    mas_lento = min_speed_ms < ref_min - SLOWER_MS

    if mas_abs and mas_lento:
        verdict, cue = "passed", "suave"
    elif menos_abs and mas_lento:
        verdict, cue = "short", "aprieta"
    elif mas_abs:
        # Mismo resultado pero castigando mas la goma. Se apunta, no se canta:
        # no hay nada que corregir en la siguiente frenada.
        verdict, cue = "limit", None
    else:
        verdict, cue = "ok", None

    return Diagnosis(
        pos=event["pos"],
        verdict=verdict,
        cue=cue,
        abs_s=round(abs_s, 2),
        ref_abs_s=ref_abs,
        min_speed_ms=min_speed_ms,
        ref_min_speed_ms=ref_min,
    )


def worst(diagnoses) -> Diagnosis | None:
    """La frenada que mas te esta costando, o nada si la vuelta fue limpia.

    Solo se canta UNA cosa por vuelta. Corregir siete curvas a la vez no es
    entrenar, es ruido, y acabas apagando el coach.
    """
    corregibles = [d for d in diagnoses if d.cue]
    if not corregibles:
        return None
    return min(corregibles, key=lambda d: d.delta_kmh)


class LapReview:
    """Va tomando nota de tu vuelta, frenada a frenada.

    No guarda la vuelta entera en memoria ni escribe ficheros: para cada zona
    de frenada de la referencia le basta con dos numeros (cuanto ABS y a cuanto
    pasaste por lo mas lento).
    """

    def __init__(self, events: list[dict], window: float = 0.04):
        # `window` es cuanto trozo de vuelta alrededor del punto de frenada se
        # vigila, en fraccion de vuelta. 0.04 son unos 180 m en un circuito de
        # 4.5 km: de sobra para cubrir frenada mas curva, sin invadir la
        # siguiente zona.
        self.zones = [e for e in events if e["type"] == "brake"]
        self.window = window
        self._reset()

    def _reset(self) -> None:
        self._abs_frames = [0] * len(self.zones)
        self._min_speed = [None] * len(self.zones)

    def on_frame(self, f) -> None:
        for i, ev in enumerate(self.zones):
            # Distancia hasta la zona, resolviendo el paso por meta.
            delta = (f.lap_pos - ev["pos"]) % 1.0
            if delta > self.window:
                continue
            if f.abs_active:
                self._abs_frames[i] += 1
            actual = self._min_speed[i]
            if actual is None or f.speed_ms < actual:
                self._min_speed[i] = f.speed_ms

    def finish(self) -> list[Diagnosis]:
        """Cierra la vuelta y devuelve el diagnostico de lo que se rodo.

        Las zonas por las que no se paso (entraste a boxes a media vuelta) no
        salen: inventar un diagnostico de una curva que no has hecho seria
        justo el tipo de informacion falsa que este proyecto no da.
        """
        salida = []
        for i, ev in enumerate(self.zones):
            if self._min_speed[i] is None:
                continue
            salida.append(diagnose(
                ev,
                abs_s=self._abs_frames[i] / SAMPLE_RATE,
                min_speed_ms=self._min_speed[i],
            ))
        self._reset()
        return salida
