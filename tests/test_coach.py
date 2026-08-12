"""Regresion del coach: que suene lo mismo, donde mismo y en el mismo orden.

El replay es determinista: con `speed=0` la fuente no duerme y el coach ve
exactamente los mismos frames en cada ejecucion. Eso convierte "lo que suena
en una vuelta" en algo que se puede congelar en un fichero y comparar.
"""

from __future__ import annotations

import pytest

from coach import Coach, ConsoleEngine
from conftest import CSV, coach_cfg, golden, referencia
from source import ReplaySource


class GrabadorEngine(ConsoleEngine):
    """Motor que apunta cada aviso con la posicion en que sono.

    Hereda de ConsoleEngine a proposito: el Coach comprueba el tipo para
    decidir si genera tonos de audio o etiquetas de texto, y aqui queremos
    las etiquetas (comparar strings es legible; comparar buffers de audio, no).
    """

    def __init__(self):
        super().__init__({})
        self.frame = None
        self.giro = 0  # vuelta de CIRCUITO, contada por cruces de meta
        self.avisos: list[dict] = []

    def play(self, tone):
        self.avisos.append({
            "aviso": tone,
            "giro": self.giro,
            "pos": round(self.frame.lap_pos, 4),
        })


def rodar(circuito: str, vueltas: int = 3, **overrides) -> list[dict]:
    """Reproduce el CSV y devuelve todo lo que sono, con su vuelta y posicion.

    La vuelta se cuenta por CRUCES DE META (caida de lap_pos), no con el campo
    `lap` del Frame. No es un capricho: ver test_el_lap_del_replay_no_es_la_
    vuelta_del_circuito, mas abajo.
    """
    cfg = coach_cfg(**overrides)
    engine = GrabadorEngine()
    coach = Coach(referencia(circuito), engine, cfg)

    src = ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=vueltas)
    anterior = None
    for frame in src.frames():
        if anterior is not None and frame.lap_pos < anterior - 0.5:
            engine.giro += 1
        anterior = frame.lap_pos
        engine.frame = frame
        coach.on_frame(frame)
    return engine.avisos


def giro_completo(circuito: str, **overrides) -> list[dict]:
    """Los avisos de una vuelta entera de circuito, sin bordes del replay.

    La primera y la ultima vuelta del replay estan cortadas (el CSV puede
    empezar a mitad de circuito), asi que para contar avisos se usa una
    intermedia, que si es una vuelta completa de verdad.
    """
    avisos = rodar(circuito, vueltas=3, **overrides)
    return [a for a in avisos if a["giro"] == 1]


# ---------------------------------------------------------------------------
# Golden: la vuelta sonora completa
# ---------------------------------------------------------------------------


def test_lo_que_suena_no_cambia(circuito):
    """Cada aviso, su tipo y su posicion, vuelta a vuelta."""
    golden(f"{circuito}_coach", rodar(circuito))


# ---------------------------------------------------------------------------
# Invariantes del bucle
# ---------------------------------------------------------------------------


def test_cada_vuelta_rearma_los_avisos(circuito):
    """Al cruzar meta se rearma todo: cada vuelta suena igual que la anterior.

    Es el fallo mas silencioso posible: el coach enmudece a partir de la
    segunda vuelta y solo te enteras rodando.
    """
    avisos = rodar(circuito, vueltas=3)
    v1 = [a["aviso"] for a in avisos if a["giro"] == 1]
    v2 = [a["aviso"] for a in avisos if a["giro"] == 2]

    assert v1, "no sono nada en la vuelta completa"
    assert v2 == v1, "la vuelta siguiente no repite los mismos avisos"


def test_el_lap_del_replay_no_es_la_vuelta_del_circuito():
    """DEFECTO CONOCIDO de ReplaySource, documentado aqui a proposito.

    ReplaySource incrementa `lap` cuando se acaba el buffer del CSV, no cuando
    se cruza meta. En un CSV cortado en meta (Hockenheim) da igual, pero
    Winton empieza en el 16 % de la vuelta: ahi el cruce de meta cae A MITAD
    del buffer y `frame.lap` va desfasado respecto a la vuelta real.

    Hoy no rompe nada porque NADIE fuera de source.py lee `frame.lap`: el
    coach se orienta solo con `lap_pos`. Pero cualquier funcion que cuente
    vueltas (el analisis post-vuelta, por ejemplo) se comeria el desfase, asi
    que queda escrito. iRacing en vivo si incrementa Lap al cruzar meta, o sea
    que en este punto el replay NO es fiel al simulador.
    """
    src = ReplaySource(str(CSV["winton"]), speed=0.0, max_laps=2)
    cruces_dentro_del_mismo_lap = 0
    anterior = None
    for f in src.frames():
        if anterior is not None and f.lap_pos < anterior[0] - 0.5:
            if f.lap == anterior[1]:
                cruces_dentro_del_mismo_lap += 1
        anterior = (f.lap_pos, f.lap)

    assert cruces_dentro_del_mismo_lap > 0, (
        "ReplaySource ya cuenta las vueltas por meta: arreglado el defecto, "
        "borra este test y actualiza la nota de CLAUDE.md"
    )


def test_la_cuenta_atras_solo_va_en_las_frenadas(circuito):
    """Los ticks preceden a FRENA y solo a FRENA.

    El aviso de gas es un "ya puedes", no algo para lo que prepararse, y
    ponerle cuenta atras subiria de 30 a 48 sonidos por vuelta.
    """
    avisos = [a["aviso"] for a in giro_completo(circuito)]
    tick = "  ."

    for i, aviso in enumerate(avisos):
        if aviso != tick:
            continue
        siguientes = [x for x in avisos[i + 1:] if x != tick]
        assert siguientes and siguientes[0] == "FRENA", (
            f"un tick en la posicion {i} no desemboca en una frenada: "
            f"{avisos[max(0, i - 2):i + 3]}"
        )


def test_hay_tres_ticks_por_frenada(circuito):
    """Con --countdown 3, cada frenada llega precedida de sus tres ticks."""
    avisos = [a["aviso"] for a in giro_completo(circuito)]
    frenadas = avisos.count("FRENA")
    ticks = avisos.count("  .")
    assert frenadas > 0
    assert ticks == 3 * frenadas, f"{ticks} ticks para {frenadas} frenadas"


def test_sin_countdown_no_suena_ningun_tick(circuito):
    avisos = [a["aviso"] for a in giro_completo(circuito, countdown=0)]
    assert "  ." not in avisos


def test_la_antelacion_de_la_voz_no_se_comprime_en_meta():
    """Un aviso cuya antelacion cruza la linea de meta suena ANTES de cruzarla.

    La curva 1 de Hockenheim esta a 167 m de meta y su voz necesita ~3.7 s de
    antelacion (frase + cuenta atras + colchon): a 220 km/h la frase arranca
    unos 60 m ANTES de la linea. Con el rearme en meta (el diseno viejo) la
    voz no podia sonar hasta cruzar y salia comprimida contra la linea, con
    los ticks sonando encima. El rearme por evento la deja donde toca.

    Y una sola vez por aproximacion: comprimida era malo, doble seria peor.
    """
    avisos = rodar("hockenheim", vueltas=3, voice=True)
    voz_t1 = [a for a in avisos if a["aviso"] == "[voz] Frena, 40%, 4a"]

    # Tres vueltas de replay = cuatro aproximaciones a la curva 1 (la del
    # arranque y una por cada paso por meta, incluida la del final del buffer).
    assert len(voz_t1) == 4, f"la voz de la curva 1 sono {len(voz_t1)} veces"

    # Salvo la primera (el replay YA arranca dentro de su ventana), todas
    # tienen que sonar antes de la linea, no comprimidas tras ella.
    for v in voz_t1[1:]:
        assert v["pos"] > 0.9, (
            f"la voz de la curva 1 sono en {v['pos']:.4f}: comprimida tras "
            "meta en vez de anticiparse antes de la linea"
        )


def test_el_aviso_llega_antes_del_punto(circuito):
    """El aviso tiene que ADELANTARSE al evento, nunca sonar encima ni tarde.

    Para cada aviso se busca el evento de su mismo tipo mas cercano por
    delante: tiene que existir, y a una distancia razonable. Un aviso que
    suena DESPUES del punto es peor que no avisar.
    """
    ref = referencia(circuito)
    largo = ref["track_length_m"]
    etiqueta = {"brake": "FRENA", "throttle": "GAS  ",
                "lift": "SUELTA", "manage": "MEDIO GAS"}

    for son in giro_completo(circuito, countdown=0):
        candidatos = [
            (ev["pos"] - son["pos"]) % 1.0
            for ev in ref["events"] if etiqueta[ev["type"]] == son["aviso"]
        ]
        adelanto_m = min(candidatos) * largo
        assert 0 < adelanto_m < 200, (
            f"{son['aviso']} en {son['pos']:.4f} avisa a {adelanto_m:.0f} m "
            "de su evento: o suena tarde, o suena absurdamente pronto"
        )


def test_el_margen_adelanta_mas_el_aviso(circuito):
    """--margin es un colchon de seguridad: mas metros, aviso mas temprano.

    Sergio es piloto seguro y ante la duda hay que frenar pronto. Si un
    refactor invierte este signo, el margen deja de proteger y pasa a hacer
    exactamente lo contrario.
    """
    sin = giro_completo(circuito, countdown=0)
    con = giro_completo(circuito, countdown=0, margin=50.0)

    assert len(sin) == len(con)
    for a, b in zip(sin, con):
        assert a["aviso"] == b["aviso"]
        assert b["pos"] < a["pos"], "con --margin el aviso NO se adelanto"


def test_skip_mismatch_calla_si_la_velocidad_no_cuadra(circuito):
    """Con la referencia inflada, ningun punto aplica y el coach se calla.

    El punto de frenada de otro piloto depende de su velocidad de entrada. Si
    llegas muy distinto, avisar es peor que callarse.
    """
    ref = referencia(circuito)
    inflada = dict(ref, events=[dict(e, speed_ms=e["speed_ms"] * 3.0)
                                for e in ref["events"]])

    engine = GrabadorEngine()
    coach = Coach(inflada, engine, coach_cfg(countdown=0, skip_mismatch=True))
    src = ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=1)
    for frame in src.frames():
        engine.frame = frame
        coach.on_frame(frame)

    assert not engine.avisos, f"aviso con velocidad incompatible: {engine.avisos}"


def test_sin_skip_mismatch_avisa_igual(circuito):
    """Por defecto el mismatch solo se anota; no silencia el aviso."""
    ref = referencia(circuito)
    inflada = dict(ref, events=[dict(e, speed_ms=e["speed_ms"] * 3.0)
                                for e in ref["events"]])

    engine = GrabadorEngine()
    coach = Coach(inflada, engine, coach_cfg(countdown=0, skip_mismatch=False))
    src = ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=1)
    for frame in src.frames():
        engine.frame = frame
        coach.on_frame(frame)

    assert engine.avisos, "se callo sin que nadie se lo pidiera"


# ---------------------------------------------------------------------------
# Utilidades del coach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evento,piloto,esperado", [
    (0.20, 0.10, 0.10),   # el evento va por delante, sin lio
    (0.02, 0.98, 0.04),   # el evento esta pasada la meta: hay que sumar la vuelta
    (0.50, 0.50, 0.00),   # justo encima
])
def test_gap_to_resuelve_el_paso_por_meta(evento, piloto, esperado):
    """Sin esto, el ultimo tramo de la vuelta da distancias negativas."""
    coach = Coach({"track_length_m": 1000.0, "events": []},
                  ConsoleEngine({}), coach_cfg())
    assert coach.gap_to(evento, piloto) == pytest.approx(esperado * 1000.0)


# ---------------------------------------------------------------------------
# Analisis post-vuelta y modo entrenamiento
# ---------------------------------------------------------------------------


def test_el_analisis_no_cambia_ni_un_aviso(circuito):
    """Lo primero, como siempre: mirar no puede alterar lo que suena."""
    con = rodar(circuito, vueltas=2)
    golden(f"{circuito}_coach", rodar(circuito))
    assert con, "no sono nada"


def test_al_cruzar_meta_hay_diagnostico_de_la_vuelta(circuito):
    """El resumen se cierra en meta, que es cuando el dato aun esta fresco."""
    engine = GrabadorEngine()
    coach = Coach(referencia(circuito), engine, coach_cfg())

    anterior = None
    for f in ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=2).frames():
        anterior = f.lap_pos
        engine.frame = f
        coach.on_frame(f)

    assert coach.last_review, "no genero ningun diagnostico al cruzar meta"
    assert all(d.verdict in ("ok", "passed", "short", "limit")
               for d in coach.last_review)


def test_rodando_la_propia_referencia_no_se_corrige_nada(circuito):
    """Si le das la vuelta que le sirve de referencia, no hay nada que decir.

    Es la garantia contra el coach cansino: solo habla cuando hay algo de
    verdad que corregir.
    """
    engine = GrabadorEngine()
    coach = Coach(referencia(circuito), engine, coach_cfg(training=True))

    for f in ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=2).frames():
        engine.frame = f
        coach.on_frame(f)

    assert coach.training_cue is None, (
        f"se invento una correccion: {coach.training_cue}"
    )


def test_en_modo_entrenamiento_la_correccion_va_DENTRO_de_la_frase():
    """La decision de diseño: ni una frase nueva, ni un sonido nuevo.

    La voz ya dice "Frena, 40%, tercera". En entrenamiento dice "Frena, 40%,
    tercera, suave". Llega en el mismo momento, no busca hueco, y sobre todo
    es una ORDEN ("suave") en vez de un reproche ("aqui te pasaste"): un aviso
    que mira al pasado te mete duda justo antes de frenar, y la duda cuesta
    mas tiempo que el error.
    """
    ref = referencia("hockenheim")
    frenada = next(e for e in ref["events"] if e["type"] == "brake")

    engine = GrabadorEngine()
    coach = Coach(ref, engine, coach_cfg(voice=True, training=True))
    coach.set_training_cue(frenada["pos"], "suave")

    texto = next(ev["_voice"] for ev in coach.events
                 if ev["pos"] == frenada["pos"])
    assert texto.endswith("suave"), f"la correccion no entro en la frase: {texto}"
    assert texto.count("[voz]") == 1, "se genero una frase aparte"


def test_sin_modo_entrenamiento_la_frase_es_la_de_siempre():
    ref = referencia("hockenheim")
    frenada = next(e for e in ref["events"] if e["type"] == "brake")

    coach = Coach(ref, GrabadorEngine(), coach_cfg(voice=True, training=False))
    coach.set_training_cue(frenada["pos"], "suave")

    texto = next(ev["_voice"] for ev in coach.events
                 if ev["pos"] == frenada["pos"])
    assert not texto.endswith("suave"), "hablo de mas con el modo apagado"


def test_la_correccion_solo_va_en_una_curva():
    """Corregir siete curvas a la vez no es entrenar, es ruido."""
    ref = referencia("hockenheim")
    frenadas = [e for e in ref["events"] if e["type"] == "brake"]

    coach = Coach(ref, GrabadorEngine(), coach_cfg(voice=True, training=True))
    coach.set_training_cue(frenadas[2]["pos"], "aprieta")

    con_correccion = [ev for ev in coach.events
                      if isinstance(ev.get("_voice"), str)
                      and ev["_voice"].endswith("aprieta")]
    assert len(con_correccion) == 1


# El retraso de la tarjeta de sonido
# ---------------------------------------------------------------------------


class EngineConRetraso(GrabadorEngine):
    """Un motor de audio que tarda en sacar el sonido, como el de Windows."""

    latency_ms = 200.0


def rodar_con_engine(circuito: str, engine, **overrides) -> list[dict]:
    coach = Coach(referencia(circuito), engine, coach_cfg(**overrides))
    anterior = None
    for f in ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=3).frames():
        if anterior is not None and f.lap_pos < anterior - 0.5:
            engine.giro += 1
        anterior = f.lap_pos
        engine.frame = f
        coach.on_frame(f)
    return [a for a in engine.avisos if a["giro"] == 1]


def test_la_latencia_declarada_no_mueve_los_avisos(circuito):
    """La cifra que declara la tarjeta NO se descuenta sola de la antelacion.

    Se descontaba, y el A/B en pista (Indianapolis) demostro que era un error:
    los 182.9 ms que declara el PC de juego son la SUGERENCIA del modo de alta
    latencia de PortAudio, no una medida del retraso real, y descontarlos
    adelantaba todos los avisos respecto al tacto validado en carrera. Solo se
    descuenta lo que el usuario pase por --audio-latency, medido de verdad.
    """
    sin = rodar_con_engine(circuito, GrabadorEngine(), countdown=0)
    con = rodar_con_engine(circuito, EngineConRetraso(), countdown=0)

    assert [(a["aviso"], a["pos"]) for a in sin] == \
           [(a["aviso"], a["pos"]) for a in con], (
        "la latencia declarada por el motor movio los avisos: eso se retiro "
        "tras el A/B de Indianapolis, no lo resucites sin validarlo en pista"
    )


def test_la_latencia_forzada_si_adelanta_el_aviso(circuito):
    """--audio-latency con un retraso MEDIDO si compensa: adelanta el aviso."""
    sin = rodar_con_engine(circuito, GrabadorEngine(), countdown=0)
    con = rodar_con_engine(circuito, GrabadorEngine(),
                           countdown=0, audio_latency=200.0)

    assert len(sin) == len(con)
    for a, b in zip(sin, con):
        assert a["aviso"] == b["aviso"]
        assert b["pos"] < a["pos"], "no se adelanto para compensar el retraso"


def test_la_compensacion_equivale_a_pedir_mas_antelacion(circuito):
    """Compensar 200 ms medidos tiene que dar lo mismo que pedir 0.2 s mas."""
    compensada = rodar_con_engine(circuito, GrabadorEngine(),
                                  countdown=0, lead=0.35, audio_latency=200.0)
    mas_lead = rodar_con_engine(circuito, GrabadorEngine(),
                                countdown=0, lead=0.55)

    assert [a["pos"] for a in compensada] == [a["pos"] for a in mas_lead]


def test_sin_retraso_todo_suena_donde_siempre(circuito):
    """El modo consola no tiene latencia: los golden no se pueden mover."""
    engine = GrabadorEngine()
    assert engine.latency_ms == 0.0
    assert rodar_con_engine(circuito, engine, countdown=0) == giro_completo(
        circuito, countdown=0
    )


@pytest.mark.parametrize("pico,clip", [
    (0.10, "p20"),   # nunca por debajo de p20: "frena 0%" no existe
    (0.34, "p40"),
    (0.45, "p40"),
    (0.55, "p60"),
    (0.95, "p100"),
    (1.00, "p100"),
])
def test_el_freno_se_dice_redondeado_a_tramos_de_20(pico, clip):
    """"Frena 73%" seria falsa precision: el pico es de OTRO piloto.

    Redondear a tramos de 20 % convierte un dato ajeno en una guia honesta.
    """
    assert Coach._pct_clip(pico) == clip
