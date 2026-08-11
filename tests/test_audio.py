"""Los sonidos: que se distingan, que no hagan click y que no se pisen.

Aqui no se comprueba "que suene algo", se comprueba QUE suena: la frecuencia
real de cada tono, medida sobre el buffer. Un aviso que no se distingue de
otro es un aviso que no sirve, y eso no se ve leyendo el codigo.
"""

from __future__ import annotations

import numpy as np
import pytest

from coach import SR, Coach, make_tone
from conftest import coach_cfg


class FakeAudio:
    """Motor que finge ser de audio (no es ConsoleEngine) y guarda buffers."""

    latency_ms = 0.0

    def __init__(self):
        self.played: list[np.ndarray] = []

    def play(self, tone):
        self.played.append(tone)

    def close(self):
        pass


def frecuencia(buf: np.ndarray) -> float:
    """Frecuencia dominante de un buffer, por FFT."""
    espectro = np.abs(np.fft.rfft(buf))
    return float(np.fft.rfftfreq(len(buf), 1 / SR)[int(np.argmax(espectro))])


def coach_con_audio(**overrides) -> tuple[Coach, FakeAudio]:
    engine = FakeAudio()
    ref = {"track_length_m": 4000.0, "events": []}
    return Coach(ref, engine, coach_cfg(**overrides)), engine


# ---------------------------------------------------------------------------
# Los tonos base
# ---------------------------------------------------------------------------


def test_cada_tipo_de_aviso_suena_a_su_frecuencia():
    coach, _ = coach_con_audio()
    esperado = {"brake": 620.0, "throttle": 1050.0, "lift": 820.0, "manage": 720.0}
    for tipo, f in esperado.items():
        medida = frecuencia(coach.tones[tipo])
        assert medida == pytest.approx(f, abs=15.0), f"{tipo} suena a {medida:.0f} Hz"


def test_los_tonos_no_hacen_click():
    """Arrancar o cortar un seno en seco produce un click en CADA aviso.

    A 39 avisos por vuelta acabas odiando el programa, asi que la envolvente
    tiene que entrar y salir desde cero.
    """
    tono = make_tone(620.0, 90)
    assert abs(tono[0]) < 1e-6
    assert abs(tono[-1]) < 1e-6

    borde = int(SR * 0.006)
    assert np.all(np.abs(np.diff(tono[:borde])) < 0.05), "ataque demasiado brusco"


# ---------------------------------------------------------------------------
# La cuenta atras: tiene que distinguirse del pitido de frenada
# ---------------------------------------------------------------------------


def test_los_ticks_suben_de_frecuencia():
    """Cada tick suena mas agudo que el anterior.

    Asi sabes en cual vas SIN contar: el mas agudo es el ultimo, y el pitido
    remata la escala. Es informacion extra por el mismo numero de sonidos.
    """
    coach, _ = coach_con_audio(countdown=3)
    frecuencias = [frecuencia(t) for t in coach.count_tones]

    assert len(frecuencias) == 3
    assert frecuencias == sorted(frecuencias), f"no suben: {frecuencias}"
    assert len(set(frecuencias)) == 3, f"hay ticks repetidos: {frecuencias}"


def test_ningun_tick_se_confunde_con_el_pitido_de_freno():
    """El motivo del cambio: en pista los ticks y el pitido sonaban igual.

    Compartian los 620 Hz del freno y solo se diferenciaban en duracion y
    volumen. Con ruido de motor y la cabeza en la curva, eso es una diferencia
    demasiado fina. Ahora todos los ticks quedan claramente por debajo.
    """
    coach, _ = coach_con_audio(countdown=3)
    freno = frecuencia(coach.tones["brake"])

    for i, tick in enumerate(coach.count_tones):
        f = frecuencia(tick)
        assert f < freno * 0.95, (
            f"el tick {i + 1} suena a {f:.0f} Hz, demasiado cerca de los "
            f"{freno:.0f} Hz del freno"
        )


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8])
def test_la_rampa_nunca_alcanza_al_pitido(n):
    """Sea cual sea el numero de ticks, la escala cabe debajo del freno.

    Con un factor fijo por tick, un --countdown 5 se saldria por arriba y el
    ultimo tick sonaria mas agudo que la propia frenada. Repartir la rampa
    entre la base y el tono del freno lo hace imposible por construccion.
    """
    coach, _ = coach_con_audio(countdown=n)
    freno = frecuencia(coach.tones["brake"])

    assert len(coach.count_tones) == n
    assert all(frecuencia(t) < freno for t in coach.count_tones)


def test_los_ticks_siguen_siendo_cortos_y_bajitos():
    """La escala cambia la ALTURA, no la presencia. Un tick no es un aviso."""
    coach, _ = coach_con_audio(countdown=3)
    pitido = coach.tones["brake"]

    for tick in coach.count_tones:
        assert len(tick) < len(pitido), "el tick dura tanto como el aviso"
        assert np.abs(tick).max() < np.abs(pitido).max(), "el tick suena igual de alto"


# ---------------------------------------------------------------------------
# Volumen de los pitidos
# ---------------------------------------------------------------------------


def test_por_defecto_el_pitido_suena_como_el_dia_de_la_carrera():
    """El 0.35 es el volumen con el que se corrio y se quedo segundo.

    Que ahora sea ajustable no puede cambiar lo que oye quien no toca nada:
    el defecto es el afinado validado, no un numero nuevo.
    """
    coach, _ = coach_con_audio()
    for tipo, tono in coach.tones.items():
        assert np.abs(tono).max() == pytest.approx(0.35, abs=0.01), f"{tipo} cambio de volumen"


def test_el_volumen_de_los_pitidos_se_puede_ajustar():
    """Los cuatro tonos escalan JUNTOS con --volume.

    Juntos importa: sus alturas relativas son lo que te deja distinguir freno
    de gas sin pensar. Si uno escalara y otro no, subir el volumen borraria esa
    diferencia justo cuando mas se necesita (con ruido de motor encima).
    """
    normal, _ = coach_con_audio(volume=0.35)
    fuerte, _ = coach_con_audio(volume=0.70)

    for tipo in normal.tones:
        pico_n = np.abs(normal.tones[tipo]).max()
        pico_f = np.abs(fuerte.tones[tipo]).max()
        assert pico_f == pytest.approx(pico_n * 2, rel=1e-3), f"{tipo} no escalo"


def test_subir_el_pitido_no_lo_deja_saturado():
    """El motor de audio SUMA los sonidos (voz + pitido + tick a la vez).

    Con el tope del ajuste, un pitido solo ya rozaria el 1.0 y cualquier suma
    clipa. El limite existe para que el aviso siga siendo un tono limpio y no
    un chasquido.
    """
    coach, _ = coach_con_audio(volume=1.0)
    for tipo, tono in coach.tones.items():
        assert np.abs(tono).max() <= 1.0, f"{tipo} se sale de rango"


# ---------------------------------------------------------------------------
# Volumen de la voz
# ---------------------------------------------------------------------------


def test_la_voz_se_puede_atenuar():
    """La voz se oia mas alta que los pitidos rodando en Hockenheim.

    No es que los clips vengan saturados (sus picos, 0.30-0.56, son
    comparables al 0.35 del tono). Es que el oido integra la sonoridad en unos
    200 ms y el pitido dura 90: se percibe mas bajo de lo que mide. Como es un
    ajuste perceptual y no matematico, se expone como parametro y se afina al
    oido, en vez de normalizar por pico (que lo empeoraria).
    """
    ref = {
        "track_length_m": 4000.0,
        "events": [{"type": "brake", "pos": 0.5, "speed_ms": 50.0,
                    "peak": 0.8, "gear": 3}],
    }
    alta = Coach(ref, FakeAudio(), coach_cfg(voice=True, voice_volume=1.0))
    baja = Coach(dict(ref, events=[dict(ref["events"][0])]), FakeAudio(),
                 coach_cfg(voice=True, voice_volume=0.5))

    pico_alta = np.abs(alta.events[0]["_voice"]).max()
    pico_baja = np.abs(baja.events[0]["_voice"]).max()

    assert pico_baja == pytest.approx(pico_alta * 0.5, rel=1e-3)


def test_la_frase_de_voz_no_se_alarga_sin_control(circuito):
    """La voz se genero un 15 % mas lenta porque costaba entenderla rodando.

    Pero una voz mas lenta dura mas, y la frase tiene que caber ANTES de la
    curva: voz + cuenta atras + antelacion. Medido tras el cambio, la frase mas
    larga pasa de 1.55 s a 1.79 s. Si alguien la ralentiza mas de la cuenta,
    la frase invade la curva anterior y el aviso deja de servir.
    """
    from conftest import referencia

    coach = Coach(referencia(circuito), FakeAudio(), coach_cfg(voice=True))
    duraciones = [e["_voice_dur"] for e in coach.events if e.get("_voice_dur")]

    assert duraciones, "no se genero ninguna frase"
    assert max(duraciones) < 2.5, (
        f"la frase mas larga dura {max(duraciones):.2f} s: a este paso no cabe "
        "antes de la curva"
    )


def test_el_solape_entre_frases_sigue_acotado(circuito):
    """Ya hay curvas donde la frase arranca antes de pasar la anterior.

    No es nuevo ni es un fallo: medido antes de tocar la velocidad de la voz,
    Hockenheim ya iba a -36 m y Winton a -64 m. Se sostiene porque el motor de
    audio SUMA los sonidos en vez de cortarlos. Lo que este test impide es que
    ese solape crezca sin que nadie se entere.
    """
    from conftest import referencia

    ref = referencia(circuito)
    coach = Coach(ref, FakeAudio(), coach_cfg(voice=True, countdown=3,
                                              countdown_interval=0.5))
    eventos = sorted(coach.events, key=lambda e: e["pos"])
    largo = ref["track_length_m"]

    peor = 0.0
    for i, ev in enumerate(eventos):
        if not ev.get("_voice_dur"):
            continue
        v = ev.get("speed_ms", 50.0)
        necesita = (0.35 + 3 * 0.5 + ev["_voice_dur"] + 0.30) * v
        hueco = ((ev["pos"] - eventos[i - 1]["pos"]) % 1.0) * largo
        peor = min(peor, hueco - necesita)

    assert peor > -110.0, (
        f"la frase invade {abs(peor):.0f} m la curva anterior: o la voz se ha "
        "alargado demasiado, o hay que acortar la cuenta atras"
    )


def test_por_defecto_la_voz_va_por_debajo_del_tono():
    """El default tiene que corregir lo que se oyo en pista, no repetirlo."""
    ref = {
        "track_length_m": 4000.0,
        "events": [{"type": "brake", "pos": 0.5, "speed_ms": 50.0,
                    "peak": 0.8, "gear": 3}],
    }
    coach = Coach(ref, FakeAudio(), coach_cfg(voice=True))
    assert coach.cfg.voice_volume < 1.0, "el default no atenua nada"
