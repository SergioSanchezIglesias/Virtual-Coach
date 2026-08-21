"""Focused rendering contracts for the compact Tk overlays."""

from __future__ import annotations

from typing import cast

import overlay as ov
import standings as st
from source import CarState


class _RelativeRowProbe:
    """Records the visual affordances emitted by ``RelativePanel._row``."""

    s = 1.0
    w = ov._width(ov.REL_COLS)
    mono = "TkFixedFont"
    ui = "TkDefaultFont"

    def __init__(self):
        self.chips = []
        self.ident_calls = []

    def _cols(self):
        yield from ((name, x0, x1, anchor) for name, x0, x1, anchor in [
            ("POS", 10, 32, "w"), ("#", 40, 74, "w"), ("PILOTO", 82, 194, "w"),
            ("CLASE", 202, 246, "w"), ("LIC", 254, 300, "w"), ("iR", 308, 348, "e"),
            ("REL", 356, 408, "e"),
        ])

    def _class_color(self, name, index):
        return ov.LIFT

    def _row_bg(self, *args):
        pass

    def _ident(self, *args, **kwargs):
        self.ident_calls.append(args)

    def _chip(self, *args, **kwargs):
        self.chips.append((args[2], kwargs.get("filled", False)))

    def _text(self, *args, **kwargs):
        pass


def _car():
    return CarState(
        idx=1, number="7", name="Player Driver", class_id=1, class_name="GT3",
        irating=3200, license="A 3.5", class_pos=4, pos=4, lap=10,
        lap_dist_pct=0.5, f2_time=0.0, last_lap=100.0, best_lap=99.0,
        on_pit_road=False, in_world=True, is_me=True,
    )


def test_standings_compact_columns_omit_gap_and_interval():
    assert [name for name, _, _ in ov.COLS] == [
        "POS", "#", "PILOTO", "LIC", "iR", "INC", "ÚLTIMA", "MEJOR",
    ]


def test_relative_player_row_uses_a_filled_you_chip():
    panel = _RelativeRowProbe()
    row = st.RelRow(car=_car(), rel_s=0.0, laps_diff=0, class_pos=4)

    ov.RelativePanel._row(cast(ov.RelativePanel, panel), row, 24, {1: 0}, ov.H_PLAYER_ROW)

    assert ("TÚ", True) in panel.chips
    assert panel.ident_calls[0][1] == 24 + ov.H_PLAYER_ROW / 2


def test_relative_player_row_has_a_dedicated_height_in_canvas_layout():
    row = st.RelRow(car=_car(), rel_s=0.0, laps_diff=0, class_pos=4)

    assert ov.H_PLAYER_ROW > ov.H_ROW
    assert ov._relative_row_height(row) == ov.H_PLAYER_ROW
    assert ov._relative_height([row]) == ov.H_HDR + ov.H_PLAYER_ROW
