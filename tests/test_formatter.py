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
    def test_reset_uses_qualified_label_and_preserves_unknown_scope(self):
        event = {
            "type": "direct_reset",
            "status": "announced",
            "displayLabel": "重置（形式未明确）",
            "scope": "所有用户",
            "presentation": {"scopeKnown": False, "scopeLabel": None},
        }
        text = format_codex_resets({"events": [event]})
        self.assertIn("重置（形式未明确）｜预告", text)
        self.assertIn("适用范围：未明确", text)
        self.assertNotIn("全员", text)
        self.assertNotIn("所有用户", text)
        event.pop("displayLabel")
        event["presentation"] = None
        text = format_codex_resets({"events": [event]})
        self.assertNotIn("全员", text)
        self.assertIn("适用范围：所有用户", text)

    def test_reset_qualified_scope_keeps_conditions_separate_from_products(self):
        text = format_codex_resets(
            {
                "events": [
                    {
                        "type": "direct_reset",
                        "displayLabel": "额度重置",
                        "scope": "所有用户",
                        "presentation": {
                            "status": "in_progress",
                            "scopeKnown": True,
                            "scopeLabel": "所有付费用户（符合原帖条件）",
                            "audienceZh": "所有付费用户",
                            "productsZh": "Codex、ChatGPT Work",
                            "reportedAt": "2026-09-26T00:00:00Z",
                        },
                    }
                ]
            }
        )
        self.assertIn("额度重置｜进行中（尚未确认完成）", text)
        self.assertIn("适用范围：所有付费用户（符合原帖条件）", text)
        self.assertIn("适用产品：Codex、ChatGPT Work", text)
        self.assertIn("开始生效公告时间（非到账或完成时间）：2026-09-26 08:00", text)

    def test_reset_estimates_and_inferred_statuses_are_not_confirmations(self):
        for status, label in (
            ("expired_unconfirmed", "预计窗口已过（尚未确认）"),
            ("likely_completed", "推测已完成（非官方确认）"),
        ):
            with self.subTest(status=status):
                text = format_codex_resets(
                    {
                        "events": [
                            {
                                "status": "announced",
                                "presentation": {
                                    "status": status,
                                    "timeInferred": True,
                                },
                                "schedule": {"label": "下周"},
                                "estimate": {
                                    "from": "2026-09-29T19:00:00Z",
                                    "through": "2026-09-30T19:00:00Z",
                                    "basis": "model",
                                    "reason": "未给具体日期",
                                },
                            }
                        ]
                    }
                )
                self.assertIn(label, text)
                self.assertIn("原始预告（非实际执行时间）：下周", text)
                self.assertIn("预告时间换算含日期或时区推断", text)
                self.assertIn(
                    "预计生效（仅供参考，以实际到账为准）：2026-09-30 03:00 至 2026-10-01 03:00",
                    text,
                )
                self.assertIn("预计依据：模型推算", text)
                self.assertIn("预计说明：未给具体日期", text)
                self.assertIn("已核实发生日期：未知", text)
                self.assertNotIn("确认帖时间", text)
                self.assertNotIn("｜已确认", text)

    def test_reset_prefers_full_translation_with_excerpt_and_original_fallbacks(self):
        for post, expected in (
            ({"fullText": "完整译文", "text": "节选"}, "完整译文"),
            ({"fullText": None, "text": "节选"}, "节选"),
            ({"fullOriginalText": "Original post"}, "Original post"),
        ):
            with self.subTest(post=post):
                text = format_codex_resets({"events": [{"posts": [post]}]})
                self.assertIn(expected, text)
                if post.get("fullText"):
                    self.assertNotIn("节选", text)

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
