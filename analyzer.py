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
BRAKE_MIN_PEAK = 0.35   # pico minimo para no confundir un roce con una frenada
BRAKE_MIN_DUR = 0.20    # segundos minimos por encima de BRAKE_OFF
THROTTLE_ON = 0.20      # apertura de gas que cuenta como "vuelve a acelerar"
MERGE_DIST = 40.0       # metros: eventos mas juntos que esto se fusionan


def load_lap(path: str) -> pd.DataFrame:
    """Carga el CSV y normaliza lo minimo imprescindible."""
    df = pd.read_csv(path)

    required = {"Speed", "LapDistPct", "Brake", "Throttle", "Gear"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Faltan columnas en el CSV: {sorted(missing)}")

    # El export trae ruido de coma flotante (-3e-10). Fuera.
    df["Brake"] = df["Brake"].clip(0.0, 1.0)
    df["Throttle"] = df["Throttle"].clip(0.0, 1.0)

    # No hay canal de tiempo: se reconstruye del muestreo uniforme a 60 Hz.
    df["t"] = np.arange(len(df)) / SAMPLE_RATE

    return df


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
                "brake_gear": int(gear[start]),
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
        else:
            merged.append(z)
    return merged


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


def to_reference(zones: list[dict], args) -> dict:
    """Aplana las zonas a la lista de eventos que consume el coach."""
    events = []
    for z in zones:
        events.append({
            "type": "brake",
            "pos": round(z["brake_pos"], 6),
            "speed_ms": round(z["brake_speed_ms"], 2),
            "peak": round(z["peak_brake"], 2),
        })
        events.append({
            "type": "throttle",
            "pos": round(z["throttle_pos"], 6),
            "speed_ms": round(z["throttle_speed_ms"], 2),
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
    ap.add_argument("--track-length", type=float, default=4574.0,
                    help="metros, solo para mostrar distancias legibles")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--brake-on", type=float, default=BRAKE_ON)
    ap.add_argument("--brake-off", type=float, default=BRAKE_OFF)
    ap.add_argument("--brake-min-peak", type=float, default=BRAKE_MIN_PEAK)
    ap.add_argument("--brake-min-dur", type=float, default=BRAKE_MIN_DUR)
    ap.add_argument("--throttle-on", type=float, default=THROTTLE_ON)
    ap.add_argument("--merge-dist", type=float, default=MERGE_DIST)
    args = ap.parse_args()

    df = load_lap(args.csv)
    print(f"{len(df)} muestras, {len(df) / SAMPLE_RATE:.3f} s reconstruidos")

    zones = detect_events(df, args.track_length, args)
    print_table(zones, args.track_length)

    if args.output:
        ref = to_reference(zones, args)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(ref, fh, indent=2)
        print(f"Escrito {args.output} ({len(ref['events'])} eventos)")


if __name__ == "__main__":
    main()
