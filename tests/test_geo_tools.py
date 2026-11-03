"""
Unit tests for the geometry + guardrail layer (localmap_agent/geo_tools.py).

Zero third-party dependencies: run them with

    python -m unittest discover -s tests -v

They need NO model, NO Ollama and NO network. That is deliberate: the parts
that can be proven deterministically are proven deterministically, and only the
LLM loop is left untested. pytest users can run the same file with `pytest`.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from localmap_agent.geo_tools import (  # noqa: E402
    MAX_DISTANCE_KM,
    SIAS_CENTER,
    VALID_BBOX,
    MapBoard,
    build_schemas,
    haversine_km,
    tool_add_marker,
    tool_compute_distance,
    tool_list_markers,
    tool_remove_marker,
    tool_revise_marker,
    tool_search_place,
    tool_set_map_view,
    wgs84_to_gcj02,
)

CAMPUS = (SIAS_CENTER["lat"], SIAS_CENTER["lng"])


class TestHaversine(unittest.TestCase):
    def test_zero_for_identical_points(self):
        self.assertAlmostEqual(haversine_km(*CAMPUS, *CAMPUS), 0.0, delta=1e-9)

    def test_one_degree_of_longitude_at_equator(self):
        # 1 degree of longitude at the equator is ~111.19 km (WGS-84 mean radius).
        self.assertAlmostEqual(haversine_km(0.0, 0.0, 0.0, 1.0), 111.19, delta=0.5)

    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_km(0.0, 0.0, 1.0, 0.0), 111.19, delta=0.5)

    def test_is_symmetric(self):
        a = haversine_km(34.40, 113.76, 34.75, 114.05)
        b = haversine_km(34.75, 114.05, 34.40, 113.76)
        self.assertAlmostEqual(a, b, delta=1e-9)

    def test_known_campus_distance(self):
        # Sias University -> Zhengzhou East Railway Station is roughly 38 km.
        d = haversine_km(*CAMPUS, 34.7520, 113.7500)
        self.assertTrue(35.0 < d < 42.0, f"got {d}")


class TestCoordinateSystems(unittest.TestCase):
    def test_gcj02_shift_is_in_the_expected_range(self):
        """Inside mainland China the GCJ-02 offset is a few hundred metres."""
        lat, lng = wgs84_to_gcj02(*CAMPUS)
        shift_m = haversine_km(CAMPUS[0], CAMPUS[1], lat, lng) * 1000
        self.assertTrue(100 < shift_m < 1000, f"unexpected GCJ-02 shift: {shift_m:.1f} m")

    def test_gcj02_shift_is_deterministic(self):
        self.assertEqual(wgs84_to_gcj02(*CAMPUS), wgs84_to_gcj02(*CAMPUS))

    def test_gcj02_shift_direction_is_consistent(self):
        """Two nearby points in the same city must shift the same way."""
        base = wgs84_to_gcj02(34.40, 113.76)
        near = wgs84_to_gcj02(34.41, 113.77)
        self.assertGreater((base[0] - 34.40) * (near[0] - 34.41), 0)
        self.assertGreater((base[1] - 113.76) * (near[1] - 113.77), 0)


class TestGuardrails(unittest.TestCase):
    """The guardrails are the reason this is an agent loop and not a one-shot."""

    def test_rejects_out_of_bbox_coordinates(self):
        """Beijing must be rejected - this is the guard against hallucinated coords."""
        board = MapBoard()
        out = tool_add_marker(
            board, name="Beijing", name_zh="北京",
            latitude=39.9042, longitude=116.4074,
            description="x", category="other",
        )
        self.assertFalse(out["ok"])
        self.assertIn("error", out)
        self.assertEqual(len(board.markers), 0)

    def test_rejects_far_away_but_in_bbox_coordinates(self):
        board = MapBoard()
        out = tool_add_marker(
            board, name="Far", name_zh="很远的点",
            latitude=VALID_BBOX["lat_max"], longitude=VALID_BBOX["lng_max"],
            description="x", category="other",
        )
        self.assertFalse(out["ok"])
        self.assertIn("km", out["error"])
        self.assertGreater(MAX_DISTANCE_KM, 0)
        self.assertEqual(len(board.markers), 0)

    def test_rejects_non_numeric_coordinates(self):
        board = MapBoard()
        out = tool_add_marker(
            board, name="Bad", name_zh="坏数据",
            latitude="北纬34度", longitude=None,
            description="x", category="other",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(len(board.markers), 0)

    def test_accepts_a_legitimate_place(self):
        board = MapBoard()
        out = tool_add_marker(
            board, name="Zhengzhou East", name_zh="郑州东站",
            latitude=34.7520, longitude=113.7500,
            description="高铁站，从学校打车约 40 分钟。", category="transport",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["marker_id"], 1)
        self.assertGreater(out["distance_from_sias_km"], 0)
        self.assertEqual(len(board.markers), 1)


class TestBoardOperations(unittest.TestCase):
    def _add(self, board, i=0, **kw):
        return tool_add_marker(
            board,
            name=kw.get("name", f"P{i}"),
            name_zh=kw.get("name_zh", f"点{i}"),
            latitude=kw.get("latitude", 34.41 + i * 0.01),
            longitude=kw.get("longitude", 113.76),
            description=kw.get("description", "d"),
            category=kw.get("category", "other"),
        )

    def test_add_get_remove_roundtrip(self):
        board = MapBoard()
        self._add(board, name_zh="甲")
        self.assertIsNotNone(board.get(1))
        self.assertEqual(board.get(1).name_zh, "甲")
        self.assertTrue(tool_remove_marker(board, 1)["ok"])
        self.assertIsNone(board.get(1))

    def test_ids_increment_and_never_reuse_a_deleted_slot(self):
        board = MapBoard()
        for i in range(3):
            self._add(board, i)
        tool_remove_marker(board, 2)
        self.assertEqual([m.id for m in board.markers], [1, 3])
        self._add(board, 3)
        self.assertEqual(board.markers[-1].id, 4)

    def test_revise_updates_text_and_recomputes_distance(self):
        board = MapBoard()
        self._add(board, name_zh="甲")
        out = tool_revise_marker(board, 1, description="new", latitude=34.80, longitude=113.90)
        self.assertTrue(out["ok"])
        self.assertIn("description", out["changed"])
        self.assertEqual(board.get(1).description, "new")
        self.assertGreater(board.get(1).distance_km, 0)

    def test_revise_ignores_unknown_fields(self):
        board = MapBoard()
        self._add(board, name_zh="甲")
        out = tool_revise_marker(board, 1, hacker_field="x")
        self.assertEqual(out["changed"], [])
        self.assertFalse(hasattr(board.get(1), "hacker_field"))

    def test_revise_missing_marker_returns_false(self):
        self.assertFalse(tool_revise_marker(MapBoard(), 999, description="x")["ok"])

    def test_compute_distance_matches_haversine(self):
        out = tool_compute_distance(34.40, 113.76, 34.75, 114.05)
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(
            out["distance_km"],
            round(haversine_km(34.40, 113.76, 34.75, 114.05), 3),
            delta=1e-6,
        )

    def test_compute_distance_rejects_garbage(self):
        self.assertFalse(tool_compute_distance("abc", 1, 2, 3)["ok"])

    def test_set_view_and_list_markers(self):
        board = MapBoard()
        tool_set_map_view(board, 34.40, 113.76, 13, "校园周边")
        self.assertEqual(board.view, {"lat": 34.40, "lng": 113.76, "zoom": 13})
        self.assertEqual(board.title, "校园周边")
        self._add(board, name_zh="甲", category="food")
        listed = tool_list_markers(board)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["markers"][0]["name_zh"], "甲")

    def test_to_dict_has_a_stable_serialisable_shape(self):
        board = MapBoard()
        self._add(board, name_zh="甲")
        d = board.to_dict()
        self.assertEqual(d["marker_count"], 1)
        self.assertTrue(
            {"id", "name", "name_zh", "latitude", "longitude", "description",
             "category", "distance_km"}.issubset(set(d["markers"][0]))
        )


class TestToolSchemas(unittest.TestCase):
    def test_exposes_every_dispatchable_tool(self):
        names = {s["function"]["name"] for s in build_schemas()}
        self.assertEqual(
            names,
            {"search_place", "add_map_marker", "revise_map_marker",
             "remove_map_marker", "compute_distance", "set_map_view", "list_markers"},
        )

    def test_schema_shape_is_valid_openai_style(self):
        for s in build_schemas():
            self.assertEqual(s["type"], "function")
            fn = s["function"]
            self.assertTrue(fn["name"])
            self.assertTrue(fn["description"])
            self.assertEqual(fn["parameters"]["type"], "object")
            for prop in fn["parameters"].get("properties", {}).values():
                self.assertIn("type", prop)


class TestGeocoderDegradation(unittest.TestCase):
    def test_degrades_gracefully_when_network_is_down(self):
        """If Photon is unreachable the tool must tell the model to fall back
        instead of crashing - the behaviour that saved v1 from a retry loop."""
        with mock.patch("urllib.request.urlopen", side_effect=OSError("network disabled")):
            out = tool_search_place(MapBoard(), "新郑汽车站")
        self.assertFalse(out["ok"])
        self.assertTrue(out["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
