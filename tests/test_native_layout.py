"""Synthetic raw ABI fixtures; no LMU installation required."""

import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lmu_corner_cues.lmu import LMUReader, TelemetryError


class RawMap(bytearray):
    def __init__(self, index=0, player=True, track=b"Track"):
        super().__init__(324820)
        self.close = Mock()
        struct.pack_into("<BBB", self, 128464, 104, index, player)
        if index >= 104:
            return
        telemetry = 128468 + index * 1888
        scoring = 2192 + index * 584
        for offset, value in ((telemetry + 96, track), (telemetry + 32, b"Car"),
                              (scoring + 36, b"Car"), (scoring + 200, b"GT3")):
            self[offset:offset + len(value)] = value
        struct.pack_into("<i", self, telemetry, 7)
        struct.pack_into("<i", self, scoring, 7)
        struct.pack_into("<i", self, telemetry + 20, 3)
        struct.pack_into("<h", self, scoring + 100, 2)
        struct.pack_into("<d", self, scoring + 104, 35)
        struct.pack_into("<dd", self, telemetry + 388, 0, 0)


class NativeLayoutTests(unittest.TestCase):
    def test_last_player_and_pedals(self):
        data = RawMap(index=103, track=b"  Track\0ignored")
        struct.pack_into("<dd", data, 128468 + 103 * 1888 + 388, 0.75, 0.25)
        reader = LMUReader(lambda: data)
        reader.connect()
        sample = reader.read()
        self.assertEqual((sample.track, sample.vehicle, sample.vehicle_class), ("Track", "Car", "GT3"))
        self.assertEqual((sample.lap, sample.distance, sample.throttle, sample.brake), (2, 35, 0.75, 0.25))
        reader.close()

    def test_player_vehicle_ids_must_match_and_not_be_sentinel(self):
        for telemetry_id, scoring_id in ((7, 8), (-1, 7), (7, -1), (-1, -1)):
            with self.subTest(telemetry_id=telemetry_id, scoring_id=scoring_id):
                data = RawMap(index=103)
                struct.pack_into("<i", data, 128468 + 103 * 1888, telemetry_id)
                struct.pack_into("<i", data, 2192 + 103 * 584, scoring_id)
                self.assert_invalid(data, "vehicle IDs.*re-enter a driving session")

    def test_rejects_invalid_pedals(self):
        for name, offset in (("throttle", 388), ("brake", 396)):
            for value in (-0.001, 1.001, float("nan"), float("inf"), -float("inf")):
                with self.subTest(pedal=name, value=value):
                    data = RawMap()
                    struct.pack_into("<d", data, 128468 + offset, value)
                    self.assert_invalid(data)

    def test_rejects_negative_lap_count_and_distance(self):
        for field, offset, fmt, value in (("lap", 100, "<h", -1),
                                           ("distance", 104, "<d", -0.001)):
            with self.subTest(field=field):
                data = RawMap()
                struct.pack_into(fmt, data, 2192 + offset, value)
                self.assert_invalid(data)

    def test_accepts_inclusive_numeric_boundaries_and_zero_vehicle_id(self):
        for throttle, brake in ((0.0, 1.0), (1.0, 0.0)):
            with self.subTest(throttle=throttle, brake=brake):
                data = RawMap()
                struct.pack_into("<i", data, 128468, 0)
                struct.pack_into("<i", data, 2192, 0)
                struct.pack_into("<h", data, 2192 + 100, 0)
                struct.pack_into("<d", data, 2192 + 104, 0.0)
                struct.pack_into("<dd", data, 128468 + 388, throttle, brake)
                reader = LMUReader(lambda data=data: data)
                reader.connect()
                sample = reader.read()
                self.assertEqual((sample.lap, sample.distance, sample.throttle, sample.brake),
                                 (0, 0.0, throttle, brake))
                reader.close()

    def test_invalid_numeric_and_identifiers(self):
        for offset, size in ((128468 + 96, 64), (128468 + 32, 64), (2192 + 36, 64), (2192 + 200, 32)):
            data = RawMap()
            data[offset:offset + size] = b" " * size
            self.assert_invalid(data)
        for offset in (2192 + 104, 128468 + 388, 128468 + 396):
            for value in (float("nan"), float("inf"), -float("inf")):
                data = RawMap()
                struct.pack_into("<d", data, offset, value)
                self.assert_invalid(data)
        for active, index, has_vehicle in ((0, 0, 1), (105, 0, 1), (1, 1, 1), (104, 104, 1), (104, 0, 2)):
            data = RawMap()
            struct.pack_into("<BBB", data, 128464, active, index, has_vehicle)
            self.assert_invalid(data)

    def assert_invalid(self, data, message="driving session"):
        reader = LMUReader(lambda: data)
        reader.connect()
        with self.assertRaisesRegex(TelemetryError, message):
            reader.read()
        reader.close()

    def test_size_and_connection_errors(self):
        for size in (324819, 324821):
            data = RawMap()
            data[:] = bytes(size)
            with self.assertRaisesRegex(TelemetryError, "compatible LMU_Data"):
                LMUReader(lambda data=data: data).connect()
            data.close.assert_called_once_with()
        with self.assertRaisesRegex(TelemetryError, "Connect"):
            LMUReader().read()
        for error in (OSError("absent"), ValueError("incompatible")):
            with self.assertRaises(TelemetryError):
                LMUReader(Mock(side_effect=error)).connect()

    def test_windows_open_is_read_only(self):
        data = RawMap()
        with patch("lmu_corner_cues.lmu.sys.platform", "win32"), patch("lmu_corner_cues.lmu.mmap.mmap", return_value=data) as opener:
            reader = LMUReader()
            reader.connect()
            import mmap
            opener.assert_called_once_with(-1, 324820, tagname="LMU_Data", access=mmap.ACCESS_READ)
            before = bytes(data)
            reader.read()
            self.assertEqual(bytes(data), before)
            reader.close()
