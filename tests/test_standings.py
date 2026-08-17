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


# ---------------------------------------------------------------------------
# En carrera el orden es la posicion REAL en pista, no la del SDK
# ---------------------------------------------------------------------------


def test_en_carrera_manda_la_posicion_en_pista_no_la_del_sdk():
    """CarIdxClassPosition solo cambia en los puntos de cronometraje: entre
    dos, un adelantamiento no se ve. Sergio lo noto en carrera como "cierto
    delay". El orden en carrera es vuelta + LapDistPct; el numero del SDK
    queda de desempate cuando dos coches van clavados."""
    snap = _snap([
        _car(0, 1, "A", 1, 4000, 1, lap=10, lap_dist_pct=0.40),
        _car(1, 2, "B", 1, 4000, 2, lap=10, lap_dist_pct=0.45),  # ya ha pasado a A
        _car(2, 3, "C", 1, 4000, 3, lap=9, lap_dist_pct=0.90),
    ])
    (blk,) = st.build_standings(snap)
    assert [r.number for r in blk.rows] == ["2", "1", "3"]
    assert [r.pos for r in blk.rows] == [1, 2, 3]
    # El gap se mide al que va DELANTE de verdad.
    assert blk.rows[1].gap == pytest.approx(0.05 * 99.0)


def test_en_practica_se_sigue_ordenando_por_mejor_vuelta():
    snap = _snap([
        _car(0, 1, "A", 1, 4000, 2, lap=10, lap_dist_pct=0.90, best=101.0),
        _car(1, 2, "B", 1, 4000, 1, lap=3, lap_dist_pct=0.10, best=100.0),
    ], session_type="Practice")
    (blk,) = st.build_standings(snap)
    assert [r.number for r in blk.rows] == ["2", "1"]


def test_dos_coches_pegados_no_bailan():
    """Rueda a rueda, a 2 Hz, dos coches se alternan por centimetros y la
    tabla parpadearia. Con el orden anterior a mano, un intercambio menor
    que HYST_LAP no se aplica; uno mayor si."""
    def snap(a_pct, b_pct):
        return _snap([
            _car(0, 1, "A", 1, 4000, 1, lap=10, lap_dist_pct=a_pct),
            _car(1, 2, "B", 1, 4000, 2, lap=10, lap_dist_pct=b_pct),
        ])
    (blk,) = st.build_standings(snap(0.500, 0.499))
    prev = st.ranks([blk])
    assert prev == {0: 1, 1: 2}
    # B se pone 0.0005 vueltas por delante (2 m): sigue el orden anterior.
    (blk,) = st.build_standings(snap(0.500, 0.5005), prev)
    assert [r.number for r in blk.rows] == ["1", "2"]
    # B se va a 0.01 (unos 45 m): ahora si.
    (blk,) = st.build_standings(snap(0.500, 0.510), prev)
    assert [r.number for r in blk.rows] == ["2", "1"]
    # Y sin orden anterior no hay histeresis: manda la pista.
    (blk,) = st.build_standings(snap(0.500, 0.5005))
    assert [r.number for r in blk.rows] == ["2", "1"]


# ---------------------------------------------------------------------------
# Relatives: quien tengo delante y detras EN PISTA, sea de la clase que sea
# ---------------------------------------------------------------------------


def _rel_snap():
    # Vuelta de 100 s. Yo (idx 2) en el 50 % de la vuelta 10.
    def car(*a, **kw):
        kw.setdefault("best", 100.0)
        return _car(*a, **kw)
    return _snap([
        car(0, 92, "Lider", 1, 5000, 1, lap=11, lap_dist_pct=0.52),   # me dobla: 2 s delante
        car(1, 51, "Delante", 1, 4900, 2, lap=10, lap_dist_pct=0.56),  # misma vuelta, 6 s
        car(2, 4, "Yo", 1, 4300, 3, lap=10, lap_dist_pct=0.50, is_me=True),
        car(3, 27, "GT4", 2, 3200, 1, lap=9, lap_dist_pct=0.47),      # otra clase, 3 s detras
        car(4, 71, "Doblado", 1, 2900, 4, lap=9, lap_dist_pct=0.45),   # yo le doblo, 5 s detras
        car(5, 8, "Lejos", 1, 4000, 5, lap=10, lap_dist_pct=0.10),     # 40 s detras
        car(6, 9, "Meta", 2, 3000, 2, lap=9, lap_dist_pct=0.99),      # 0.49 delante / 0.51 detras
        car(7, 10, "Boxes", 1, 4000, 6, lap=10, lap_dist_pct=0.70, on_pit_road=True),
        car(8, 11, "DNS", 1, 4000, 0, lap=0, lap_dist_pct=0.51, in_world=False),
    ])


def test_el_relative_ordena_por_pista_con_todas_las_clases_y_yo_en_medio():
    rows = st.build_relative(_rel_snap(), around=2)
    assert [r.car.number for r in rows] == ["51", "92", "4", "27", "71"]
    assert rows[2].is_me
    assert rows[2].rel_s == pytest.approx(0.0)
    assert rows[1].rel_s == pytest.approx(2.0)   # el lider, aunque vaya una vuelta mas
    assert rows[0].rel_s == pytest.approx(6.0)
    assert rows[3].rel_s == pytest.approx(-3.0)
    assert rows[4].rel_s == pytest.approx(-5.0)


def test_el_relative_dice_quien_te_dobla_y_a_quien_doblas():
    rows = st.build_relative(_rel_snap(), around=2)
    by = {r.car.number: r for r in rows}
    assert by["92"].laps_diff == 1     # va una vuelta por delante: me esta doblando
    assert by["71"].laps_diff == -1    # va una vuelta por detras: le doblo yo
    assert by["51"].laps_diff == 0
    assert by["27"].laps_diff == -1    # otra clase, pero en pista le doblo: eso es lo que importa
    assert by["4"].laps_diff == 0


def test_el_relative_da_la_vuelta_a_meta_y_ignora_a_quien_no_esta():
    # Con ventana ancha entran los lejanos. "Meta" (99 %) esta a 0.49 vueltas
    # por delante y a 0.51 por detras: gana el camino corto, delante.
    rows = st.build_relative(_rel_snap(), around=10)
    nums = [r.car.number for r in rows]
    assert "11" not in nums                    # DNS: nunca en pista
    assert nums.index("9") < nums.index("4")   # Meta va delante
    by = {r.car.number: r for r in rows}
    assert by["9"].rel_s == pytest.approx(49.0)
    assert by["8"].rel_s == pytest.approx(-40.0)
    assert by["10"].car.on_pit_road


def test_el_relative_sin_mi_no_revienta():
    snap = _snap([_car(0, 92, "A", 1, 4000, 1)])
    assert st.build_relative(snap, around=3) == []


def test_las_grabaciones_viejas_sin_licencia_se_siguen_leyendo():
    # CarState gano `license` (LicString del SDK) despues de grabar sesiones:
    # un JSONL anterior no lo trae y tiene que cargar igual.
    line = ('{"t":0.0,"session_type":"Race","time_remain":10.0,"laps_total":2,'
            '"laps_done":1,"session_num":0,"cars":[{"idx":0,"number":"1","name":"A",'
            '"class_id":1,"class_name":"GT3","irating":4000,"class_pos":1,"pos":1,'
            '"lap":1,"lap_dist_pct":0.5,"f2_time":0.0,"last_lap":100.0,"best_lap":99.0,'
            '"on_pit_road":false,"in_world":true,"is_me":true}]}')
    snap = SessionSnapshot.from_json(line)
    assert snap.cars[0].license == ""
    assert snap.air_temp is None and snap.track_temp is None


def test_cada_panel_recuerda_su_posicion(tmp_path):
    import overlay as ov

    f = tmp_path / "pos.json"
    ov.save_pos(640, 120, f)                       # el de siempre: la clasificacion
    ov.save_pos(1500, 300, f, view="relative")
    assert ov.load_pos(f) == (640, 120)
    assert ov.load_pos(f, view="relative") == (1500, 300)
    # El formato viejo ({"x","y"}) sigue valiendo para la clasificacion.
    f.write_text('{"x": 5, "y": 6}')
    assert ov.load_pos(f) == (5, 6)
    assert ov.load_pos(f, view="relative") is None


# ---------------------------------------------------------------------------
# El relative va en TIEMPO del SDK (CarIdxEstTime), no en distancia
# ---------------------------------------------------------------------------


def test_el_relative_usa_el_tiempo_estimado_del_sdk_si_lo_hay():
    """Sergio en pista: 'en cada curva el relative baja 2-3 s y vuelve a
    subir'. Convertir distancia a segundos con la mejor vuelta supone
    velocidad constante: 100 m en recta son 1.4 s y en una horquilla 6.
    CarIdxEstTime ya es tiempo hasta ese punto de la pista (por la vuelta
    rapida de cada coche): la diferencia es el relative de verdad."""
    snap = _snap([
        _car(0, 1, "Delante", 1, 4000, 1, lap=10, lap_dist_pct=0.55, best=100.0, est_time=63.0),
        _car(1, 2, "Yo", 1, 4000, 2, lap=10, lap_dist_pct=0.50, best=100.0, est_time=55.0, is_me=True),
        _car(2, 3, "Detras", 1, 4000, 3, lap=10, lap_dist_pct=0.45, best=100.0, est_time=52.0),
    ])
    rows = st.build_relative(snap, around=2)
    by = {r.car.number: r for r in rows}
    assert by["1"].rel_s == pytest.approx(8.0)    # y no 5.0 (0.05 x 100)
    assert by["3"].rel_s == pytest.approx(-3.0)   # y no -5.0


def test_el_relative_con_est_time_da_la_vuelta_a_meta():
    # Yo al 98 %, el otro al 2 % de la vuelta siguiente: 4 s por delante,
    # aunque su EstTime (2 s) sea menor que el mio (97 s).
    snap = _snap([
        _car(0, 1, "Delante", 1, 4000, 1, lap=11, lap_dist_pct=0.02, best=100.0, est_time=2.0),
        _car(1, 2, "Yo", 1, 4000, 2, lap=10, lap_dist_pct=0.98, best=100.0, est_time=97.0, is_me=True),
        _car(2, 3, "Detras", 1, 4000, 3, lap=10, lap_dist_pct=0.94, best=100.0, est_time=93.0),
    ])
    rows = st.build_relative(snap, around=2)
    by = {r.car.number: r for r in rows}
    assert by["1"].rel_s == pytest.approx(5.0)
    assert by["3"].rel_s == pytest.approx(-4.0)
    assert [r.car.number for r in rows] == ["1", "2", "3"]


def test_sin_est_time_el_relative_cae_a_distancia():
    # Grabaciones viejas (est_time = 0 en todos): sigue valiendo lo de antes.
    rows = st.build_relative(_rel_snap(), around=2)
    assert rows[0].rel_s == pytest.approx(6.0)


def test_los_incidentes_y_la_serie_viajan_en_la_foto():
    snap = _snap([_car(0, 1, "A", 1, 4000, 1, incidents=7, is_me=True)], series_id=447)
    back = SessionSnapshot.from_json(snap.to_json())
    assert back.cars[0].incidents == 7 and back.series_id == 447


def test_el_nombre_de_la_serie_sale_de_un_fichero_local(tmp_path):
    # El SDK solo da SeriesID (numero): el nombre lo pone un series.json que
    # se rellena una vez por serie. Sin entrada, None: el overlay lo canta.
    f = tmp_path / "series.json"
    assert st.series_name(447, f) is None
    f.write_text('{"447": "GT3 Regional Europe"}', encoding="utf-8")
    assert st.series_name(447, f) == "GT3 Regional Europe"
    assert st.series_name(0, f) is None
    f.write_text("{basura")
    assert st.series_name(447, f) is None
