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


def test_la_referencia_guarda_cuanto_trabajo_el_abs(circuito, analyzer_cfg):
    """El ABS es el testigo de si el piloto se paso de frenada.

    Sin este dato en la referencia no hay con que comparar, y el diagnostico
    post-vuelta no puede existir.
    """
    ref = analizar(circuito, analyzer_cfg)
    frenadas = [e for e in ref["events"] if e["type"] == "brake"]

    assert frenadas
    for ev in frenadas:
        assert "abs_s" in ev, "la frenada no dice cuanto trabajo el ABS"
        assert "min_speed_ms" in ev, "la frenada no dice a cuanto se pasa"
        assert ev["abs_s"] >= 0.0
        assert ev["min_speed_ms"] > 0.0


def test_el_piloto_de_referencia_usa_el_abs_en_todas_las_frenadas(circuito,
                                                                 analyzer_cfg):
    """MEDIDO, y contradice lo que parecia obvio.

    La idea de partida era "si el rapido no activa el ABS y tu si, te has
    pasado". Falso: el piloto de referencia lo activa en las 7 frenadas de
    Hockenheim y en las 9 de Winton. Frena al limite y deja que el sistema
    module; es lo que hace un piloto rapido.

    Por eso el diagnostico NO puede ser un si/no, tiene que ser CUANTO rato.
    Si algun dia este test falla, la premisa ha cambiado y hay que repensar
    todo el analisis post-vuelta.
    """
    ref = analizar(circuito, analyzer_cfg)
    frenadas = [e for e in ref["events"] if e["type"] == "brake"]

    sin_abs = [e for e in frenadas if e["abs_s"] == 0.0]
    assert not sin_abs, f"frenadas sin ABS en la referencia: {sin_abs}"


def test_el_abs_dura_mas_en_las_frenadas_mas_fuertes(analyzer_cfg):
    """La duracion del ABS escala con la intensidad. No es ruido.

    En Hockenheim va de 0.05 s (un roce) a 2.33 s (la frenada mas al limite de
    la vuelta). Si no hubiese esa relacion, el dato no serviria para medir
    nada.
    """
    ref = analizar("hockenheim", analyzer_cfg)
    frenadas = [e for e in ref["events"] if e["type"] == "brake"]

    suaves = [e["abs_s"] for e in frenadas if e["peak"] < 0.5]
    fuertes = [e["abs_s"] for e in frenadas if e["peak"] > 0.8]

    assert suaves and fuertes
    assert max(suaves) < min(fuertes), (
        f"el ABS no distingue frenada suave de fuerte: {suaves} vs {fuertes}"
    )


def test_las_frenadas_detectadas_capturan_casi_todo_el_abs(circuito,
                                                           analyzer_cfg):
    """Validacion cruzada del detector de frenadas, gratis.

    Si el detector se dejase frenadas, apareceria ABS suelto por la vuelta.
    Medido: solo 4 muestras sueltas en Hockenheim y 1 en Winton, de miles.
    """
    df = a.load_lap(str(CSV[circuito]))
    largo = a.track_length_from_speed(df)
    pos = df["LapDistPct"].to_numpy()
    abs_activo = df["ABSActive"].to_numpy().astype(bool)

    dentro = np.zeros(len(df), dtype=bool)
    for z in a.detect_events(df, largo, analyzer_cfg):
        i0 = int(np.argmin(np.abs(pos - z["brake_pos"])))
        i1 = int(np.argmin(np.abs(pos - z["throttle_pos"])))
        dentro[i0:i1] = True

    sueltas = int((abs_activo & ~dentro).sum())
    assert sueltas <= 10, (
        f"{sueltas} muestras de ABS fuera de toda frenada detectada: "
        "el detector se esta dejando alguna"
    )


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


# ---------------------------------------------------------------------------
# El umbral de freno y las zonas de inercia (lecciones de Indianapolis)
# ---------------------------------------------------------------------------


def _vuelta_sintetica(pico_freno: float, acelera_despues: bool = True):
    """Una vuelta de laboratorio: recta, UNA frenada, y salida (o inercia).

    600 muestras a 60 Hz. La frenada dura 1.4 s (84 muestras), calcada de la
    curva de Indianapolis que motivo el umbral actual.
    """
    import pandas as pd

    n = 600
    df = pd.DataFrame({
        "Speed": np.full(n, 50.0),
        "LapDistPct": np.linspace(0.0, 0.99, n),
        "Brake": np.zeros(n),
        "Throttle": np.ones(n),
        "Gear": np.full(n, 3, dtype=int),
    })
    df.loc[150:283, "Throttle"] = 0.0        # levanta antes y durante la frenada
    df.loc[200:283, "Brake"] = pico_freno    # 84 muestras = 1.4 s de pedal
    if not acelera_despues:
        df.loc[284:400, "Throttle"] = 0.0    # inercia larga tras la suelta
    return df


def test_una_frenada_suave_como_la_de_indianapolis_avisa(analyzer_cfg):
    """El umbral bajo a 0.20 por una curva REAL de Indy (pico 0.245, 1.4 s).

    "Toda frenada real avisa, por suave que sea; el umbral solo filtra roces."
    Con el umbral en 0.30 esa curva se quedaba muda, y el ruido medido en los
    tres circuitos no pasa de 0.148: hay hueco de sobra para capturarla.
    """
    zones = a.detect_events(_vuelta_sintetica(0.245), 1000.0, analyzer_cfg)
    assert len(zones) == 1, "la frenada suave se quedo muda"


def test_un_freno_sostenido_bajo_el_umbral_se_canta(analyzer_cfg, capsys):
    """Descartar en silencio ya no vale: en Indy se trago una curva real.

    Un pico de 0.17 sostenido 1.4 s queda bajo el umbral (puede ser un roce
    largo), pero el analyzer lo dice por pantalla: el piloto conoce la vuelta
    y es quien puede decidir si ahi faltaba un aviso.
    """
    zones = a.detect_events(_vuelta_sintetica(0.17), 1000.0, analyzer_cfg)
    assert zones == []

    salida = capsys.readouterr().out
    assert "descartado" in salida and "--brake-min-peak" in salida, (
        "el descarte dudoso no se canto por pantalla"
    )


def test_una_zona_de_inercia_no_emite_aviso_de_gas(analyzer_cfg):
    """Si la referencia NO acelera tras soltar, esa zona no lleva aviso de GAS.

    detect_events ya calculaba esta validacion (coasting) pero nadie la usaba
    y el aviso se emitia igual. Ordenar "GAS" donde el piloto rapido va en
    banda es informacion falsa, la linea roja del proyecto.
    """
    analyzer_cfg.track_length = 1000.0

    def tipos(pico, acelera):
        zones = a.detect_events(_vuelta_sintetica(pico, acelera),
                                1000.0, analyzer_cfg)
        ref = a.to_reference(zones, [], [], analyzer_cfg)
        return [e["type"] for e in ref["events"]]

    assert tipos(0.8, acelera=True) == ["brake", "throttle"]
    assert tipos(0.8, acelera=False) == ["brake"], (
        "sono un GAS en una zona de inercia"
    )


# ---------------------------------------------------------------------------
# El freno arrastrado (leccion de Tsukuba)
# ---------------------------------------------------------------------------


def _vuelta_con_freno_arrastrado():
    """Frenada fuerte, luego el pie se queda APOYADO (0.02) un segundo, y solo
    al soltar del todo entra el gas. Calcada de las curvas lentas de Tsukuba.
    """
    df = _vuelta_sintetica(0.8, acelera_despues=False)
    df.loc[284:343, "Brake"] = 0.02      # 60 muestras = 1 s de pedal apoyado
    df.loc[344:, "Throttle"] = 1.0       # gas al soltar de verdad
    return df


def test_el_freno_arrastrado_no_es_inercia(analyzer_cfg):
    """En Tsukuba la referencia baja el freno a 0.01-0.05 y lo arrastra ~1 s
    antes de soltarlo del todo; el gas entra en la suelta REAL, no al bajar de
    BRAKE_OFF. Tomar el cruce de 0.03 como suelta dejaba 3 de 5 curvas sin GAS
    por "inercia": un aviso bueno silenciado.
    """
    zones = a.detect_events(_vuelta_con_freno_arrastrado(), 1000.0, analyzer_cfg)
    assert len(zones) == 1
    z = zones[0]
    assert not z["coasting"], "el freno arrastrado se tomo por inercia"
    # La suelta real es la muestra 344; el punto de gas cae ahi, no en la 284.
    assert abs(z["throttle_pos"] - 344 / 600 * 0.99) < 6 / 600, z["throttle_pos"]


def test_tsukuba_avisa_gas_en_las_cinco_frenadas(analyzer_cfg):
    """La vuelta real: 5 frenadas, y en TODAS la referencia vuelve a acelerar.

    Medido: desde la suelta real (freno a cero) el gas llega +0.03/+0.48/+0.07 s
    en las tres curvas que antes se marcaban como inercia. Y no se toca ni un
    metro de Hockenheim/Winton, donde el pie no se queda apoyado (los golden
    de esos dos circuitos son la prueba).
    """
    from conftest import DATA

    df = a.load_lap(str(DATA / "tsukuba.csv"))
    analyzer_cfg.track_length = a.track_length_from_speed(df)
    zones = a.detect_events(df, analyzer_cfg.track_length, analyzer_cfg)
    assert len(zones) == 5
    assert [z["coasting"] for z in zones] == [False] * 5, (
        [round(z["throttle_pos"] * 100, 2) for z in zones]
    )
    ref = a.to_reference(zones, [], [], analyzer_cfg)
    assert sum(e["type"] == "throttle" for e in ref["events"]) == 5


# ---------------------------------------------------------------------------
# La escala del pedal (leccion de VIR)
# ---------------------------------------------------------------------------
#
# Cada piloto de Garage61 pisa "hasta arriba" a un valor distinto: 1.00 en
# Hockenheim, 0.78 en Winton, 0.59 en Tsukuba y 0.38 en VIR (Yeonwoo Lee,
# AMG GT4). Es calibracion/fuerza de SU pedal, no ritmo: el de VIR hace 2:22.
# Con umbrales absolutos (BRAKE_ON 0.15 = el 40 % de su frenada maxima) se
# perdian 4 frenadas reales de 13 y otra se detectaba 13 m tarde.


def _con_pedal_escalado(circuito: str, factor: float, tmp_path) -> str:
    """El mismo CSV con el freno multiplicado: otro piloto, mismo pie."""
    import pandas as pd

    df = pd.read_csv(CSV[circuito])
    df["Brake"] = df["Brake"] * factor
    out = tmp_path / f"{circuito}_x{factor}.csv"
    df.to_csv(out, index=False)
    return str(out)


@pytest.mark.parametrize("factor", [0.4, 0.7])
def test_la_escala_del_pedal_no_mueve_las_frenadas(circuito, factor,
                                                    analyzer_cfg, tmp_path):
    """Un pedal que llega a 0.4 en vez de a 1.0 tiene que dar las MISMAS
    frenadas, en los mismos metros, con el mismo punto de gas."""
    ref = a.load_lap(str(CSV[circuito]))
    esc = a.load_lap(_con_pedal_escalado(circuito, factor, tmp_path))
    length = a.track_length_from_speed(ref)

    z_ref = a.detect_events(ref, length, analyzer_cfg)
    z_esc = a.detect_events(esc, length, analyzer_cfg)
    assert len(z_ref) == len(z_esc), (len(z_ref), len(z_esc))
    for r, e in zip(z_ref, z_esc):
        assert abs(r["brake_pos"] - e["brake_pos"]) < 1e-6
        assert abs(r["throttle_pos"] - e["throttle_pos"]) < 1e-6
        assert r["coasting"] == e["coasting"]


def test_vir_detecta_las_trece_frenadas(analyzer_cfg):
    """La vuelta real de VIR con el pedal a 0.376: 13 zonas, y entre ellas las
    cuatro que con umbrales absolutos se perdian (12.4, 15.0, 52.4 y 83.0 %)."""
    from conftest import DATA

    df = a.load_lap(str(DATA / "vir.csv"))
    length = a.track_length_from_speed(df)
    zones = a.detect_events(df, length, analyzer_cfg)
    posiciones = [round(z["brake_pos"] * 100, 1) for z in zones]
    assert len(zones) == 13, posiciones
    for esperada in (12.4, 15.0, 52.4, 83.0):
        assert any(abs(p - esperada) < 0.3 for p in posiciones), (
            f"falta la frenada del {esperada} %: {posiciones}"
        )
    # La frenada 8 (43.6 %) suena donde el pie aterriza, no 13 m despues.
    assert any(abs(p - 43.6) < 0.1 for p in posiciones), posiciones
