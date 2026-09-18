import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

# Exercise the src-layout package without requiring an installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lmu_corner_cues import CornerMarker, CueEngine, Profile  # noqa: E402


def profile():
    return Profile("circuit", (CornerMarker("T1", 10, 20, 30), CornerMarker("T2", 40, 50, 60)))


class ProfileTests(unittest.TestCase):
    def test_round_trip_with_optional_vehicle(self):
        for vehicle in (None, "GT3"):
            original = Profile("circuit", profile().markers, vehicle)
            restored = Profile.from_json(original.to_json())
            self.assertEqual(restored, original)
            self.assertEqual(restored.to_json(), original.to_json())

    def test_immutable_profile_copies_input(self):
        markers = list(profile().markers)
        parsed = Profile("circuit", markers)  # type: ignore[arg-type]
        markers.clear()
        self.assertEqual(len(parsed.markers), 2)
        with self.assertRaises(FrozenInstanceError):
            parsed.circuit = "other"  # type: ignore[misc]

    def test_malformed_json_and_schema(self):
        for text in ('{', '[]', '{}', '{"circuit":"a","circuit":"b","markers":[]}',
                     '{"circuit":"a","markers":{}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Profile.from_json(text)
        for change in ({"circuit": " "}, {"vehicle": 1}, {"markers": []},
                       {"unknown": True}, {"markers": [{}]}, {"markers": [1]}):
            data = json.loads(profile().to_json())
            data.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                Profile.from_json(json.dumps(data))

    def test_invalid_distances(self):
        for cue in ("BRAKE", "RELEASE_BRAKE", "THROTTLE"):
            for value in (-1, True, "10", None, float("nan"), float("inf")):
                data = json.loads(profile().to_json())
                data["markers"][0][cue] = value
                with self.subTest(cue=cue, value=value), self.assertRaisesRegex(ValueError, "finite non-negative"):
                    Profile.from_json(json.dumps(data))

    def test_invalid_order_and_duplicate_names(self):
        for distances in ((20, 10, 30), (10, 10, 30), (10, 30, 20)):
            with self.subTest(distances=distances), self.assertRaisesRegex(ValueError, "BRAKE <"):
                CornerMarker("T1", *distances)
        for second in (CornerMarker("T2", 25, 35, 45), CornerMarker("T2", 30, 40, 50)):
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                Profile("circuit", (profile().markers[0], second))
        with self.assertRaisesRegex(ValueError, "duplicate marker"):
            Profile("circuit", (profile().markers[0], CornerMarker("T1", 40, 50, 60)))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = CueEngine(profile())

    def test_thresholds_and_one_shot_order(self):
        self.assertEqual(self.engine.update(0, 9), ())
        events = []
        for distance in (10, 20, 30, 40, 50, 60):
            events.extend(self.engine.update(0, distance))
            self.assertEqual(self.engine.update(0, distance), ())
        self.assertEqual([cue.kind for cue in events], ["BRAKE", "RELEASE_BRAKE", "THROTTLE"] * 2)
        self.assertEqual([cue.marker for cue in events], ["T1"] * 3 + ["T2"] * 3)
        self.assertEqual([cue.distance for cue in events], [10, 20, 30, 40, 50, 60])
        self.assertEqual(self.engine.update(0, 100), ())

    def test_first_sample_and_skipped_frames_emit_reached_cues(self):
        self.assertEqual(len(self.engine.update(1, 25)), 2)
        self.assertEqual(len(self.engine.update(1, 100)), 4)

    def test_new_lap_resets_even_at_same_distance(self):
        self.assertEqual(len(self.engine.update(1, 60)), 6)
        cues = self.engine.update(2, 60)
        self.assertEqual(len(cues), 6)
        self.assertTrue(all(cue.lap == 2 for cue in cues))
        self.assertEqual(self.engine.update(2, 60), ())

    def test_same_lap_wrap_waits_for_lap_counter(self):
        self.assertEqual(len(self.engine.update(1, 20)), 2)
        for distance in (0, 10, 30, 100):
            self.assertEqual(self.engine.update(1, distance), ())
        self.assertEqual(len(self.engine.update(2, 10)), 1)

    def test_explicit_session_reset(self):
        self.engine.update(1, 60)
        self.engine.reset()
        self.assertEqual(len(self.engine.update(1, 10)), 1)

    def test_invalid_samples_do_not_mutate_state(self):
        self.engine.update(1, 10)
        for lap, distance in ((True, 20), (-1, 20), (1.5, 20), (2, -1), (2, float("nan"))):
            with self.subTest(lap=lap, distance=distance), self.assertRaises(ValueError):
                self.engine.update(lap, distance)  # type: ignore[arg-type]
        self.assertEqual([cue.kind for cue in self.engine.update(1, 20)], ["RELEASE_BRAKE"])


if __name__ == "__main__":
    unittest.main()
