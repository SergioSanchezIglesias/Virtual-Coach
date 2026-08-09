"""El analisis post-vuelta: por que has ido lento, no solo cuanto.

Distingue dos errores que dan EL MISMO sintoma (pasar lento por la curva) y
que se corrigen al reves:

  - frenaste pronto y suave  -> llegas lento pero limpio  -> frena mas tarde
  - frenaste tarde y a saco  -> el ABS trabaja, la rueda no gira, te vas largo
                             -> frena antes y mas suave

Desde dentro del coche se sienten parecido. El ABS es lo que los separa.
"""

from __future__ import annotations

import pytest

from review import LapReview, diagnose, worst


def zona(**kw) -> dict:
    """Una frenada de la referencia, con los valores por defecto sanos."""
    base = {"type": "brake", "pos": 0.50, "speed_ms": 60.0, "peak": 0.9,
            "gear": 3, "abs_s": 1.50, "min_speed_ms": 25.0}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# El diagnostico, caso a caso
# ---------------------------------------------------------------------------


def test_mucho_mas_abs_y_mas_lento_es_pasarse_de_frenada():
    """El error caro: pides mas freno del que hay y el coche no gira.

    Una rueda al limite de frenada no genera agarre lateral, asi que te vas
    largo. La correccion es CONTRARIA a la intuicion de "he ido lento, freno
    mas tarde": hay que frenar ANTES y mas suave.
    """
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=2.90, min_speed_ms=23.0)
    assert d.verdict == "passed"
    assert d.cue == "suave"


def test_menos_abs_y_mas_lento_es_sobrarte_margen():
    """El error barato: llegas lento pero limpio. Puedes apretar mas."""
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=0.20, min_speed_ms=23.0)
    assert d.verdict == "short"
    assert d.cue == "aprieta"


def test_parecido_a_la_referencia_no_dice_nada():
    """Si vas bien, silencio. Un coach que habla siempre acaba apagado."""
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=1.60, min_speed_ms=24.9)
    assert d.verdict == "ok"
    assert d.cue is None


def test_pasar_mas_rapido_que_la_referencia_no_es_un_error():
    """Vas mejor que el rapido. Eso no se corrige, se celebra en silencio."""
    d = diagnose(zona(min_speed_ms=25.0), abs_s=1.55, min_speed_ms=27.0)
    assert d.verdict == "ok"


def test_mas_abs_pero_igual_de_rapido_es_ir_al_limite():
    """Trabajas mas el ABS pero el resultado es el mismo: vas al limite.

    No es un error que corregir con la voz, pero si conviene saberlo: asi se
    castigan las gomas.
    """
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=2.60, min_speed_ms=25.1)
    assert d.verdict == "limit"
    assert d.cue is None


def test_el_diagnostico_guarda_los_numeros_que_lo_justifican():
    """Nada de veredictos sin datos: el resumen tiene que poder ensenarlos."""
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=2.90, min_speed_ms=23.0)
    assert d.abs_s == 2.90
    assert d.ref_abs_s == 1.50
    assert d.delta_kmh == pytest.approx((23.0 - 25.0) * 3.6, abs=0.01)


@pytest.mark.parametrize("ref_abs,mio_abs", [(0.05, 0.35), (0.02, 0.30)])
def test_en_frenadas_flojas_no_basta_con_el_salto_relativo(ref_abs, mio_abs):
    """Trampa: donde la referencia casi no usa ABS, todo es "muchas veces mas".

    La frenada 5 de Hockenheim tiene 0.05 s de ABS. Pasar a 0.35 s son SIETE
    veces mas, pero en absoluto son tres decimas: ruido. Sin un minimo
    absoluto, el coach cantaria un error en cada roce del pedal.
    """
    d = diagnose(zona(abs_s=ref_abs, min_speed_ms=25.0),
                 abs_s=mio_abs, min_speed_ms=24.0)
    assert d.verdict == "ok", f"falso positivo con {ref_abs}s -> {mio_abs}s"


# ---------------------------------------------------------------------------
# La vuelta entera
# ---------------------------------------------------------------------------


def frame(pos, speed=60.0, brake=0.0, throttle=1.0, abs_on=False):
    from source import Frame
    return Frame(t=0.0, lap_pos=pos, speed_ms=speed, brake=brake,
                 throttle=throttle, gear=3, lap=0, on_track=True,
                 abs_active=abs_on)


def test_la_vuelta_mide_cada_frenada_por_separado():
    """Dos frenadas en la vuelta, cada una con su cuenta."""
    eventos = [zona(pos=0.20), zona(pos=0.60)]
    review = LapReview(eventos)

    for i in range(100):
        p = i / 100
        frenando = 0.18 < p < 0.25 or 0.58 < p < 0.65
        review.on_frame(frame(p, brake=0.9 if frenando else 0.0,
                              speed=20.0 if frenando else 60.0,
                              abs_on=frenando and p < 0.30))

    resultado = review.finish()
    assert len(resultado) == 2
    assert resultado[0].abs_s > 0, "no midio el ABS de la primera frenada"
    assert resultado[1].abs_s == 0.0, "conto ABS donde no lo hubo"


def test_una_vuelta_incompleta_no_inventa_diagnosticos():
    """Si entras a boxes a media vuelta, las frenadas que no hiciste no salen."""
    eventos = [zona(pos=0.20), zona(pos=0.80)]
    review = LapReview(eventos)
    for i in range(50):  # solo media vuelta
        review.on_frame(frame(i / 100, brake=0.9 if 0.18 < i / 100 < 0.25 else 0.0))

    resultado = review.finish()
    assert all(d.pos < 0.5 for d in resultado), (
        "diagnostico de una curva por la que no se paso"
    )


def test_lo_peor_de_la_vuelta_es_lo_que_se_canta():
    """Solo se dice UNA cosa: la que mas cuesta. Lo demas es ruido."""
    diagnosticos = [
        diagnose(zona(pos=0.2, min_speed_ms=25.0), abs_s=1.55, min_speed_ms=24.9),
        diagnose(zona(pos=0.5, min_speed_ms=25.0), abs_s=2.90, min_speed_ms=20.0),
        diagnose(zona(pos=0.8, min_speed_ms=25.0), abs_s=0.10, min_speed_ms=24.0),
    ]
    from review import worst

    peor = worst(diagnosticos)
    assert peor.pos == 0.5, "no eligio la curva donde mas se pierde"


# ---------------------------------------------------------------------------
# Sobre las vueltas reales
# ---------------------------------------------------------------------------


def rodar_review(circuito: str, retoque=None):
    """Pasa una vuelta real por el analisis, con un retoque opcional."""
    import dataclasses

    from conftest import CSV, referencia
    from source import ReplaySource

    review = LapReview(referencia(circuito)["events"])
    for f in ReplaySource(str(CSV[circuito]), speed=0.0, max_laps=1).frames():
        review.on_frame(retoque(f) if retoque else f)
    return review.finish()


def test_la_referencia_contra_si_misma_no_tiene_un_solo_error(circuito):
    """La prueba de fuego contra los falsos positivos.

    Si le das al analisis la MISMA vuelta que le sirve de referencia, no puede
    encontrar nada que corregir. Si encontrara algo, estaria inventandose
    errores, y un coach que te corrige cuando lo has hecho bien es peor que no
    tener coach.
    """
    diagnosticos = rodar_review(circuito)

    assert diagnosticos, "no analizo ninguna frenada"
    assert all(d.verdict == "ok" for d in diagnosticos), (
        [f"{d.pos:.3f}:{d.verdict}" for d in diagnosticos if d.verdict != "ok"]
    )
    assert worst(diagnosticos) is None


def estropear(circuito: str, indice: int, *, abs_on: bool, factor: float):
    """Devuelve un retoque que estropea UNA zona de frenada concreta.

    La zona se toma de la propia referencia en vez de escribir el rango a
    mano: el punto mas lento de una curva puede caer muy al final del tramo
    (en la del 42 % de Hockenheim cae en el ultimo 5 % de la ventana), y un
    rango tecleado a ojo se lo deja fuera sin que se note.
    """
    import dataclasses

    from conftest import referencia
    from review import LapReview

    frenadas = [e for e in referencia(circuito)["events"] if e["type"] == "brake"]
    zona_pos = frenadas[indice]["pos"]
    ventana = LapReview([]).window

    def retoque(f):
        if (f.lap_pos - zona_pos) % 1.0 <= ventana:
            return dataclasses.replace(f, abs_active=abs_on,
                                       speed_ms=f.speed_ms * factor)
        return f

    return zona_pos, retoque


def test_detecta_una_pasada_de_frenada_inyectada_en_datos_reales():
    """Y ahora al reves: con un error de verdad, tiene que cantarlo.

    Se coge la vuelta buena de Hockenheim y se estropea UNA curva: mas ABS y
    mas lento, que es exactamente pasarse de frenada.
    """
    pos, retoque = estropear("hockenheim", 3, abs_on=True, factor=0.85)
    peor = worst(rodar_review("hockenheim", retoque=retoque))

    assert peor is not None, "no detecto la pasada de frenada"
    assert peor.pos == pytest.approx(pos), f"senalo la curva equivocada: {peor.pos}"
    assert peor.verdict == "passed"
    assert peor.cue == "suave"


def test_detecta_que_te_sobra_margen():
    """El error contrario: frenas de menos y pasas lento, pero limpio."""
    pos, retoque = estropear("hockenheim", 2, abs_on=False, factor=0.85)
    peor = worst(rodar_review("hockenheim", retoque=retoque))

    assert peor is not None, "no detecto que sobraba margen"
    assert peor.pos == pytest.approx(pos)
    assert peor.verdict == "short"
    assert peor.cue == "aprieta"


# ---------------------------------------------------------------------------
# Lo que fallo en la primera sesion real
# ---------------------------------------------------------------------------


def test_el_diagnostico_dice_el_NUMERO_de_frenada():
    """"Frenada @ 58.6%" no significa nada al volante.

    Al procesar la vuelta ya se numeran las siete frenadas; el resumen tiene
    que hablar el mismo idioma. Un porcentaje no lo puedes reconocer mientras
    conduces.
    """
    review = LapReview([zona(pos=0.20), zona(pos=0.60), zona(pos=0.85)])
    assert [z["index"] for z in review.zones] == [1, 2, 3]

    d = diagnose(review.zones[1], abs_s=2.9, min_speed_ms=20.0)
    assert d.index == 2
    assert "Frenada 2" in d.describe()


def test_una_zona_pasada_a_paso_de_boxes_no_se_analiza():
    """LO QUE APARECIO EN LA PRIMERA SESION REAL, y era absurdo:

        Frenada @ 3.6%   ABS 0.00s (el 0.80s)   -162.5 km/h
           -> te sobra margen: puedes frenar mas tarde o mas fuerte

    Ciento sesenta y dos km/h mas lento no es un error de pilotaje: es que
    estaba saliendo de boxes a 61 por hora. Una diferencia asi significa que
    esa curva no la hiciste rodando, y no hay nada que diagnosticar.
    """
    d = diagnose(zona(min_speed_ms=47.4), abs_s=0.0, min_speed_ms=2.3)
    assert d.verdict == "skip"
    assert d.cue is None


def test_una_diferencia_normal_si_se_analiza():
    """El filtro no puede cargarse los errores de verdad, que son pequenos."""
    d = diagnose(zona(abs_s=1.50, min_speed_ms=25.0), abs_s=0.2, min_speed_ms=22.5)
    assert d.verdict == "short"


def test_las_zonas_descartadas_no_llegan_al_resumen():
    eventos = [zona(pos=0.20, min_speed_ms=40.0), zona(pos=0.60, min_speed_ms=25.0)]
    review = LapReview(eventos)

    for i in range(100):
        p = i / 100
        # Por la primera zona se pasa a paso de tortuga (saliendo de boxes).
        v = 3.0 if 0.20 <= p < 0.25 else 22.0
        review.on_frame(frame(p, speed=v, brake=0.9))

    for d in review.finish():
        assert d.verdict != "skip", "una zona sin sentido llego al resumen"


def test_el_resumen_no_suelta_una_lista_interminable():
    """En la sesion real salieron CUATRO consejos y los cuatro iguales.

    Cuando todo dice lo mismo no informas, haces ruido. Se dan los peores y
    ya, ordenados de mas a menos grave.
    """
    from review import top

    muchos = [
        diagnose(zona(pos=0.1 * i, min_speed_ms=25.0), abs_s=0.1,
                 min_speed_ms=25.0 - i)
        for i in range(1, 6)
    ]
    peores = top(muchos, limit=2)

    assert len(peores) == 2
    assert peores[0].delta_kmh < peores[1].delta_kmh, "no estan ordenados"
    assert peores[0].delta_kmh == min(d.delta_kmh for d in muchos)


def test_si_no_hay_nada_grave_el_resumen_va_vacio():
    from review import top

    limpios = [diagnose(zona(pos=0.2), abs_s=1.55, min_speed_ms=25.0)]
    assert top(limpios) == []


def test_si_la_vuelta_esta_limpia_no_hay_nada_que_cantar():
    limpios = [diagnose(zona(pos=0.2), abs_s=1.55, min_speed_ms=25.0),
               diagnose(zona(pos=0.7), abs_s=1.45, min_speed_ms=25.1)]
    from review import worst

    assert worst(limpios) is None
