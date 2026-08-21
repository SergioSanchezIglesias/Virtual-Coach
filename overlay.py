#!/usr/bin/env python3
"""
overlay.py — Clasificacion por clases (con iRating estimado) y RELATIVE,
ENCIMA del juego.

Ventanas sin bordes, siempre encima y con el fondo transparente (iRacing
tiene que ir en ventana sin bordes, no en pantalla completa exclusiva). Se
pintan con un Canvas de Tk a 4 Hz: para una tabla sobra.

    python overlay.py                       # clasificacion, iRacing en vivo
    python overlay.py --relative            # ademas, el relative
    python overlay.py --no-standings --relative   # solo el relative
    python overlay.py --record carrera.jsonl  # en vivo, y ademas graba
    python overlay.py --replay carrera.jsonl  # reproduce una grabacion (Mac)

Los dos paneles van en el MISMO proceso: una sola lectura del SDK, una sola
grabacion. Consume SessionSnapshot de source.py y la logica de standings.py:
aqui solo hay pintura. Arrastra cada panel con el raton (recuerda donde lo
dejas); Esc cierra todo.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import tkinter as tk
from contextlib import suppress
from pathlib import Path
from tkinter import font as tkfont

import standings as st
from source import SessionRecorder, SessionSnapshot, make_session_source

# Donde se recuerda la posicion de cada panel entre sesiones. Va junto a las
# grabaciones (sesiones/), que es la carpeta de datos que ya usa la GUI.
POS_FILE = Path(__file__).resolve().parent / "sesiones" / "overlay_pos.json"


def _read_pos_file(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    # Formato viejo ({"x","y"}, de cuando solo habia un panel): es el de la
    # clasificacion.
    if "x" in d and "y" in d:
        return {"standings": {"x": d["x"], "y": d["y"]}}
    return d


def load_pos(path: Path = POS_FILE, view: str = "standings") -> tuple[int, int] | None:
    """La ultima posicion guardada de ese panel, o None si no hay (o esta corrupta)."""
    try:
        d = _read_pos_file(path)[view]
        return int(d["x"]), int(d["y"])
    except (KeyError, ValueError, TypeError):
        return None


def save_pos(x: int, y: int, path: Path = POS_FILE, view: str = "standings") -> None:
    """Se guarda al SOLTAR el raton tras arrastrar, no al cerrar: la GUI mata
    el proceso con terminate() y un guardado al cierre nunca llegaria."""
    with suppress(OSError):
        d = _read_pos_file(path)
        d[view] = {"x": int(x), "y": int(y)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d), encoding="utf-8")


# ---------------------------------------------------------------------------
# Estetica: tarjetas grafito, texto claro, chips con borde de color
# ---------------------------------------------------------------------------

BG = "#23272E"          # tarjeta
BG_HDR = "#2C3139"      # cabecera de tarjeta
BG_ALT = "#272B33"      # fila alterna
BORDER = "#3A404A"
TEXT = "#F1F3F6"
TEXT_DIM = "#A3ABB7"
TEXT_FAINT = "#6E7683"
ACCENT = "#7CE38B"      # verde: mi fila, iR positivo
BRAKE = "#FF5C4D"       # rojo: iR negativo, me dobla
LIFT = "#4DA3FF"        # azul: le doblo
MANAGE = "#C58BFF"      # morado: mejor vuelta de la clase
VOICE = "#FFB020"
TEAL = "#3ED0B5"        # PIT
KEY = "#010203"         # color clave: lo que se pinta de esto es transparente

# Color por clase: se reconoce por el nombre y, si no, se reparte una paleta.
CLASS_HINTS = [
    ("GT3", ACCENT), ("GT4", LIFT), ("LMP2", VOICE), ("HPD", VOICE),
    ("LMP3", VOICE), ("GTP", TEAL), ("HYPER", TEAL), ("CUP", BRAKE),
    ("PORSCHE", BRAKE), ("TCR", "#F06292"),
]
PALETTE = [ACCENT, LIFT, VOICE, MANAGE, BRAKE, "#F06292"]

# Licencias de iRacing, por letra.
LIC_COLORS = {"R": "#EF4444", "D": "#F97316", "C": "#EAB308", "B": "#22C55E",
              "A": "#3B82F6", "P": "#C084FC", "W": "#C084FC"}

# Compacto a proposito: encima del juego cada pixel tapa pista. --scale lo
# ajusta. Anchos medidos con Consolas/Segoe UI (Windows), mas anchas que las
# del Mac: un tiempo "1:41.234" necesita ~68 px a 12 pt.
PAD = 10
GAPX = 8
CARD_GAP = 6
H_HDR, H_ROW, H_MORE = 28, 24, 16
H_PLAYER_ROW = 34
R_CARD = 8
H_TITLE = 22  # franja de arriba: serie, sesion, temperaturas
COLS = [("POS", 22, "w"), ("#", 34, "w"), ("PILOTO", 112, "w"),
        ("LIC", 46, "w"), ("iR", 40, "e"), ("INC", 28, "e"),
        ("ÚLTIMA", 68, "e"), ("MEJOR", 68, "e")]
REL_COLS = [("POS", 22, "w"), ("#", 34, "w"), ("PILOTO", 112, "w"),
            ("CLASE", 44, "w"), ("LIC", 46, "w"), ("iR", 40, "e"), ("REL", 52, "e")]
F_ROW, F_SMALL, F_TINY = 12, 11, 9


def _width(cols) -> int:
    return 2 * PAD + sum(w for _, w, _ in cols) + GAPX * (len(cols) - 1)


def _relative_row_height(row: st.RelRow) -> int:
    return H_PLAYER_ROW if row.is_me else H_ROW


def _relative_height(rows: list[st.RelRow]) -> int:
    return H_HDR + sum(_relative_row_height(row) for row in rows)


def _pick_font(candidates: list[str], fallback: str) -> str:
    families = set(tkfont.families())
    for c in candidates:
        if c in families:
            return c
    return fallback


def _short(name: str) -> str:
    """'Kevin Estre' -> 'K. Estre'. iRacing a veces mete un numero final."""
    parts = [p for p in name.split() if not p.isdigit()]
    if len(parts) >= 2:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"[:16]
    return name[:16]


def _lic(lic: str) -> tuple[str, str] | None:
    """'A 3.45' -> ('A 3.4', azul). None si no hay licencia (IA, JSONL viejo)."""
    lic = (lic or "").strip()
    if not lic:
        return None
    letter = lic[0].upper()
    rest = lic[1:].strip()
    with suppress(ValueError):
        rest = f"{float(rest):.1f}"
    return f"{letter} {rest}".strip(), LIC_COLORS.get(letter, TEXT_DIM)


def _mix(color: str, base: str, k: float) -> str:
    """color*k + base*(1-k). Tk no tiene alpha en los fills."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    br, bg_, bb = (int(base[i:i + 2], 16) for i in (1, 3, 5))
    def mix_channel(a: int, c: int) -> int:
        return int(c + (a - c) * k)

    return f"#{mix_channel(r, br):02x}{mix_channel(g, bg_):02x}{mix_channel(b, bb):02x}"


# ---------------------------------------------------------------------------
# El feed: la ultima foto y su clasificacion, compartidos por los paneles
# ---------------------------------------------------------------------------


def _laps_text(snap: SessionSnapshot) -> str:
    """Vuelta en curso / total. laps_done viene de RaceLaps (ver
    source.laps_done): el lider en CarIdxLap cuenta la de formacion."""
    if snap.laps_total:
        return f"Laps {snap.laps_done + 1} / {snap.laps_total}"
    return f"Lap {snap.laps_done + 1}"


class Feed:
    """Guarda la ultima foto y calcula la clasificacion UNA vez por foto
    (con la anterior a mano, para que dos coches pegados no bailen)."""

    def __init__(self):
        self.snap: SessionSnapshot | None = None
        self.blocks: list[st.ClassBlock] = []
        self.status = "Esperando a iRacing… (entra en una sesión)"
        self.lock = threading.Lock()
        self._ranks: dict[int, int] = {}
        self._memory = st.CarMemory()  # en carrera, quien se va sigue clasificado

    def push(self, snap: SessionSnapshot) -> None:
        snap = self._memory.apply(snap)
        blocks = st.build_standings(snap, self._ranks)
        with self.lock:
            self.snap, self.blocks = snap, blocks
            self._ranks = st.ranks(blocks)

    def set_status(self, text: str) -> None:
        with self.lock:
            self.status = text

    def get(self):
        with self.lock:
            return self.snap, self.blocks, self.status


# ---------------------------------------------------------------------------
# Panel base: ventana sin bordes, arrastrable, que recuerda su sitio
# ---------------------------------------------------------------------------


class Panel:
    VIEW = "panel"
    COLS: list = []

    def __init__(self, root: tk.Tk, feed: Feed, scale: float, pos: tuple[int, int]):
        self.root = root
        self.feed = feed
        self.s = scale
        self.w = _width(self.COLS)
        self.win = tk.Toplevel(root)
        self.win.title(f"Virtual Coach — {self.VIEW}")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self._transparent(self.win)
        self.win.geometry(f"+{pos[0]}+{pos[1]}")

        self.ui = _pick_font(["Inter", "Segoe UI", "Helvetica Neue"], "TkDefaultFont")
        self.mono = _pick_font(["JetBrains Mono", "Consolas", "Menlo"], "TkFixedFont")

        self.canvas = tk.Canvas(self.win, width=self.w * scale, height=H_HDR * scale,
                                bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._drag = None
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.win.bind("<Escape>", lambda e: root.destroy())
        self._last_draw_error = None

    # -- ventana ------------------------------------------------------------

    def _transparent(self, win) -> None:
        with suppress(tk.TclError):
            if sys.platform == "win32":
                win.attributes("-transparentcolor", KEY)
                win.attributes("-alpha", 0.94)
            elif sys.platform == "darwin":
                win.attributes("-alpha", 0.94)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, e):
        if self._drag:
            self._drag = None
            save_pos(self.win.winfo_x(), self.win.winfo_y(), view=self.VIEW)

    # -- bucle --------------------------------------------------------------

    def tick(self) -> None:
        snap, blocks, status = self.feed.get()
        try:
            if snap is not None:
                self.draw(snap, blocks)
            else:
                self.draw_waiting(status)
        except Exception as exc:
            # Un fallo pintando NO puede matar el bucle: se canta una vez y
            # se sigue intentando con la foto siguiente.
            import traceback

            key = f"{type(exc).__name__}: {exc}"
            if key != self._last_draw_error:
                self._last_draw_error = key
                print(f"[overlay/{self.VIEW}] error pintando: {key}", flush=True)
                traceback.print_exc()
            self.draw_waiting(f"Error pintando: {key}"[:80])
        self.win.after(250, self.tick)

    def draw(self, snap: SessionSnapshot, blocks: list[st.ClassBlock]) -> None:
        raise NotImplementedError

    def draw_waiting(self, status: str) -> None:
        # Sin datos el canvas seria del color clave, o sea INVISIBLE, y no
        # sabrias si el overlay esta vivo. Un panel pequeno lo dice.
        s = self.s
        c = self.canvas
        c.config(height=H_HDR * s)
        c.delete("all")
        self._card(0, 0, self.w * s, H_HDR * s)
        self._text(PAD * s, H_HDR * s / 2, "VIRTUAL COACH", F_SMALL, "bold", TEXT_DIM)
        self._text((self.w - PAD) * s, H_HDR * s / 2, status, F_SMALL, fill=TEXT_FAINT, anchor="e")

    # -- primitivas ---------------------------------------------------------

    def _f(self, size: int, weight: str = "normal", mono: bool = False):
        return (self.mono if mono else self.ui, int(round(size * self.s)), weight)

    def _rrect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _card(self, x0, y0, x1, y1, hdr_h: float = 0.0, accent: str | None = None):
        s = self.s
        self._rrect(x0, y0, x1, y1, R_CARD * s, fill=BG, outline=BORDER)
        if hdr_h:
            # La clase firma la tarjeta sin convertir la cabecera en un bloque chillón.
            header_bg = _mix(accent, BG_HDR, 0.10) if accent else BG_HDR
            self._rrect(x0, y0, x1, y0 + hdr_h + R_CARD * s, R_CARD * s, fill=header_bg, outline="")
            self.canvas.create_rectangle(x0 + 1, y0 + hdr_h, x1 - 1, y0 + hdr_h + R_CARD * s,
                                         fill=BG, outline="")
            self.canvas.create_line(x0 + 1, y0 + hdr_h, x1 - 1, y0 + hdr_h, fill=BORDER)
            if accent:
                self.canvas.create_rectangle(x0 + R_CARD * s, y0 + 1, x1 - R_CARD * s,
                                             y0 + 3 * s, fill=accent, outline="")
                self.canvas.create_rectangle(x0 + 1, y0 + 3 * s, x0 + 3 * s,
                                             y1 - R_CARD * s, fill=accent, outline="")

    def _text(self, x, y, s, size=13, weight="normal", fill=TEXT, mono=False, anchor="w") -> float:
        """Pinta y devuelve el ancho REAL del texto. La cabecera encadena
        textos ("13 coches", "Laps 1 / 16"...) y con anchos a ojo se pisaban
        (pasó con dos cifras de coches)."""
        item = self.canvas.create_text(x, y, text=s, font=self._f(size, weight, mono),
                                       fill=fill, anchor=anchor)
        x0, _, x1, _ = self.canvas.bbox(item)
        return float(x1 - x0)

    def _chip(self, x, cy, text, color, size=F_TINY + 1, filled=False, h=16, w=None) -> float:
        """Chip con borde de color (o relleno). Devuelve el ancho que ocupa."""
        s = self.s
        if w is None:
            w = tkfont.Font(font=self._f(size, "bold")).measure(text) / s + 10
        if filled:
            self._rrect(x, cy - h / 2 * s, x + w * s, cy + h / 2 * s, 4 * s, fill=color, outline="")
            self._text(x + w * s / 2, cy, text, size, "bold", BG, anchor="center")
        else:
            self._rrect(x, cy - h / 2 * s, x + w * s, cy + h / 2 * s, 4 * s,
                        fill=_mix(color, BG, 0.16), outline=color)
            self._text(x + w * s / 2, cy, text, size, "bold", color, anchor="center")
        return w * s

    def _cols(self):
        x = PAD * self.s
        for name, w, anchor in self.COLS:
            yield name, x, x + w * self.s, anchor
            x += (w + GAPX) * self.s

    def _class_color(self, name: str, i: int) -> str:
        up = name.upper()
        for hint, color in CLASS_HINTS:
            if hint in up:
                return color
        return PALETTE[i % len(PALETTE)]

    def _row_bg(self, y: float, is_me: bool, alt: bool, x1: float, height: int = H_ROW) -> None:
        s = self.s
        c = self.canvas
        row_end = y + height * s
        if is_me:
            c.create_rectangle(1, y, x1 - 1, row_end, fill=_mix(ACCENT, BG, 0.22), outline="")
            c.create_rectangle(1, y, 4 * s, row_end, fill=ACCENT, outline="")
            if height > H_ROW:
                c.create_line(4 * s, y, x1 - 1, y, fill=_mix(ACCENT, BG, 0.60))
                c.create_line(4 * s, row_end, x1 - 1, row_end, fill=_mix(ACCENT, BG, 0.60))
        elif alt:
            c.create_rectangle(1, y, x1 - 1, row_end, fill=BG_ALT, outline="")

    def _ident(self, cols, cy, car, pos_text: str, pos_color: str, bold: bool,
               name_color: str = TEXT, lic_slot: int = 3) -> None:
        """POS, #num, nombre y chip de licencia: comun a los dos paneles."""
        s = self.s
        (_, x0, _, _) = cols[0]
        self._text(x0, cy, pos_text, F_ROW, "bold" if bold else "normal", pos_color, mono=True)
        (_, x0, _, _) = cols[1]
        self._text(x0, cy, f"#{car.number}", F_SMALL, "bold", TEXT_DIM, mono=True)
        (_, x0, _, _) = cols[2]
        self._text(x0, cy, _short(car.name), F_ROW, "bold" if bold else "normal", name_color)
        (_, x0, x1, _) = cols[lic_slot]
        lic = _lic(car.license)
        if lic:
            self._chip(x0, cy, lic[0], lic[1], w=(x1 - x0) / s)


# ---------------------------------------------------------------------------
# Clasificacion por clases
# ---------------------------------------------------------------------------


class StandingsPanel(Panel):
    VIEW = "standings"
    COLS = COLS

    def __init__(self, root, feed, scale, pos, top: int, around: int):
        super().__init__(root, feed, scale, pos)
        self.top = top
        self.around = around

    def draw(self, snap: SessionSnapshot, blocks: list[st.ClassBlock]) -> None:
        s = self.s
        c = self.canvas
        rows_by_block = [st.visible_rows(b, self.top, self.around) for b in blocks]
        height = H_TITLE + CARD_GAP + sum(
            H_HDR + H_ROW * len(r) + (H_MORE if len(r) < b.n else 0)
            for b, r in zip(blocks, rows_by_block, strict=True)
        ) + CARD_GAP * max(0, len(blocks) - 1)
        c.config(width=self.w * s, height=max(height, H_HDR) * s)
        c.delete("all")
        y = self._title(snap) + CARD_GAP * s
        self._n_blocks = len(blocks)
        for i, (b, rows) in enumerate(zip(blocks, rows_by_block, strict=True)):
            self._block_index = i
            y = self._class(snap, b, rows, self._class_color(b.class_name, i), y)
            y += CARD_GAP * s

    def _title(self, snap: SessionSnapshot) -> float:
        """Tipo de sesion y temperaturas. El nombre de la serie NO sale del
        SDK (solo el SeriesID) y no se pinta: un hueco que hay que rellenar a
        mano no es automatico, es un recordatorio en mitad de la pista."""
        s = self.s
        h = H_TITLE * s
        self._card(0, 0, self.w * s, h)
        cy = h / 2
        kind = {"Race": "Carrera", "Practice": "Práctica", "Open Qualify": "Clasificación",
                "Lone Qualify": "Clasificación", "Warmup": "Warmup"}.get(snap.session_type, snap.session_type)
        self._text(PAD * s, cy, kind, F_SMALL, "bold", TEXT)
        if snap.air_temp is not None and snap.track_temp is not None:
            self._text((self.w - PAD) * s, cy, f"aire {snap.air_temp:.0f}°  ·  pista {snap.track_temp:.0f}°",
                       F_SMALL, fill=TEXT_DIM, anchor="e")
        return h

    def _class_label(self, b: st.ClassBlock) -> str:
        """El nombre de la clase, sin inventar: si iRacing no lo da, sin chip
        (una sola clase) o 'Clase A/B/C' (varias)."""
        if b.class_name:
            return b.class_name[:10]
        if self._n_blocks <= 1:
            return ""
        return f"Clase {chr(ord('A') + self._block_index)}"

    def _class(self, snap, b: st.ClassBlock, rows, color: str, y: float) -> float:
        s = self.s
        card_h = H_HDR + H_ROW * len(rows) + (H_MORE if len(rows) < b.n else 0)

        self._card(0, y, self.w * s, y + card_h * s, hdr_h=H_HDR * s, accent=color)
        # Cabecera de la tarjeta
        cy = y + H_HDR * s / 2
        x = PAD * s
        name = self._class_label(b)
        if name:
            x += self._chip(x, cy, name, color, size=F_TINY + 2, h=18) + 10 * s
        x += self._text(x, cy, f"{b.n}", F_ROW, "bold") + 4 * s
        x += self._text(x, cy, "coches", F_SMALL, fill=TEXT_DIM) + 14 * s
        x += self._text(x, cy, _laps_text(snap), F_ROW, "bold") + 14 * s
        m, sec = divmod(max(0, int(snap.time_remain)), 60)
        remain = f"{m}:{sec:02d}" if snap.time_remain < 36000 else "—"
        self._text(x, cy, remain, F_ROW, "bold", mono=True)
        xr = (self.w - PAD) * s
        if b.is_mine:
            row = next((r for r in b.rows if r.is_me), None)
            if row is not None:
                col = TEXT_DIM if row.delta is None else (ACCENT if row.delta >= 0 else BRAKE)
                txt = st.fmt_delta(row.delta)
                cw = tkfont.Font(font=self._f(F_TINY + 2, "bold")).measure(txt) + 10 * s
                xr -= self._chip(xr - cw, cy, txt, col, size=F_TINY + 2, h=18) + 8 * s
        self._text(xr, cy, f"SoF {b.sof:.0f}", F_ROW, "bold", TEXT, anchor="e")
        y += H_HDR * s
        # Filas
        for i, r in enumerate(rows):
            self._row_bg(y, r.is_me, i % 2 == 1, self.w * s)
            self._row(r, y)
            y += H_ROW * s
        if len(rows) < b.n:
            self._text(self.w * s / 2, y + H_MORE * s / 2, f"· · ·   {b.n - len(rows)} más   · · ·",
                       F_TINY, fill=TEXT_FAINT, anchor="center")
            y += H_MORE * s
        return y

    def _row(self, r: st.Row, y: float) -> None:
        s = self.s
        cy = y + H_ROW * s / 2
        me = r.is_me
        car = r.car
        cols = list(self._cols())
        # Quien se ha ido de la sala sigue clasificado, pero en gris.
        self._ident(cols, cy, car, str(r.pos), ACCENT if me else TEXT, me,
                    name_color=TEXT_FAINT if car.gone else TEXT)
        (_, _, x1, _) = cols[4]
        self._text(x1, cy, st.fmt_ir(car.irating), F_SMALL, "bold", TEXT_DIM, mono=True, anchor="e")
        (_, _, x1, _) = cols[5]
        inc_col = BRAKE if car.incidents >= 12 else (VOICE if car.incidents >= 8 else TEXT_DIM)
        self._text(x1, cy, st.fmt_inc(car.incidents), F_SMALL, "bold" if me else "normal",
                   inc_col, mono=True, anchor="e")
        (_, _, x1, _) = cols[6]
        pb = car.last_lap > 0 and car.best_lap > 0 and abs(car.last_lap - car.best_lap) < 1e-3
        self._text(x1, cy, st.fmt_lap(car.last_lap), F_ROW,
                   fill=ACCENT if pb else TEXT, mono=True, anchor="e")
        (_, _, x1, _) = cols[7]
        self._text(x1, cy, st.fmt_lap(car.best_lap), F_ROW,
                   fill=MANAGE if r.fastest else TEXT_DIM, mono=True, anchor="e")


# ---------------------------------------------------------------------------
# Relative: quien tengo delante y detras en pista
# ---------------------------------------------------------------------------


class RelativePanel(Panel):
    VIEW = "relative"
    COLS = REL_COLS

    def __init__(self, root, feed, scale, pos, around: int):
        super().__init__(root, feed, scale, pos)
        self.around = around

    def draw(self, snap: SessionSnapshot, blocks: list[st.ClassBlock]) -> None:
        s = self.s
        c = self.canvas
        rows = st.build_relative(snap, self.around, blocks)
        if not rows:
            self.draw_waiting("Relative: no estás en la sesión")
            return
        class_index = {b.class_id: i for i, b in enumerate(blocks)}
        me = snap.me
        mine = next((b for b in blocks if b.is_mine), None)
        accent = self._class_color(mine.class_name, class_index.get(mine.class_id, 0)) if mine else ACCENT
        height = _relative_height(rows)
        c.config(width=self.w * s, height=height * s)
        c.delete("all")
        self._card(0, 0, self.w * s, height * s, hdr_h=H_HDR * s, accent=accent)
        cy = H_HDR * s / 2
        x = PAD * s
        if me and mine:
            my = next((r for r in mine.rows if r.is_me), None)
            if mine.class_name:
                x += self._chip(x, cy, mine.class_name[:10], accent,
                                size=F_TINY + 2, h=18) + 10 * s
            if my is not None:
                x += self._text(x, cy, f"P{my.pos}", F_ROW, "bold", ACCENT, mono=True) + 6 * s
                x += self._text(x, cy, f"de {mine.n}", F_SMALL, fill=TEXT_DIM) + 14 * s
            self._text(x, cy, st.fmt_inc(me.incidents), F_ROW, "bold",
                       BRAKE if me.incidents >= 12 else (VOICE if me.incidents >= 8 else TEXT_DIM),
                       mono=True)
        self._text((self.w - PAD) * s, cy, _laps_text(snap), F_ROW, "bold", TEXT_DIM, anchor="e")
        y = H_HDR * s
        for i, r in enumerate(rows):
            row_h = _relative_row_height(r)
            self._row_bg(y, r.is_me, i % 2 == 1, self.w * s, row_h)
            self._row(r, y, class_index, row_h)
            y += row_h * s

    def _row(self, r: st.RelRow, y: float, class_index: dict[int, int], row_h: int = H_ROW) -> None:
        s = self.s
        cy = y + row_h * s / 2
        car = r.car
        cols = list(self._cols())
        color = self._class_color(car.class_name, class_index.get(car.class_id, 0))
        # El color del nombre dice la relacion de vuelta, como el relative de
        # iRacing: rojo me dobla, azul le doblo, blanco misma vuelta.
        if r.is_me:
            name_col = TEXT
        elif car.on_pit_road:
            name_col = TEXT_FAINT
        elif r.laps_diff > 0:
            name_col = BRAKE
        elif r.laps_diff < 0:
            name_col = LIFT
        else:
            name_col = TEXT
        pos_txt = str(r.class_pos) if r.class_pos > 0 else "—"
        self._ident(cols, cy, car, pos_txt, ACCENT if r.is_me else color, r.is_me,
                    name_color=name_col, lic_slot=4)
        (_, x0, x1, _) = cols[3]
        if r.is_me:
            self._chip(x0, cy, "TÚ", ACCENT, filled=True, w=(x1 - x0) / s)
        elif car.class_name:
            self._chip(x0, cy, car.class_name[:6], color, w=(x1 - x0) / s)
        (_, _, x1, _) = cols[5]
        self._text(x1, cy, st.fmt_ir(car.irating), F_SMALL, "bold", TEXT_DIM, mono=True, anchor="e")
        (_, x0, x1, _) = cols[6]
        if r.is_me:
            return
        if car.on_pit_road:
            self._chip(x0, cy, "PIT", TEAL, w=(x1 - x0) / s)
        else:
            self._text(x1, cy, st.fmt_gap(r.rel_s), F_ROW, "bold", TEXT, mono=True, anchor="e")


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------


def _feed(source, feed: Feed, recorder: SessionRecorder | None) -> None:
    import traceback

    try:
        for n, snap in enumerate(source.snapshots(), start=1):
            if recorder:
                recorder.write(snap)
            feed.push(snap)
            if n == 1:
                print(f"[overlay] primera foto: {len(snap.cars)} coches, sesion {snap.session_type}", flush=True)
        feed.set_status("Fin de la grabación")
    except BaseException as exc:  # que el hilo no muera en silencio
        print(f"[overlay] fuente parada: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        feed.set_status(f"Sin datos: {type(exc).__name__}: {exc}"[:80])


def _parse_pos(text: str | None, view: str, default: tuple[int, int]) -> tuple[int, int]:
    if text:
        x, y = (int(v) for v in text.split(","))
        return x, y
    return load_pos(view=view) or default


def main() -> None:
    ap = argparse.ArgumentParser(description="Clasificacion con iRating estimado y relative, encima del juego")
    ap.add_argument("--replay", help="JSONL grabado con --record (para el Mac)")
    ap.add_argument("--speed", type=float, default=1.0, help="velocidad del replay (0 = a tope)")
    ap.add_argument("--record", help="graba la sesion en vivo a este JSONL")
    ap.add_argument("--no-standings", action="store_true", help="sin el panel de clasificacion")
    ap.add_argument("--relative", action="store_true", help="ademas, el panel de relative")
    ap.add_argument("--top", type=int, default=3, help="primeros de cada clase que se ven")
    ap.add_argument("--around", type=int, default=2, help="coches alrededor de mi en la clasificacion")
    ap.add_argument("--rel-around", type=int, default=3, help="coches delante y detras en el relative")
    ap.add_argument("--scale", type=float, default=1.0, help="tamano de los paneles")
    ap.add_argument("--pos", default=None,
                    help="esquina superior izquierda de la clasificacion, x,y. Si se omite, "
                         "la ultima posicion donde se dejo arrastrada (o 28,28 la primera vez)")
    ap.add_argument("--rel-pos", default=None, help="idem para el relative (o 28,420)")
    args = ap.parse_args()

    if args.record and args.replay:
        raise SystemExit("--record es para la sesion en vivo, no para un replay.")
    if args.no_standings and not args.relative:
        raise SystemExit("Sin clasificacion ni relative no hay nada que ensenar.")

    root = tk.Tk()
    root.withdraw()  # la raiz no se ve: los paneles son ventanas hijas
    feed = Feed()
    panels: list[Panel] = []
    if not args.no_standings:
        panels.append(StandingsPanel(root, feed, args.scale, _parse_pos(args.pos, "standings", (28, 28)),
                                     args.top, args.around))
    if args.relative:
        panels.append(RelativePanel(root, feed, args.scale, _parse_pos(args.rel_pos, "relative", (28, 420)),
                                    args.rel_around))

    source = make_session_source(args.replay, speed=args.speed)
    recorder = SessionRecorder(args.record) if args.record else None
    if recorder:
        print(f"[overlay] grabando en {args.record}", flush=True)
    threading.Thread(target=_feed, args=(source, feed, recorder), daemon=True).start()

    for p in panels:
        p.tick()
    try:
        root.mainloop()
    finally:
        source.close()
        if recorder:
            recorder.close()


if __name__ == "__main__":
    main()
