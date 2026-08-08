from __future__ import annotations

import unittest

from formatter import format_dailies_index, format_daily, format_story


class FormatterBehaviorTests(unittest.TestCase):
    def test_daily_reports_omitted_sections_and_items_explicitly(self) -> None:
        data = {
            "report": {
                "date": "2026-08-08",
                "sections": [
                    {
                        "label": "要闻",
                        "items": [{"title": f"item-{i}"} for i in range(25)],
                    }
                ],
                "flashes": [{"title": f"flash-{i}"} for i in range(25)],
            }
        }
        text = format_daily(data)
        self.assertIn("item-0", text)
        self.assertIn("5 条省略", text)
        self.assertIn("快讯", text)
        self.assertIn("5 条省略", text)

    def test_dailies_index_displays_all_api_entries(self) -> None:
        data = {"items": [{"date": f"2026-08-{i:02d}"} for i in range(1, 26)]}
        text = format_dailies_index(data)
        self.assertIn("2026-08-25", text)
        self.assertNotIn("仅显示前 20", text)

    def test_story_shows_recent_reports_in_api_order_and_notes_remaining(self) -> None:
        reports = [
            {"title": f"report-{i}", "links": {"original": f"https://example/{i}"}}
            for i in range(12)
        ]
        text = format_story({"story": {"title": "Event", "reports": reports}})
        self.assertLess(
            text.index("https://example/0"), text.index("https://example/1")
        )
        self.assertIn("report-0", text)
        self.assertIn("另有 2 条省略", text)


if __name__ == "__main__":
    unittest.main()
