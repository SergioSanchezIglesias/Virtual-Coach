#!/usr/bin/env python3
"""
analyzer.py — Convierte una vuelta de referencia exportada de Garage61 (CSV)
en una lista de eventos de frenada y aceleracion indexados por LapDistPct.

Salida: JSON listo para consumir por el coach en vivo.

Uso:
    python analyzer.py vuelta.csv --track hockenheim_gp --car ferrari_296_gt3 \
        --laptime 99.156 --track-length 4574 -o ref_hockenheim.json
"""

import argparse
import json
import numpy as np
import pandas as pd

SAMPLE_RATE = 60.0  # Hz. iRacing / Garage61 exportan a 60 Hz uniformes.

# --- Umbrales de deteccion -------------------------------------------------
# Todos ajustables por CLI: son EL parametro a afinar del proyecto.
BRAKE_ON = 0.15    # el pedal supera esto -> puede ser una frenada
BRAKE_OFF = 0.03   # por debajo de esto se considera pedal suelto (histeresis)
BRAKE_MIN_PEAK = 0.30   # pico minimo de freno para contar como frenada. A 0.35
                        # se perdia la curva 1 de Hockenheim (un toque de 0.34).
                        # Hay hueco limpio: no hay picos reales entre 0.05 y 0.34,
                        # asi que 0.30 la captura sin colar roces. Validar en otros
                        # circuitos: si aparecen avisos fantasma, subirlo por CLI.
BRAKE_MIN_DUR = 0.20    # segundos minimos por encima de BRAKE_OFF
THROTTLE_ON = 0.20      # apertura de gas que cuenta como "vuelve a acelerar"
MERGE_DIST = 40.0       # metros: eventos mas juntos que esto se fusionan

# Lifts: curvas rapidas que se toman LEVANTANDO el gas, sin llegar a frenar.
LIFT_FULL = 0.90        # gas considerado "pleno" del que se levanta
LIFT_TARGET = 0.70      # tiene que caer al menos hasta aqui para contar
LIFT_NO_BRAKE = 0.08    # si el freno supera esto, es una frenada, no un lift
LIFT_MIN_DUR = 0.30     # segundos sostenido (descarta microblips del pie)
LIFT_RECOVER = 0.10     # cuanto sube el gas desde el valle para marcar el gas

# Zonas de gestion: curvas rapidas encadenadas que se toman a GAS PARCIAL, sin
# frenar y sin volver a pleno. El gas OSCILA (modulacion continua): no hay un
# instante unico que avisar, se avisa la ENTRADA. Contar cuantas veces el gas
# cruza su media distingue esto (oscila) de una salida de curva (sube y ya).
MANAGE_FULL = 0.85       # el gas nunca llega a pleno en la zona
MANAGE_NO_BRAKE = 0.08   # sin freno en toda la zona
MANAGE_MIN_DUR = 0.80    # segundos sostenido
MANAGE_CROSSINGS = 3     # cruces minimos del gas sobre su media (oscilacion)
MANAGE_CLEAR = 40.0      # metros: si hay frenada/lift mas cerca, no es zona nueva


def load_lap(path: str) -> pd.DataFrame:
    """Carga el CSV y normaliza lo minimo imprescindible."""
    df = pd.read_csv(path)

    required = {"Speed", "LapDistPct", "Brake", "Throttle", "Gear"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Faltan columnas en el CSV: {sorted(missing)}")

    # Rotar para empezar en la LINEA DE META. Garage61 puede exportar la vuelta
    # arrancando a mitad de circuito (LapDistPct en 0.16, no en 0). Como
    # detect_events recorre el array asumiendo orden 0->1, un corte a mitad
    # descoloca las curvas pegadas a el (su gas cae "antes" que su freno, ver
    # Winton). Rotamos al primer frame tras el salto 1->0. Un CSV que ya empieza
    # en meta (Hockenheim) no tiene ese salto y se queda igual.
    pos = df["LapDistPct"].to_numpy()
    jumps = np.where(np.diff(pos) < -0.5)[0]
    if len(jumps):
        k = int(jumps[0]) + 1
        df = pd.concat([df.iloc[k:], df.iloc[:k]]).reset_index(drop=True)

    # El export trae ruido de coma flotante (-3e-10). Fuera.
    df["Brake"] = df["Brake"].clip(0.0, 1.0)
    df["Throttle"] = df["Throttle"].clip(0.0, 1.0)

    # No hay canal de tiempo: se reconstruye del muestreo uniforme a 60 Hz.
    df["t"] = np.arange(len(df)) / SAMPLE_RATE

    return df


def track_length_from_speed(df: pd.DataFrame) -> float:
    """Estima la longitud de la vuelta integrando la velocidad.

    distancia = Σ v·Δt, con Δt = 1/60 s. Da la longitud de la TRAZADA
    realmente recorrida, que para convertir LapDistPct a metros es incluso
    mas fiel que la longitud oficial del spline del circuito. No necesita ser
    exacta al metro: el aviso del coach va en tiempo, con --margin de colchon,
    asi que un error del 1-2% se traduce en milisegundos. Valido en Hockenheim
    (4516 m estimados vs 4574 m oficiales: 1.3%). Evita tener que saber y
    teclear la longitud de cada circuito a mano.
    """
    return float(df["Speed"].sum() / SAMPLE_RATE)


def detect_events(df: pd.DataFrame, track_length: float, cfg) -> list[dict]:
    """Devuelve zonas de frenada con su punto de freno y su punto de gas."""
    brake = df["Brake"].to_numpy()
    throttle = df["Throttle"].to_numpy()
    speed = df["Speed"].to_numpy()
    pos = df["LapDistPct"].to_numpy()
    gear = df["Gear"].to_numpy()
    n = len(df)

    zones = []
    i = 0
    while i < n:
        if brake[i] <= cfg.brake_on:
            i += 1
            continue

        # Extender el bloque hacia delante mientras siga habiendo pedal.
        end = i
        while end < n and brake[end] > cfg.brake_off:
            end += 1

        duration = (end - i) / SAMPLE_RATE
        peak = float(brake[i:end].max())

        if duration >= cfg.brake_min_dur and peak >= cfg.brake_min_peak:
            # Retroceder al primer contacto real con el pedal: el punto de
            # frenada util es donde el pie ATERRIZA, no donde cruza el umbral.
            start = i
            while start > 0 and brake[start - 1] > cfg.brake_off:
                start -= 1

            # Punto de gas = momento en que el pie izquierdo suelta el freno.
            #
            # Medido sobre la referencia real, este punto coincide con el
            # primer contacto con el acelerador dentro de 0-6 m en las seis
            # zonas: el piloto no rueda en punto muerto, encadena. Y la senal
            # del freno es monotona y limpia, mientras que la del gas no:
            # estos coches llevan auto-blip y el acelerador sube solo por
            # encima de 0.5 durante las reducciones, en plena frenada.
            # Detectar por freno evita ese falso positivo de raiz.
            gas = min(end, n - 1)

            # Validacion: si el gas no sube de verdad poco despues, no fue una
            # transicion sino una fase de inercia. Ahi el aviso no aplica.
            window = gas + int(0.6 * SAMPLE_RATE)
            coasting = throttle[gas:min(window, n)].max() < cfg.throttle_on

            # Solo informativo: donde llega a gas pleno. No genera aviso
            # (varia entre 0.2 s y 1.1 s segun la curva: es un resultado de
            # la entrada, no una accion que se pueda ordenar).
            full = gas
            while full < n - 1 and throttle[full] < 0.90:
                full += 1

            zones.append({
                "coasting": bool(coasting),
                "full_throttle_pos": float(pos[full]),
                "brake_pos": float(pos[start]),
                "brake_speed_ms": float(speed[start]),
                # Marcha de la CURVA (en el punto de gas), no la del inicio de
                # frenada: al piloto le sirve saber a que marcha reduce, no
                # desde cual. En una horquilla frenas en 5a pero la tomas en 1a.
                "gear": int(gear[gas]),
                "peak_brake": peak,
                "brake_duration_s": round(duration, 3),
                "min_speed_ms": float(speed[start:gas].min()),
                "throttle_pos": float(pos[gas]),
                "throttle_speed_ms": float(speed[gas]),
            })

        i = end

    return merge_close(zones, track_length, cfg.merge_dist)


def merge_close(zones: list[dict], track_length: float, min_gap: float) -> list[dict]:
    """Fusiona zonas cuyos puntos de freno estan a menos de min_gap metros.

    Caso tipico: el piloto suelta un instante entre dos apoyos de la misma
    secuencia de curvas. Son una sola referencia para el piloto, no dos.
    """
    if not zones:
        return zones

    merged = [zones[0]]
    for z in zones[1:]:
        gap = (z["brake_pos"] - merged[-1]["brake_pos"]) * track_length
        if gap < min_gap:
            prev = merged[-1]
            prev["peak_brake"] = max(prev["peak_brake"], z["peak_brake"])
            prev["min_speed_ms"] = min(prev["min_speed_ms"], z["min_speed_ms"])
            prev["throttle_pos"] = z["throttle_pos"]
            prev["throttle_speed_ms"] = z["throttle_speed_ms"]
            prev["gear"] = z["gear"]  # la marcha de la curva es la del apoyo final
        else:
            merged.append(z)
    return merged


def detect_lifts(df: pd.DataFrame, cfg) -> list[dict]:
    """Zonas donde se LEVANTA el gas sin frenar (curvas rapidas de solo alzar).

    Un lift es una caida desde gas pleno que se sostiene parcial SIN que el
    freno aparezca. Definirlo asi lo separa por construccion de:
      - las frenadas    -> ahi el freno sube por encima de lift_no_brake
      - las salidas de curva -> ahi el gas SUBE desde cero, no cae desde pleno
    El aviso cae donde el pie ROMPE desde pleno, el analogo al primer contacto
    con el freno en las frenadas.
    """
    thr = df["Throttle"].to_numpy()
    brk = df["Brake"].to_numpy()
    pos = df["LapDistPct"].to_numpy()
    speed = df["Speed"].to_numpy()
    n = len(df)

    lifts = []
    i = 1
    while i < n:
        # Transicion pleno -> no-pleno: el pie empieza a levantar.
        if thr[i - 1] >= cfg.lift_full and thr[i] < cfg.lift_full:
            start = i - 1
            j = i
            min_thr, max_brk = thr[i], brk[i]
            while j < n and thr[j] < cfg.lift_full:
                min_thr = min(min_thr, thr[j])
                max_brk = max(max_brk, brk[j])
                j += 1
            dur = (j - start) / SAMPLE_RATE
            if (min_thr < cfg.lift_target
                    and max_brk < cfg.lift_no_brake
                    and dur >= cfg.lift_min_dur):
                # Vuelve-a-gas: tras el valle del gas, el punto donde el pie
                # EMPIEZA a volver de verdad (recupera lift_recover desde el
                # minimo). Es el "ya puedes", analogo al primer contacto con el
                # gas de las frenadas, no el gas pleno.
                idx_min = start + int(np.argmin(thr[start:j]))
                back = idx_min
                while back < j and thr[back] < min_thr + cfg.lift_recover:
                    back += 1
                lifts.append({
                    "lift_pos": float(pos[start]),
                    "lift_speed_ms": float(speed[start]),
                    "lift_min_throttle": round(float(min_thr), 2),
                    "gas_pos": float(pos[back]),
                    "gas_speed_ms": float(speed[back]),
                })
            i = j
        else:
            i += 1
    return lifts


def detect_manage_zones(df: pd.DataFrame, track_length: float, cfg,
                        taken_pos: list[float]) -> list[dict]:
    """Zonas de gestion: gas parcial sostenido, sin frenar, sin llegar a pleno.

    Curvas rapidas encadenadas donde el gas se MODULA (sube y baja) en vez de
    haber una accion puntual. Se detecta el tramo y se avisa su entrada. El
    numero de cruces del gas sobre su media separa la modulacion real de una
    simple salida de curva (donde el gas solo sube). Se descartan las zonas
    pegadas a una frenada o lift ya detectados.
    """
    thr = df["Throttle"].to_numpy()
    brk = df["Brake"].to_numpy()
    speed = df["Speed"].to_numpy()
    pos = df["LapDistPct"].to_numpy()
    gear = df["Gear"].to_numpy()
    n = len(df)

    zones = []
    i = 0
    while i < n:
        if brk[i] < cfg.manage_no_brake and thr[i] < cfg.manage_full:
            start = i
            j = i
            bmax = 0.0
            while j < n and brk[j] < cfg.manage_no_brake and thr[j] < cfg.manage_full:
                bmax = max(bmax, brk[j])
                j += 1
            seg = thr[start:j]
            dur = (j - start) / SAMPLE_RATE
            if len(seg):
                gm = float(seg.mean())
                cross = int(np.sum(np.diff((seg > gm).astype(int)) != 0))
                p = float(pos[start])
                near = any(abs(p - t) * track_length < cfg.manage_clear
                           for t in taken_pos)
                if (dur >= cfg.manage_min_dur and bmax < cfg.manage_no_brake
                        and 0.05 < gm < 0.65 and cross >= cfg.manage_crossings
                        and not near):
                    apex = start + int(np.argmin(speed[start:j]))
                    zones.append({
                        "pos": p,
                        "speed_ms": float(speed[start]),
                        "gear": int(gear[apex]),  # marcha en el punto mas lento
                        "gas_mean": round(gm, 2),
                    })
            i = j
        else:
            i += 1
    return zones


def print_table(zones: list[dict], track_length: float) -> None:
    print(f"\n{len(zones)} zonas de frenada detectadas\n")
    print(f"{'#':>2} {'freno':>7} {'m':>6} {'v_ent':>6} {'pico':>5} "
          f"{'dur':>5} {'v_min':>6} {'gas':>7} {'m':>6} {'largo':>6}")
    print("-" * 70)
    for i, z in enumerate(zones, 1):
        print(
            f"{i:>2} "
            f"{z['brake_pos'] * 100:>6.2f}% {z['brake_pos'] * track_length:>6.0f} "
            f"{z['brake_speed_ms'] * 3.6:>6.0f} {z['peak_brake']:>5.2f} "
            f"{z['brake_duration_s']:>5.2f} {z['min_speed_ms'] * 3.6:>6.0f} "
            f"{z['throttle_pos'] * 100:>6.2f}% {z['throttle_pos'] * track_length:>6.0f} "
            f"{(z['throttle_pos'] - z['brake_pos']) * track_length:>6.0f}"
        )
    print()


def to_reference(zones: list[dict], lifts: list[dict],
                 manage: list[dict], args) -> dict:
    """Aplana las zonas a la lista de eventos que consume el coach."""
    events = []
    for z in zones:
        events.append({
            "type": "brake",
            "pos": round(z["brake_pos"], 6),
            "speed_ms": round(z["brake_speed_ms"], 2),
            "peak": round(z["peak_brake"], 2),
            "gear": z["gear"],  # marcha de la curva, para la voz
        })
        events.append({
            "type": "throttle",
            "pos": round(z["throttle_pos"], 6),
            "speed_ms": round(z["throttle_speed_ms"], 2),
        })
    for lift in lifts:
        events.append({
            "type": "lift",
            "pos": round(lift["lift_pos"], 6),
            "speed_ms": round(lift["lift_speed_ms"], 2),
        })
        # El "vuelve a pisar" del lift usa el mismo aviso que el gas de una
        # frenada: es la misma orden, "ya puedes acelerar".
        events.append({
            "type": "throttle",
            "pos": round(lift["gas_pos"], 6),
            "speed_ms": round(lift["gas_speed_ms"], 2),
        })
    for m in manage:
        events.append({
            "type": "manage",
            "pos": round(m["pos"], 6),
            "speed_ms": round(m["speed_ms"], 2),
            "gear": m["gear"],
        })
    events.sort(key=lambda e: e["pos"])

    return {
        "sim": "iracing",
        "track": args.track,
        "car": args.car,
        "track_length_m": args.track_length,
        "laptime_s": args.laptime,
        "source": "garage61",
        "events": events,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--track", default="unknown")
    ap.add_argument("--car", default="unknown")
    ap.add_argument("--laptime", type=float, default=None)
    ap.add_argument("--track-length", type=float, default=None,
                    help="metros; si se omite, se estima integrando la velocidad "
                         "de la propia vuelta (afecta a la fusion de zonas y al "
                         "timing del coach, no es solo cosmetico)")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--brake-on", type=float, default=BRAKE_ON)
    ap.add_argument("--brake-off", type=float, default=BRAKE_OFF)
    ap.add_argument("--brake-min-peak", type=float, default=BRAKE_MIN_PEAK)
    ap.add_argument("--brake-min-dur", type=float, default=BRAKE_MIN_DUR)
    ap.add_argument("--throttle-on", type=float, default=THROTTLE_ON)
    ap.add_argument("--merge-dist", type=float, default=MERGE_DIST)
    ap.add_argument("--lift-full", type=float, default=LIFT_FULL)
    ap.add_argument("--lift-target", type=float, default=LIFT_TARGET)
    ap.add_argument("--lift-no-brake", type=float, default=LIFT_NO_BRAKE)
    ap.add_argument("--lift-min-dur", type=float, default=LIFT_MIN_DUR)
    ap.add_argument("--lift-recover", type=float, default=LIFT_RECOVER)
    ap.add_argument("--manage-full", type=float, default=MANAGE_FULL)
    ap.add_argument("--manage-no-brake", type=float, default=MANAGE_NO_BRAKE)
    ap.add_argument("--manage-min-dur", type=float, default=MANAGE_MIN_DUR)
    ap.add_argument("--manage-crossings", type=int, default=MANAGE_CROSSINGS)
    ap.add_argument("--manage-clear", type=float, default=MANAGE_CLEAR)
    args = ap.parse_args()

    df = load_lap(args.csv)
    print(f"{len(df)} muestras, {len(df) / SAMPLE_RATE:.3f} s reconstruidos")

    if args.track_length is None:
        args.track_length = track_length_from_speed(df)
        print(f"Longitud estimada de la vuelta: {args.track_length:.0f} m "
              f"(integrada de la velocidad)")

    zones = detect_events(df, args.track_length, args)
    print_table(zones, args.track_length)

    lifts = detect_lifts(df, args)
    if lifts:
        print(f"{len(lifts)} lifts (levantar sin frenar):")
        for lift in lifts:
            print(f"  suelta {lift['lift_pos'] * 100:6.2f}%  ->  "
                  f"gas {lift['gas_pos'] * 100:6.2f}%   "
                  f"({lift['lift_speed_ms'] * 3.6:3.0f} km/h, "
                  f"valle {lift['lift_min_throttle']:.2f})")
        print()

    taken = ([z["brake_pos"] for z in zones]
             + [z["throttle_pos"] for z in zones]
             + [lift["lift_pos"] for lift in lifts])
    manage = detect_manage_zones(df, args.track_length, args, taken)
    if manage:
        print(f"{len(manage)} zonas de gestion (gas parcial, sin frenar):")
        for m in manage:
            print(f"  {m['pos'] * 100:6.2f}%  {m['speed_ms'] * 3.6:3.0f} km/h  "
                  f"marcha {m['gear']}  (gas medio {m['gas_mean']:.2f})")
        print()

    if args.output:
        ref = to_reference(zones, lifts, manage, args)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(ref, fh, indent=2)
        print(f"Escrito {args.output} ({len(ref['events'])} eventos)")


if __name__ == "__main__":
    main()
