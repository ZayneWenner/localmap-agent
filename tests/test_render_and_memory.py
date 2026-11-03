"""
Smoke tests for the HTML renderer and the two-layer memory.

Zero third-party dependencies, no Ollama, no network:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from localmap_agent.geo_tools import MapBoard, tool_add_marker  # noqa: E402
from localmap_agent.map_renderer import render_html  # noqa: E402
from localmap_agent.memory import ConversationMemory  # noqa: E402


def _board_with_two_markers() -> dict:
    board = MapBoard()
    tool_add_marker(board, name="Campus", name_zh="西亚斯学院",
                    latitude=34.402844, longitude=113.759351,
                    description="学校主校区。", category="campus")
    tool_add_marker(board, name="East Station", name_zh="郑州东站",
                    latitude=34.7520, longitude=113.7500,
                    description="高铁站，从学校打车约 40 分钟。", category="transport")
    return board.to_dict()


class TestRenderer(unittest.TestCase):
    def test_returns_a_full_document(self):
        html = render_html(_board_with_two_markers())
        self.assertIsInstance(html, str)
        self.assertIn("<html", html.lower())
        self.assertGreater(len(html), 1000)

    def test_embeds_both_markers(self):
        html = render_html(_board_with_two_markers())
        self.assertIn("Campus", html)
        self.assertIn("East Station", html)

    def test_works_with_an_empty_board(self):
        html = render_html(MapBoard().to_dict())
        self.assertIn("<html", html.lower())

    def test_accepts_meta_and_api_key(self):
        html = render_html(
            _board_with_two_markers(),
            api_key="DUMMY-KEY-FOR-TEST",
            meta={"model": "gemma4:e2b", "generated_at": "2026-10-11 20:00:00"},
        )
        self.assertIn("gemma4:e2b", html)
        self.assertIn("<html", html.lower())


class TestMemory(unittest.TestCase):
    def test_window_keeps_only_recent_messages(self):
        m = ConversationMemory(Path("does_not_exist_yet.json"), window=3)
        for i in range(10):
            m.append("user", f"msg-{i}")
        window = m.recent_window()
        self.assertEqual(len(window), 3)
        self.assertEqual(window[0]["content"], "msg-7")
        self.assertEqual(set(window[0]), {"role", "content"})  # ts stripped

    def test_ignores_empty_messages(self):
        m = ConversationMemory(Path("does_not_exist_yet.json"))
        m.append("user", "")
        self.assertEqual(m.items, [])

    def test_facts_roundtrip(self):
        m = ConversationMemory(Path("does_not_exist_yet.json"))
        m.remember_fact("preferred_style", "口语化")
        self.assertEqual(m.recall("preferred_style"), "口语化")
        self.assertEqual(m.recall("missing", "fallback"), "fallback")

    def test_persists_to_disk_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session_memory.json"
            m1 = ConversationMemory(p)
            m1.append("user", "再加两个吃饭的地方")
            m1.remember_fact("last_count", 7)
            m1.save()

            self.assertTrue(p.exists())
            raw = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(raw["facts"]["last_count"], 7)

            m2 = ConversationMemory(p)  # simulates a restart
            self.assertEqual(m2.recall("last_count"), 7)
            self.assertEqual(m2.items[-1]["content"], "再加两个吃饭的地方")

    def test_survives_a_corrupted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session_memory.json"
            p.write_text("{ this is not json", encoding="utf-8")
            m = ConversationMemory(p)
            self.assertEqual(m.items, [])
            self.assertEqual(m.facts, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
