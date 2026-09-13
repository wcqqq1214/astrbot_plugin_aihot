from __future__ import annotations

import unittest

from formatter import (
    ATTR_TEXT,
    MAX_MESSAGE_CHARS,
    format_codex_resets,
    format_dailies_index,
    format_daily,
    format_latest_codex_reset,
    format_story,
)


class FormatterBehaviorTests(unittest.TestCase):
    def test_latest_reset_ignores_recent_edits_to_old_events(self):
        text = format_latest_codex_reset(
            {
                "events": [
                    {
                        "title": "Old receipt",
                        "occurredOn": "2026-09-04",
                        "createdAt": "2026-09-04T00:00:00+08:00",
                        "updatedAt": "2026-09-13T00:00:00+08:00",
                    },
                    {
                        "title": "Latest reset",
                        "type": "direct_reset",
                        "status": "confirmed",
                        "confirmedAt": "2026-09-12T08:00:00Z",
                    },
                ]
            }
        )
        self.assertIn("Codex 最新重置", text)
        self.assertIn("Latest reset", text)
        self.assertNotIn("Old receipt", text)
        self.assertNotIn("未显示", text)

    def test_latest_reset_includes_new_announcement_without_future_schedule_ranking(
        self,
    ):
        text = format_latest_codex_reset(
            {
                "events": [
                    {
                        "title": "Old estimate",
                        "createdAt": "2026-09-01T00:00:00Z",
                        "schedule": {"from": "2026-10-01T00:00:00Z"},
                    },
                    {
                        "title": "New credit",
                        "type": "reset_credit",
                        "status": "announced",
                        "createdAt": "2026-09-14T00:00:00+08:00",
                    },
                    {"title": "Earlier reset", "confirmedAt": "2026-09-13T15:00:00Z"},
                ]
            }
        )
        self.assertIn("New credit", text)
        self.assertIn("发重置卡｜预告", text)
        self.assertNotIn("Old estimate", text)
        self.assertNotIn("Earlier reset", text)
        self.assertIn("暂无公开重置记录", format_latest_codex_reset({"events": []}))

    def test_reset_receipt_does_not_invent_confirmation_or_execution_time(self):
        text = format_codex_resets(
            {
                "checkedAt": None,
                "events": [
                    {
                        "type": "reset_credit",
                        "status": "confirmed",
                        "confirmationBasis": "receipt_review",
                        "confirmedAt": None,
                        "occurredOn": None,
                        "schedule": {"label": "预计 9月4日 10:12"},
                        "posts": [
                            {
                                "stage": "发卡预告",
                                "text": "稍后发放",
                                "publishedAt": "2026-09-04T00:00:00Z",
                                "url": "https://example.com/post",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertIn("发重置卡｜已确认", text)
        self.assertIn("原始预告（非实际执行时间）", text)
        self.assertIn("回执核验；确认帖时间未知", text)
        self.assertIn("已核实发生日期：未知", text)
        self.assertIn("2026-09-04 08:00", text)
        self.assertIn("发卡预告", text)
        self.assertIn("https://example.com/post", text)

    def test_reset_order_limits_and_attribution_survive_large_notification(self):
        event = {
            "type": "direct_reset",
            "status": "confirmed",
            "title": "x" * 10000,
            "confirmedAt": "2026-09-12T08:09:17Z",
            "posts": [{"text": "y" * 10000, "url": "https://example.com/" + "a" * 2000}]
            * 10,
        }
        text = format_codex_resets({"events": [event] * 40}, 30, notification=True)
        self.assertLessEqual(len(text), MAX_MESSAGE_CHARS)
        self.assertTrue(text.endswith(ATTR_TEXT))
        self.assertIn("确认帖时间（非精确执行时间）：2026-09-12 16:09", text)
        self.assertIn("另有 7 条来源帖未显示", text)
        text = format_codex_resets(
            {"events": [{"title": "first"}, {"title": "second"}]}, 1
        )
        self.assertIn("first", text)
        self.assertNotIn("second", text)
        self.assertIn("另有 1 条未显示", text)
        self.assertIn(ATTR_TEXT, format_codex_resets({"events": []}))

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

    def test_daily_reports_omitted_sections_are_counted(self) -> None:
        data = {
            "report": {
                "sections": [{"label": f"section-{i}"} for i in range(12)],
            }
        }
        text = format_daily(data)
        self.assertIn("section-0", text)
        self.assertNotIn("section-11", text)
        self.assertIn("另有 2 条未显示", text)

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
