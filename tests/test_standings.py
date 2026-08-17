"""Tests de standings.py: la clasificacion por clases y el iRating estimado.

No hay iRacing en el Mac, asi que todo esto trabaja sobre SessionSnapshot
fabricados a mano (los mismos que la fuente en vivo emitiria) y sobre un JSONL
grabado. Lo que se defiende:

- La formula del iRating es de SUMA CERO dentro de cada clase, el que gana
  sube, el que pierde baja, y el favorito gana MENOS ganando que el tapado.
  Si alguien "arregla" la formula y rompe esto, el numero de la pantalla es
  mentira, y el proyecto no da informacion falsa.
- El SoF de un campo uniforme es ese mismo iRating.
- Los bloques salen por clase, ordenados por posicion, con gap e intervalo
  referidos a la clase (no al lider absoluto).
- La grabacion y el replay son simetricos: lo que se graba es lo que vuelve.
"""

from __future__ import annotations

import math

import pytest

import standings as st
from source import CarState, ReplaySessionSource, SessionRecorder, SessionSnapshot


def _car(idx, num, name, cls, ir, cpos, f2=0.0, last=100.0, best=99.0, **kw):
    base = dict(
        idx=idx, number=str(num), name=name, class_id=cls, class_name=f"C{cls}",
        irating=ir, class_pos=cpos, pos=cpos, lap=10, lap_dist_pct=0.5,
        f2_time=f2, last_lap=last, best_lap=best, on_pit_road=False,
        in_world=True, is_me=False,
    )
    base.update(kw)
    return CarState(**base)


def _snap(cars, **kw):
    base = dict(t=0.0, session_type="Race", time_remain=1800.0,
                laps_total=24, laps_done=12, session_num=0)
    base.update(kw)
    return SessionSnapshot(cars=tuple(cars), **base)


# --- iRating -----------------------------------------------------------------


def test_el_irating_estimado_es_suma_cero():
    irs = [4300, 3900, 5100, 2800, 4700]
    cambios = st.irating_changes(irs, [3, 4, 1, 5, 2])
    assert abs(sum(cambios)) < 1e-6


def test_el_que_gana_sube_y_el_ultimo_baja():
    irs = [4000, 4000, 4000, 4000]
    cambios = st.irating_changes(irs, [1, 2, 3, 4])
    assert cambios[0] > 0 and cambios[-1] < 0
    assert cambios == sorted(cambios, reverse=True)


def test_el_favorito_gana_menos_que_el_tapado():
    # Mismo resultado (gana el primero), pero en un caso es el mas fuerte del
    # campo y en el otro el mas flojo: la sorpresa paga mas.
    favorito = st.irating_changes([6000, 4000, 4000, 4000], [1, 2, 3, 4])[0]
    tapado = st.irating_changes([2000, 4000, 4000, 4000], [1, 2, 3, 4])[0]
    assert 0 < favorito < tapado


def test_una_carrera_de_un_solo_coche_no_mueve_nada():
    assert st.irating_changes([4000], [1]) == [0.0]


def test_el_sof_de_un_campo_uniforme_es_su_irating():
    assert st.sof([3000, 3000, 3000]) == pytest.approx(3000)
    # Y con dispersión queda por debajo de la media: la formula pondera hacia
    # los flojos (es lo que hace iRacing).
    assert st.sof([2000, 4000]) < 3000


# --- Bloques por clase ---------------------------------------------------------


def test_los_bloques_salen_por_clase_y_ordenados():
    # Vuelta de 100 s: cada 1 % de pista es 1 s. El gap es DISTANCIA EN
    # PISTA (vuelta + fraccion), no CarIdxF2Time, que en carrera solo cambia
    # en los puntos de control y en practica es un delta de mejor vuelta.
    snap = _snap([
        _car(0, 92, "K. Estre", 1, 5100, 1, lap=10, lap_dist_pct=0.500, best=100.0),
        _car(1, 51, "A. Pier Guidi", 1, 4900, 2, lap=10, lap_dist_pct=0.478, best=101.0),
        _car(2, 4, "S. Sanchez", 1, 4300, 3, lap=10, lap_dist_pct=0.434, best=101.5, is_me=True),
        _car(3, 27, "J. Calado", 2, 3200, 1, lap=9, lap_dist_pct=0.900, best=110.0),
        _car(4, 71, "D. Muller", 2, 2900, 2, lap=9, lap_dist_pct=0.869, best=111.0),
    ])
    bloques = st.build_standings(snap)
    assert [b.class_id for b in bloques] == [1, 2]
    gt3, gt4 = bloques
    assert [r.number for r in gt3.rows] == ["92", "51", "4"]
    assert gt3.rows[2].is_me
    # El gap se mide al lider DE LA CLASE y con la mejor vuelta DE LA CLASE:
    # Calado lidera GT4 aunque vaya media vuelta detras del lider absoluto.
    assert gt4.rows[0].gap == pytest.approx(0.0)
    assert gt4.rows[1].gap == pytest.approx(0.031 * 110.0)
    assert gt4.rows[1].interval == pytest.approx(0.031 * 110.0)
    assert gt3.rows[1].gap == pytest.approx(2.2)
    assert gt3.rows[2].gap == pytest.approx(6.6)
    assert gt3.rows[2].interval == pytest.approx(4.4)
    assert gt3.sof == pytest.approx(st.sof([5100, 4900, 4300]))


def test_el_gap_es_en_vivo_y_puede_ser_negativo_o_de_vueltas():
    # En practica el orden es por mejor vuelta, asi que el segundo puede ir
    # FISICAMENTE por delante del primero: gap negativo, no un cero falso.
    snap = _snap([
        _car(0, 1, "A", 1, 4000, 1, lap=5, lap_dist_pct=0.10, best=100.0),
        _car(1, 2, "B", 1, 4000, 2, lap=5, lap_dist_pct=0.30, best=101.0),
        _car(2, 3, "C", 1, 4000, 3, lap=3, lap_dist_pct=0.50, best=102.0),
    ], session_type="Practice")
    (blk,) = st.build_standings(snap)
    assert blk.rows[1].gap == pytest.approx(-20.0)
    assert st.fmt_gap(blk.rows[1].gap) == "−20.0"
    # C va 1.6 vueltas detras: doblado, se dice en vueltas.
    assert blk.rows[2].laps_down == 1
    assert st.fmt_gap(blk.rows[2].gap, laps_down=blk.rows[2].laps_down) == "+1 L"


def test_sin_ninguna_vuelta_cronometrada_el_gap_no_revienta():
    snap = _snap([
        _car(0, 1, "A", 1, 4000, 1, lap=1, lap_dist_pct=0.20, best=-1.0, last=-1.0),
        _car(1, 2, "B", 1, 4000, 2, lap=1, lap_dist_pct=0.10, best=-1.0, last=-1.0),
    ])
    (blk,) = st.build_standings(snap)
    assert blk.rows[1].gap == pytest.approx(0.1 * st.FALLBACK_LAP_S)


def test_mi_clase_va_primero():
    snap = _snap([
        _car(0, 27, "J. Calado", 2, 3200, 1),
        _car(1, 4, "S. Sanchez", 1, 4300, 1, is_me=True),
    ])
    assert st.build_standings(snap)[0].class_id == 1


def test_el_delta_de_irating_va_por_clase():
    snap = _snap([
        _car(0, 92, "A", 1, 4000, 1),
        _car(1, 51, "B", 1, 4000, 2),
        _car(2, 27, "C", 2, 3000, 1),
        _car(3, 71, "D", 2, 3000, 2),
    ])
    gt3, gt4 = st.build_standings(snap)
    assert gt3.rows[0].delta > 0 > gt3.rows[1].delta
    assert abs(gt3.rows[0].delta + gt3.rows[1].delta) < 1e-6
    assert abs(gt4.rows[0].delta + gt4.rows[1].delta) < 1e-6


def test_la_mejor_vuelta_de_la_clase_se_marca():
    snap = _snap([
        _car(0, 92, "A", 1, 4000, 1, best=106.0),
        _car(1, 51, "B", 1, 4000, 2, best=105.8),
    ])
    (gt3,) = st.build_standings(snap)
    assert not gt3.rows[0].fastest and gt3.rows[1].fastest


def test_los_coches_fuera_de_la_sesion_no_cuentan():
    # Un espectador o un DNS (nunca en pista) no puntua ni aparece: contarlo
    # inflaria el N de la formula y el iRating de todos.
    snap = _snap([
        _car(0, 92, "A", 1, 4000, 1),
        _car(1, 51, "B", 1, 4000, 2),
        _car(2, 7, "Fantasma", 1, 9000, 0, in_world=False, lap=0),
    ])
    (gt3,) = st.build_standings(snap)
    assert [r.number for r in gt3.rows] == ["92", "51"]
    assert gt3.n == 2


def test_la_ventana_alrededor_de_mi_siempre_me_incluye():
    cars = [_car(i, i, f"P{i}", 1, 4000, i + 1, f2=float(i)) for i in range(20)]
    cars[13] = _car(13, 13, "Yo", 1, 4000, 14, f2=13.0, is_me=True)
    (blk,) = st.build_standings(_snap(cars))
    visibles = st.visible_rows(blk, top=3, around=2)
    nums = [r.number for r in visibles]
    assert nums[:3] == ["0", "1", "2"]
    assert "13" in nums
    assert nums[-5:] == ["11", "12", "13", "14", "15"]
    assert len(visibles) == 8


# --- Grabar y reproducir --------------------------------------------------------


def test_grabar_y_reproducir_es_simetrico(tmp_path):
    snap = _snap([_car(0, 92, "K. Estre", 1, 5100, 1, is_me=True)], t=1.5)
    path = tmp_path / "sesion.jsonl"
    with SessionRecorder(path) as rec:
        rec.write(snap)
        rec.write(_snap([_car(0, 92, "K. Estre", 1, 5100, 1)], t=2.0))
    src = ReplaySessionSource(str(path), speed=0)
    vueltos = list(src.snapshots())
    assert len(vueltos) == 2
    assert vueltos[0] == snap
    assert vueltos[1].t == 2.0


def test_los_coches_sin_irating_no_puntuan_ni_rompen():
    # Practica con IA: pilotos con IRating 0. Dos ceros en la misma clase
    # dividian por cero y tumbaban el overlay en el PC (ago-2026). Los
    # desconocidos salen como None y los demas se calculan entre ellos.
    cambios = st.irating_changes([4000, 0, 3000, 0], [1, 2, 3, 4])
    assert cambios[1] is None and cambios[3] is None
    assert cambios[0] > 0 > cambios[2]
    assert abs(cambios[0] + cambios[2]) < 1e-6
    assert st.sof([4000, 0, 3000, 0]) == pytest.approx(st.sof([4000, 3000]))
    assert st.fmt_delta(None) == "—" and st.fmt_ir(0) == "—"
    # Y una clase entera de IA no rompe nada.
    assert st.irating_changes([0, 0], [1, 2]) == [None, None]
    assert st.sof([0, 0]) == 0.0


# ---------------------------------------------------------------------------
# La posicion del panel se recuerda entre sesiones
# ---------------------------------------------------------------------------


def test_la_posicion_del_overlay_se_recuerda(tmp_path):
    """Cada vez que se abria, el panel volvia a la esquina: se guarda al soltar
    el arrastre y se lee al arrancar. Un fichero roto o ausente = primera vez."""
    import overlay as ov

    f = tmp_path / "pos.json"
    assert ov.load_pos(f) is None
    ov.save_pos(640, 120, f)
    assert ov.load_pos(f) == (640, 120)
    f.write_text("{basura")
    assert ov.load_pos(f) is None
