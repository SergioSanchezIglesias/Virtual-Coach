"""Fixtures compartidas de los tests.

La idea de estos tests es UNA: el core esta validado en pista y en carrera,
asi que cualquier cambio que altere lo que se detecta o lo que suena tiene que
saltar aqui ANTES de que lo descubras a 200 km/h.

Los CSV de tests/data/ son copias congeladas de las vueltas reales con las que
se valido el proyecto. Son copias A PROPOSITO: los CSV de la raiz los vas
sobrescribiendo cada vez que exportas de Garage61, y un fixture que cambia
bajo los pies no congela nada.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "golden"

# Las dos vueltas con las que se valido el proyecto. Hockenheim ya viene
# cortada en meta; Winton no (empieza a mitad de circuito), asi que ejercita
# la rotacion de load_lap.
CIRCUITOS = ["hockenheim", "winton"]

CSV = {
    "hockenheim": DATA / "vuelta_hockenheim.csv",
    "winton": DATA / "winton.csv",
}


@pytest.fixture(params=CIRCUITOS)
def circuito(request) -> str:
    """Parametriza un test sobre las dos vueltas de referencia."""
    return request.param


@pytest.fixture
def analyzer_cfg() -> SimpleNamespace:
    """Los umbrales por defecto del analyzer, tal cual los define el modulo.

    Se leen del modulo en vez de copiarlos aqui: si alguien toca una constante
    (por ejemplo BRAKE_MIN_PEAK, que costo sangre afinar), los golden cambian
    y el test canta. Duplicar los valores aqui haria justo lo contrario.
    """
    import analyzer as a

    return SimpleNamespace(
        brake_on=a.BRAKE_ON,
        brake_off=a.BRAKE_OFF,
        brake_min_peak=a.BRAKE_MIN_PEAK,
        brake_min_dur=a.BRAKE_MIN_DUR,
        throttle_on=a.THROTTLE_ON,
        merge_dist=a.MERGE_DIST,
        lift_full=a.LIFT_FULL,
        lift_target=a.LIFT_TARGET,
        lift_no_brake=a.LIFT_NO_BRAKE,
        lift_min_dur=a.LIFT_MIN_DUR,
        lift_recover=a.LIFT_RECOVER,
        manage_full=a.MANAGE_FULL,
        manage_no_brake=a.MANAGE_NO_BRAKE,
        manage_min_dur=a.MANAGE_MIN_DUR,
        manage_crossings=a.MANAGE_CROSSINGS,
        manage_clear=a.MANAGE_CLEAR,
        track=None,
        car=None,
        laptime=None,
        track_length=None,
    )


def coach_cfg(**overrides) -> SimpleNamespace:
    """Config del coach con los defaults del CLI, sobreescribible por test.

    Los valores son los mismos defaults de coach.main(), mas la configuracion
    de cuenta atras que Sergio valido al oido (3 ticks cada 0.5 s).
    """
    cfg = SimpleNamespace(
        lead=0.35,
        margin=0.0,
        speed_tol=0.10,
        skip_mismatch=False,
        countdown=3,
        countdown_interval=0.5,
        count_ms=45,
        count_volume=0.20,
        count_freq=330.0,
        brake_freq=620.0,
        throttle_freq=1050.0,
        lift_freq=820.0,
        manage_freq=720.0,
        voice=False,
        voice_volume=0.60,
        beep_ms=90,
        verbose=False,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def referencia(circuito: str) -> dict:
    """La referencia congelada de un circuito, tal cual la consume el coach.

    Se lee del golden del analyzer a proposito: si el analyzer cambia lo que
    detecta, el test del analyzer canta primero y los del coach siguen
    corriendo sobre una entrada estable. Un solo fallo, no una cascada.
    """
    path = GOLDEN / f"{circuito}_events.json"
    if not path.exists():
        pytest.skip(f"falta {path.name}: corre antes los tests del analyzer")
    return json.loads(path.read_text(encoding="utf-8"))


def golden(name: str, produced):
    """Compara con el fichero congelado, o lo crea la primera vez.

    Si el golden no existe se escribe y el test pasa: es la fotografia
    inicial. A partir de ahi, cualquier diferencia falla. Para re-fotografiar
    a proposito (porque el cambio es deseado y esta validado), borra el
    fichero y vuelve a correr.
    """
    path = GOLDEN / f"{name}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(produced, indent=2), encoding="utf-8")
        pytest.skip(f"golden creado: {path.name} (revisalo y vuelve a correr)")

    esperado = json.loads(path.read_text(encoding="utf-8"))
    assert produced == esperado, (
        f"El comportamiento cambio respecto a {path.name}.\n"
        "Si el cambio es DELIBERADO y esta validado, borra el golden y "
        "regeneralo. Si no lo esperabas, acabas de romper algo que funcionaba."
    )
