"""Regresion del analyzer: que lo que se detecta hoy siga detectandose manana.

Aparte de los golden hay tests de INVARIANTES: cada uno defiende una decision
de diseño que costo medirla sobre datos reales y que un refactor descuidado
puede tirar por tierra sin que nadie se entere hasta la siguiente carrera.
"""

from __future__ import annotations

import numpy as np
import pytest

import analyzer as a
from conftest import CSV, coach_cfg, golden  # noqa: F401


def analizar(circuito: str, cfg) -> dict:
    """La cadena completa del analyzer, tal cual la corre main()."""
    df = a.load_lap(str(CSV[circuito]))
    track_length = a.track_length_from_speed(df)

    zones = a.detect_events(df, track_length, cfg)
    lifts = a.detect_lifts(df, cfg)
    taken = ([z["brake_pos"] for z in zones]
             + [z["throttle_pos"] for z in zones]
             + [lift["lift_pos"] for lift in lifts])
    manage = a.detect_manage_zones(df, track_length, cfg, taken)

    cfg.track = circuito
    cfg.car = "test"
    cfg.track_length = track_length
    ref = a.to_reference(zones, lifts, manage, cfg)
    # La longitud es una integral de floats: redondear evita que el golden
    # falle por el ultimo bit en otra maquina.
    ref["track_length_m"] = round(ref["track_length_m"], 1)
    return ref


# ---------------------------------------------------------------------------
# Golden: la fotografia del comportamiento validado en pista
# ---------------------------------------------------------------------------


def test_eventos_no_cambian(circuito, analyzer_cfg):
    """El JSON de referencia completo, evento a evento.

    Este es EL test del proyecto. Si falla, algo que sonaba donde debia ya no
    suena donde debia.
    """
    golden(f"{circuito}_events", analizar(circuito, analyzer_cfg))


# ---------------------------------------------------------------------------
# Invariantes: las decisiones de diseño, defendidas
# ---------------------------------------------------------------------------


def test_la_longitud_se_estima_sola(circuito, analyzer_cfg):
    """Integrar la velocidad da la longitud de la vuelta sin teclearla.

    Validado contra Hockenheim: 4516 m estimados vs 4574 m oficiales (1.3 %).
    Es lo que permite estrenar un circuito sin trabajo manual, asi que el
    margen se comprueba, no se supone.
    """
    df = a.load_lap(str(CSV[circuito]))
    largo = a.track_length_from_speed(df)
    assert 1000.0 < largo < 8000.0, "longitud fuera de cualquier circuito real"

    if circuito == "hockenheim":
        assert abs(largo - 4574) / 4574 < 0.02, "se fue del 2 % oficial"


def test_winton_se_rota_a_meta():
    """Winton exporta empezando a mitad de circuito y hay que rotarlo.

    detect_events recorre el array asumiendo orden 0->1. Sin rotar, las curvas
    pegadas al corte se descolocan: la curva 1 no se detectaba y el gas de la
    ultima caia en el 8.77 %. Este test vigila que la rotacion siga ahi.
    """
    crudo = np.loadtxt(CSV["winton"], delimiter=",", skiprows=1, usecols=1)
    assert crudo[0] > 0.05, "el fixture de Winton ya no empieza a mitad de vuelta"

    df = a.load_lap(str(CSV["winton"]))
    pos = df["LapDistPct"].to_numpy()
    assert pos[0] < 0.05, "load_lap no rota a meta"
    assert np.sum(np.diff(pos) < -0.5) == 0, "queda un salto de meta a mitad"


def test_hockenheim_no_necesita_rotacion():
    """La rotacion no debe tocar una vuelta que ya empieza en meta."""
    df = a.load_lap(str(CSV["hockenheim"]))
    assert df["LapDistPct"].to_numpy()[0] < 0.05


def test_el_punto_de_gas_es_la_suelta_del_freno(circuito, analyzer_cfg):
    """El auto-blip sube el acelerador EN PLENA FRENADA. Por eso no se usa.

    Este test no comprueba la implementacion, comprueba el MOTIVO: que en los
    datos reales hay acelerador alto mientras el freno sigue pisado. Mientras
    eso sea cierto, detectar el punto de gas por `throttle > X` situa el aviso
    decenas de metros antes de tiempo, y este test es la prueba viva de que la
    decision sigue siendo la correcta.
    """
    df = a.load_lap(str(CSV[circuito]))
    freno = df["Brake"].to_numpy()
    gas = df["Throttle"].to_numpy()

    blip = (freno > 0.30) & (gas > analyzer_cfg.throttle_on)
    assert blip.any(), (
        "no hay auto-blip en este fixture: revisa si la decision de detectar "
        "el gas por la suelta del freno sigue teniendo base"
    )


def test_el_gas_llega_despues_del_freno(circuito, analyzer_cfg):
    """En toda zona, el punto de gas va DESPUES del de freno. Sin excepciones."""
    df = a.load_lap(str(CSV[circuito]))
    largo = a.track_length_from_speed(df)
    for z in a.detect_events(df, largo, analyzer_cfg):
        assert z["throttle_pos"] > z["brake_pos"], f"zona invertida: {z}"


def picos_de_freno(circuito: str, cfg) -> list[float]:
    """Pico de cada bloque continuo de pedal, sea frenada o roce."""
    freno = a.load_lap(str(CSV[circuito]))["Brake"].to_numpy()
    picos = []
    i = 0
    while i < len(freno):
        if freno[i] <= cfg.brake_off:
            i += 1
            continue
        j = i
        while j < len(freno) and freno[j] > cfg.brake_off:
            j += 1
        picos.append(float(freno[i:j].max()))
        i = j
    return picos


# Banda ambigua: por debajo son roces evidentes, por encima esta el umbral.
# Un pico aqui no se puede clasificar mirando solo su altura, y es justo el
# caso en que el umbral deja de ser inocente.
BANDA_AMBIGUA = 0.15


def test_hueco_alrededor_del_umbral_de_freno(circuito, analyzer_cfg):
    """Toda frenada real avisa; el umbral solo filtra roces.

    BRAKE_MIN_PEAK bajo de 0.35 a 0.30 para no perder la curva 1 de Hockenheim
    (un toque de 0.34), y la justificacion fue que existe un HUECO alrededor
    del umbral.

    OJO con la version antigua de esa afirmacion ("no hay picos entre 0.05 y
    0.34"): eso solo es cierto en Hockenheim. Winton tiene cinco toques bajo
    umbral (hasta 0.109) agrupados entre el 35 % y el 41 % de la vuelta, que
    es estabilizar el coche mientras se modula el gas, no frenar. El hueco
    real medido va de 0.109 a 0.355, y el umbral cae dentro con holgura por
    abajo y con poco margen por arriba.

    Lo que este test vigila es lo que de verdad importa: que ningun pico caiga
    en la banda ambigua. Si un circuito nuevo mete un toque de 0.25, ya no se
    puede decidir por altura si es aviso o ruido, y toca mirarlo a mano.
    """
    ambiguos = [p for p in picos_de_freno(circuito, analyzer_cfg)
                if BANDA_AMBIGUA < p < analyzer_cfg.brake_min_peak]
    assert not ambiguos, (
        f"picos en la banda ambigua {BANDA_AMBIGUA}-{analyzer_cfg.brake_min_peak}: "
        f"{ambiguos}. No se puede decidir por altura: o se pierden avisos "
        "reales, o el umbral cuela roces. Miralo sobre los datos."
    )


def test_ninguna_frenada_real_se_queda_sin_avisar(circuito, analyzer_cfg):
    """El umbral no puede estar comiendose una frenada de verdad.

    Una frenada real es larga y profunda; un roce es corto y superficial. Si
    algun pico descartado dura mas de medio segundo Y pasa de la banda
    ambigua, es candidato a aviso perdido.
    """
    df = a.load_lap(str(CSV[circuito]))
    freno = df["Brake"].to_numpy()

    sospechosos = []
    i = 0
    while i < len(freno):
        if freno[i] <= analyzer_cfg.brake_off:
            i += 1
            continue
        j = i
        while j < len(freno) and freno[j] > analyzer_cfg.brake_off:
            j += 1
        pico, dur = float(freno[i:j].max()), (j - i) / a.SAMPLE_RATE
        if pico < analyzer_cfg.brake_min_peak and dur > 0.5 and pico > BANDA_AMBIGUA:
            sospechosos.append((round(pico, 3), round(dur, 2)))
        i = j

    assert not sospechosos, f"posibles frenadas perdidas (pico, dur): {sospechosos}"


def test_la_marcha_es_la_de_la_curva_no_la_de_la_frenada(analyzer_cfg):
    """En una horquilla frenas en 5a y la tomas en 1a. Se dice la de la curva.

    Se comprueba que la marcha guardada es la del punto de gas: en al menos
    una zona tiene que ser MENOR que la del inicio de frenada, o el dato que
    se le canta al piloto no es el que decidimos.
    """
    df = a.load_lap(str(CSV["hockenheim"]))
    largo = a.track_length_from_speed(df)
    marchas = df["Gear"].to_numpy()
    pos = df["LapDistPct"].to_numpy()

    reduce_de_verdad = False
    for z in a.detect_events(df, largo, analyzer_cfg):
        i_freno = int(np.argmin(np.abs(pos - z["brake_pos"])))
        if z["gear"] < int(marchas[i_freno]):
            reduce_de_verdad = True
    assert reduce_de_verdad, "ninguna zona reduce de marcha: dato sospechoso"


@pytest.mark.parametrize("circuito_esperado,tiene_manage", [
    ("hockenheim", False),
    ("winton", True),
])
def test_zonas_de_gestion_solo_donde_toca(circuito_esperado, tiene_manage,
                                          analyzer_cfg):
    """`manage` es el patron mas delicado: cero en Hockenheim, una en Winton.

    Es el detector con mas riesgo de falsos positivos. Fijar el recuento en
    los dos circuitos validados es la unica forma de que un ajuste de umbrales
    no lo llene de avisos fantasma sin que nadie lo note.
    """
    ref = analizar(circuito_esperado, analyzer_cfg)
    manage = [e for e in ref["events"] if e["type"] == "manage"]
    assert bool(manage) == tiene_manage, f"zonas de gestion: {manage}"
