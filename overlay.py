#!/usr/bin/env python3
"""
overlay.py — Clasificacion por clases con iRating estimado, ENCIMA del juego.

Una ventana sin bordes, siempre encima y con el fondo transparente (iRacing
tiene que ir en ventana sin bordes, no en pantalla completa exclusiva). Se
pinta con un Canvas de Tk a 4 Hz: para una tabla sobra.

    python overlay.py                       # iRacing en vivo (Windows)
    python overlay.py --record carrera.jsonl  # en vivo, y ademas graba
    python overlay.py --replay carrera.jsonl  # reproduce una grabacion (Mac)

Consume SessionSnapshot de source.py y la logica de standings.py: aqui solo
hay pintura. Arrastra el panel con el raton; Esc lo cierra.
"""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

import standings as st
from source import SessionRecorder, SessionSnapshot, make_session_source

# Los mismos colores que la GUI (y que el boceto de Pencil), para que sea la
# misma app se mire por donde se mire.
BG = "#0D1015"
SURFACE_2 = "#1C222B"
TEXT = "#E9EEF4"
TEXT_DIM = "#8892A0"
TEXT_FAINT = "#5C6674"
ACCENT = "#7CE38B"  # verde: gas, mi fila, iR positivo
BRAKE = "#FF5C4D"  # rojo: iR negativo
LIFT = "#4DA3FF"
MANAGE = "#B98CFF"  # morado: mejor vuelta de la clase
VOICE = "#FFB020"
KEY = "#010203"  # color clave: lo que se pinta de esto es transparente

# Color por clase: se reconoce por el nombre y, si no, se reparte una paleta.
CLASS_HINTS = [
    ("GT3", ACCENT), ("GT4", LIFT), ("LMP2", VOICE), ("HPD", VOICE),
    ("LMP3", VOICE), ("GTP", MANAGE), ("HYPER", MANAGE), ("CUP", BRAKE),
    ("PORSCHE", BRAKE), ("TCR", "#F06292"),
]
PALETTE = [ACCENT, LIFT, VOICE, MANAGE, BRAKE, "#F06292"]

W = 660
PAD = 14
GAPX = 10
H_HDR, H_CLS, H_COLS, H_ROW, H_MORE, H_FOOT = 40, 32, 22, 30, 22, 26
COLS = [("POS", 22, "w"), ("#", 44, "w"), ("PILOTO", 150, "w"),
        ("iRATING", 96, "w"), ("GAP", 56, "e"), ("INT", 56, "e"),
        ("ÚLTIMA", 66, "e"), ("MEJOR", 66, "e")]


def _pick_font(candidates: list[str], fallback: str) -> str:
    families = set(tkfont.families())
    for c in candidates:
        if c in families:
            return c
    return fallback


class Overlay:
    def __init__(self, root: tk.Tk, top: int, around: int, scale: float):
        self.root = root
        self.top = top
        self.around = around
        self.s = scale
        self.snap: SessionSnapshot | None = None
        self.status = "Esperando a iRacing… (entra en una sesión)"
        self.lock = threading.Lock()

        root.title("Virtual Coach — overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self._transparent(root)

        self.ui = _pick_font(["Inter", "Segoe UI", "Helvetica Neue"], "TkDefaultFont")
        self.mono = _pick_font(["JetBrains Mono", "Consolas", "Menlo"], "TkFixedFont")

        self.canvas = tk.Canvas(root, width=W * scale, height=200, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._drag = None
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        root.bind("<Escape>", lambda e: root.destroy())

    # -- ventana ------------------------------------------------------------

    def _transparent(self, root: tk.Tk) -> None:
        try:
            if sys.platform == "win32":
                root.attributes("-transparentcolor", KEY)
                root.attributes("-alpha", 0.92)
            elif sys.platform == "darwin":
                root.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    # -- datos --------------------------------------------------------------

    def push(self, snap: SessionSnapshot) -> None:
        with self.lock:
            self.snap = snap

    def set_status(self, text: str) -> None:
        with self.lock:
            self.status = text

    def tick(self) -> None:
        with self.lock:
            snap, status = self.snap, self.status
        try:
            if snap is not None:
                self.draw(snap)
            else:
                self.draw_waiting(status)
        except Exception as exc:
            # Un fallo pintando NO puede matar el bucle: se canta una vez y
            # se sigue intentando con la foto siguiente.
            import traceback

            key = f"{type(exc).__name__}: {exc}"
            if key != getattr(self, "_last_draw_error", None):
                self._last_draw_error = key
                print(f"[overlay] error pintando: {key}", flush=True)
                traceback.print_exc()
            self.draw_waiting(f"Error pintando: {key}"[:80])
        self.root.after(250, self.tick)

    def draw_waiting(self, status: str) -> None:
        # Sin datos el canvas seria del color clave, o sea INVISIBLE, y no
        # sabrias si el overlay esta vivo. Un panel pequeno lo dice.
        s = self.s
        c = self.canvas
        c.config(height=H_HDR * s)
        c.delete("all")
        self._rrect(0, 0, W * s, H_HDR * s, 8 * s, fill=BG, outline="#2A313A")
        self._text(PAD * s, H_HDR * s / 2, "VIRTUAL COACH", 11, "bold", TEXT_DIM)
        self._text((W - PAD) * s, H_HDR * s / 2, status, 12, fill=TEXT_FAINT, anchor="e")

    # -- pintura ------------------------------------------------------------

    def _f(self, size: int, weight: str = "normal", mono: bool = False):
        return (self.mono if mono else self.ui, int(round(size * self.s)), weight)

    def _rrect(self, x0, y0, x1, y1, r, **kw):
        c = self.canvas
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return c.create_polygon(pts, smooth=True, **kw)

    def _text(self, x, y, s, size=13, weight="normal", fill=TEXT, mono=False, anchor="w"):
        self.canvas.create_text(x, y, text=s, font=self._f(size, weight, mono),
                                fill=fill, anchor=anchor)

    def _cols(self):
        x = PAD * self.s
        for name, w, anchor in COLS:
            yield name, x, x + w * self.s, anchor
            x += (w + GAPX) * self.s

    def draw(self, snap: SessionSnapshot) -> None:
        s = self.s
        c = self.canvas
        blocks = st.build_standings(snap)
        rows_by_block = [st.visible_rows(b, self.top, self.around) for b in blocks]
        height = H_HDR + H_FOOT + sum(
            H_CLS + H_COLS + H_ROW * len(r) + (H_MORE if len(r) < b.n else 0)
            for b, r in zip(blocks, rows_by_block)
        )
        c.config(height=height * s)
        c.delete("all")
        self._rrect(0, 0, W * s, height * s, 8 * s, fill=BG, outline="#2A313A")

        y = self._header(snap, blocks)
        for i, (b, rows) in enumerate(zip(blocks, rows_by_block)):
            y = self._class(b, rows, self._class_color(b, i), y)
        self._footer(y)

    def _class_color(self, b: st.ClassBlock, i: int) -> str:
        name = b.class_name.upper()
        for hint, color in CLASS_HINTS:
            if hint in name:
                return color
        return PALETTE[i % len(PALETTE)]

    def _header(self, snap: SessionSnapshot, blocks) -> float:
        s = self.s
        c = self.canvas
        c.create_rectangle(0, 0, W * s, H_HDR * s, fill="#0A0D11", outline="")
        cy = H_HDR * s / 2
        x = PAD * s
        kind = {"Race": "RACE", "Practice": "PRACTICE", "Open Qualify": "QUALY",
                "Lone Qualify": "QUALY", "Warmup": "WARMUP"}.get(snap.session_type, snap.session_type.upper())
        w = 8 * s + len(kind) * 7.5 * s
        self._rrect(x, cy - 9 * s, x + w, cy + 9 * s, 4 * s, fill=TEXT, outline="")
        self._text(x + w / 2, cy, kind, 11, "bold", BG, anchor="center")
        x += w + 14 * s
        if snap.laps_total:
            self._text(x, cy, f"Lap {snap.laps_done + 1} / {snap.laps_total}", 13, "bold")
        else:
            self._text(x, cy, f"Lap {snap.laps_done + 1}", 13, "bold")
        x += 100 * s
        m, sec = divmod(max(0, int(snap.time_remain)), 60)
        remain = f"{m}:{sec:02d}" if snap.time_remain < 36000 else "—"
        self._text(x, cy, remain, 13, fill=TEXT_DIM, mono=True)

        me = snap.me
        mine = next((b for b in blocks if b.is_mine), None)
        if me and mine:
            row = next((r for r in mine.rows if r.is_me), None)
            xr = (W - PAD) * s
            if row:
                col = TEXT_DIM if row.delta is None else (ACCENT if row.delta >= 0 else BRAKE)
                txt = st.fmt_delta(row.delta)
                w = 16 * s + len(txt) * 8 * s
                self._rrect(xr - w, cy - 10 * s, xr, cy + 10 * s, 4 * s,
                            fill=self._tint(col, 0.15), outline="")
                self._text(xr - w / 2, cy, txt, 13, "bold", col, mono=True, anchor="center")
                xr -= w + 8 * s
            self._text(xr, cy, f"Tú · {st.fmt_ir(me.irating)}", 13, fill=TEXT_DIM, anchor="e")
        return H_HDR * s

    def _class(self, b: st.ClassBlock, rows, color: str, y: float) -> float:
        s = self.s
        c = self.canvas
        # Cabecera de clase
        c.create_rectangle(0, y, W * s, y + H_CLS * s, fill=self._tint(color), outline="")
        c.create_rectangle(0, y, 3 * s, y + H_CLS * s, fill=color, outline="")
        cy = y + H_CLS * s / 2
        x = PAD * s
        name = b.class_name or f"Clase {b.class_id}"
        w = 8 * s + len(name) * 7.5 * s
        self._rrect(x, cy - 8 * s, x + w, cy + 8 * s, 3 * s, fill=color, outline="")
        self._text(x + w / 2, cy, name, 11, "bold", BG, anchor="center")
        x += w + 10 * s
        self._text(x, cy, f"SoF {b.sof:.0f}", 13, "bold", TEXT_DIM)
        x += 80 * s
        self._text(x, cy, f"{b.n} coches", 13, fill=TEXT_FAINT)
        self._text((W - PAD) * s, cy, "iRating · Δ estimado", 11, fill=TEXT_FAINT, anchor="e")
        y += H_CLS * s
        # Cabecera de columnas
        cy = y + H_COLS * s / 2
        for name, x0, x1, anchor in self._cols():
            self._text(x0 if anchor == "w" else x1, cy, name, 10, "bold", TEXT_FAINT, anchor=anchor)
        y += H_COLS * s
        # Filas
        for i, r in enumerate(rows):
            if r.is_me:
                c.create_rectangle(0, y, W * s, y + H_ROW * s, fill="#1A2A1E", outline="")
                c.create_rectangle(0, y, 3 * s, y + H_ROW * s, fill=ACCENT, outline="")
            elif i % 2:
                c.create_rectangle(0, y, W * s, y + H_ROW * s, fill="#11151B", outline="")
            self._row(r, y)
            y += H_ROW * s
        if len(rows) < b.n:
            self._text(W * s / 2, y + H_MORE * s / 2, f"· · ·   {b.n - len(rows)} más   · · ·",
                       10, fill=TEXT_FAINT, anchor="center")
            y += H_MORE * s
        return y

    def _tint(self, color: str, k: float = 0.10) -> str:
        # Mezcla el color con el fondo (Tk no tiene alpha en los fills).
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        br, bg_, bb = (int(BG[i:i + 2], 16) for i in (1, 3, 5))
        mix = lambda a, b: int(b + (a - b) * k)
        return f"#{mix(r, br):02x}{mix(g, bg_):02x}{mix(b, bb):02x}"

    def _row(self, r: st.Row, y: float) -> None:
        s = self.s
        cy = y + H_ROW * s / 2
        me = r.is_me
        car = r.car
        cols = list(self._cols())
        (_, x0, _, _) = cols[0]
        self._text(x0, cy, str(r.pos), 13, "bold" if me else "normal",
                   ACCENT if me else TEXT_DIM, mono=True)
        (_, x0, _, _) = cols[1]
        self._text(x0, cy, f"#{car.number}", 13, fill=TEXT_DIM, mono=True)
        (_, x0, _, _) = cols[2]
        self._text(x0, cy, _short(car.name), 13, "bold" if me else "normal")
        (_, x0, x1, _) = cols[3]
        self._rrect(x0, cy - 10 * s, x1, cy + 10 * s, 4 * s, fill=SURFACE_2, outline="")
        self._text(x0 + 6 * s, cy, st.fmt_ir(car.irating), 12, fill=TEXT_DIM, mono=True)
        dcol = TEXT_FAINT if r.delta is None else (ACCENT if r.delta >= 0 else BRAKE)
        self._text(x1 - 6 * s, cy, st.fmt_delta(r.delta), 12, "bold", dcol, mono=True, anchor="e")
        (_, _, x1, _) = cols[4]
        self._text(x1, cy, st.fmt_gap(r.gap, r.pos == 1), 13,
                   fill=TEXT_FAINT if r.pos == 1 else TEXT, mono=True, anchor="e")
        (_, _, x1, _) = cols[5]
        self._text(x1, cy, "INT" if r.pos == 1 else st.fmt_gap(r.interval), 13,
                   fill=TEXT_FAINT if r.pos == 1 else TEXT_DIM, mono=True, anchor="e")
        (_, _, x1, _) = cols[6]
        pb = car.last_lap > 0 and car.best_lap > 0 and abs(car.last_lap - car.best_lap) < 1e-3
        self._text(x1, cy, st.fmt_lap(car.last_lap), 13,
                   fill=ACCENT if pb else TEXT, mono=True, anchor="e")
        (_, _, x1, _) = cols[7]
        self._text(x1, cy, st.fmt_lap(car.best_lap), 13,
                   fill=MANAGE if r.fastest else TEXT_DIM, mono=True, anchor="e")
        if car.on_pit_road:
            self._text((W - PAD) * s, cy, "PIT", 9, "bold", VOICE, anchor="e")

    def _footer(self, y: float) -> None:
        s = self.s
        self.canvas.create_rectangle(0, y, W * s, y + H_FOOT * s, fill="#0A0D11", outline="")
        self._text(PAD * s, y + H_FOOT * s / 2,
                   "ⓘ  El Δ de iRating es una ESTIMACIÓN (fórmula del SoF); iRacing lo confirma al acabar la sesión.",
                   10, fill=TEXT_FAINT)


def _short(name: str) -> str:
    """'Kevin Estre' -> 'K. Estre'. iRacing a veces mete un numero final."""
    parts = [p for p in name.split() if not p.isdigit()]
    if len(parts) >= 2:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"[:22]
    return name[:22]


def _feed(source, overlay: Overlay, recorder: SessionRecorder | None) -> None:
    import traceback

    try:
        n = 0
        for snap in source.snapshots():
            if recorder:
                recorder.write(snap)
            overlay.push(snap)
            n += 1
            if n == 1:
                print(f"[overlay] primera foto: {len(snap.cars)} coches, sesion {snap.session_type}", flush=True)
        overlay.set_status("Fin de la grabación")
    except BaseException as exc:  # que el hilo no muera en silencio
        print(f"[overlay] fuente parada: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        overlay.set_status(f"Sin datos: {type(exc).__name__}: {exc}"[:80])


def main() -> None:
    ap = argparse.ArgumentParser(description="Overlay de clasificacion con iRating estimado")
    ap.add_argument("--replay", help="JSONL grabado con --record (para el Mac)")
    ap.add_argument("--speed", type=float, default=1.0, help="velocidad del replay (0 = a tope)")
    ap.add_argument("--record", help="graba la sesion en vivo a este JSONL")
    ap.add_argument("--top", type=int, default=3, help="primeros de cada clase que se ven")
    ap.add_argument("--around", type=int, default=2, help="coches alrededor de mi que se ven")
    ap.add_argument("--scale", type=float, default=1.0, help="tamano del panel")
    ap.add_argument("--pos", default="28,28", help="esquina superior izquierda, x,y")
    args = ap.parse_args()

    if args.record and args.replay:
        raise SystemExit("--record es para la sesion en vivo, no para un replay.")

    root = tk.Tk()
    x, y = (int(v) for v in args.pos.split(","))
    root.geometry(f"+{x}+{y}")
    ov = Overlay(root, args.top, args.around, args.scale)

    source = make_session_source(args.replay, speed=args.speed)
    recorder = SessionRecorder(args.record) if args.record else None
    if recorder:
        print(f"[overlay] grabando en {args.record}", flush=True)
    threading.Thread(target=_feed, args=(source, ov, recorder), daemon=True).start()

    ov.tick()
    try:
        root.mainloop()
    finally:
        source.close()
        if recorder:
            recorder.close()


if __name__ == "__main__":
    main()
