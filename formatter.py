"""AstrBot-independent, bounded renderers for AI HOT API responses."""

from __future__ import annotations

from typing import Any

ATTR_TEXT = "数据来源：AI HOT（https://aihot.virxact.com/）"
MAX_MESSAGE_CHARS = 12_000
MAX_ITEMS_PER_REPLY = 30
MAX_DAILY_SECTIONS = 10
MAX_DAILY_ITEMS_PER_SECTION = 20
MAX_DAILY_FLASHES = 20
MAX_DAILIES_INDEX_ENTRIES = 180
MAX_STORY_REPORTS = 10
MAX_FIELD_CHARS = 800
MAX_LINK_CHARS = 1_500

CATEGORY_LABELS = {
    "ai-models": "模型",
    "ai-products": "产品",
    "industry": "产业",
    "paper": "论文",
    "tip": "技巧",
}
_STATUS_LABELS = {"active": "进行中", "settled": "已完结"}


def _clip(text: Any, limit: int | None = MAX_FIELD_CHARS) -> str:
    """Collapse whitespace and cap one user-visible field."""

    if not text:
        return ""
    flat = " ".join(str(text).split())
    if limit is None or len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _source_name(obj: dict | None) -> str:
    return str(((obj or {}).get("source") or {}).get("name") or "")


def _link(obj: dict | None, *keys: str) -> str | None:
    links = (obj or {}).get("links") or {}
    for key in keys:
        if links.get(key):
            return _clip(links[key], MAX_LINK_CHARS)
    return None


def _append_links(
    lines: list[str],
    obj: dict | None,
    *,
    indent: str = "   ",
    primary_keys: tuple[str, ...] = ("aihot",),
    primary_label: str = "详情",
) -> None:
    primary = _link(obj, *primary_keys)
    original = _link(obj, "original")
    if primary:
        lines.append(f"{indent}- {primary_label}: {primary}")
    if original and original != primary:
        lines.append(f"{indent}- 原文: {original}")


def _append_daily_item(lines: list[str], item: dict) -> None:
    lines.append(f"- {_clip(item.get('title')) or '（无标题）'}")
    meta: list[str] = []
    source = _source_name(item)
    if source:
        meta.append(f"来源：{_clip(source, 200)}")
    published = item.get("publishedAt") or item.get("published_at") or item.get("date")
    if published:
        meta.append(f"时间：{_clip(published, 80)}")
    if meta:
        lines.append("   - " + "｜".join(meta))
    _append_links(lines, item)


def _finish(lines: list[str], *, omitted: int = 0) -> str:
    if omitted > 0:
        lines.append(f"…（因消息长度/显示范围限制，另有 {omitted} 条未显示）")
    lines.append("\n" + ATTR_TEXT)
    result = "\n".join(lines)
    if len(result) <= MAX_MESSAGE_CHARS:
        return result
    notice = "\n…（因消息长度限制，部分内容未显示）\n\n" + ATTR_TEXT
    return result[: MAX_MESSAGE_CHARS - len(notice)].rstrip() + notice


def format_items(data: dict, show: int) -> str:
    """Render a v1 ``items`` response without silently dropping entries."""

    items = data.get("items") or []
    if not items:
        return "AI HOT：当前没有符合条件的动态。"
    try:
        requested = max(1, int(show))
    except (TypeError, ValueError):
        requested = 10
    visible = min(requested, MAX_ITEMS_PER_REPLY, len(items))
    lines = ["AI HOT 动态"]
    for i, item in enumerate(items[:visible], 1):
        title = _clip(item.get("title")) or "（无标题）"
        lines.append(f"{i}. {title}")
        summary = _clip(item.get("summary"))
        if summary:
            lines.append(f"   {summary}")
        meta: list[str] = []
        source = _source_name(item)
        if source:
            meta.append(f"来源：{_clip(source, 200)}")
        category = item.get("category")
        if category:
            meta.append(CATEGORY_LABELS.get(category, _clip(category, 100)))
        if meta:
            lines.append("   - " + "｜".join(meta))
        _append_links(lines, item, primary_label="详情")
    omitted = max(0, len(items) - visible)
    if requested < len(items) and requested < MAX_ITEMS_PER_REPLY:
        lines.append(f"…（接口返回 {len(items)} 条，按请求仅显示前 {visible} 条）")
        omitted = 0
    elif requested >= MAX_ITEMS_PER_REPLY and len(items) > visible:
        lines.append(
            f"…（最多显示 {MAX_ITEMS_PER_REPLY} 条，另有 {len(items) - visible} 条）"
        )
        omitted = 0
    return _finish(lines, omitted=omitted)


def format_hot_topics(data: dict) -> str:
    """Render the current hot-topic board."""

    items = data.get("items") or []
    if not items:
        return "AI HOT：当前没有热点话题。"
    visible = min(10, len(items))
    lines = [f"AI HOT 热点榜（{data.get('count') or len(items)}）"]
    for topic in items[:visible]:
        title = _clip(topic.get("title")) or "（无标题）"
        lines.append(f"{topic.get('rank', '?')}. {title}")
        meta: list[str] = []
        source = _source_name(topic)
        if source:
            meta.append(f"来源：{_clip(source, 200)}")
        meta.append(f"报道 {topic.get('sourceCount', 0)} 篇")
        meta.append(f"信号 {topic.get('signalCount', 0)}")
        lines.append("   - " + "｜".join(meta))
        _append_links(
            lines, topic, primary_keys=("story", "aihot"), primary_label="事件"
        )
    if len(items) > visible:
        lines.append(f"…（榜单另有 {len(items) - visible} 条未显示）")
    return _finish(lines)


def format_daily(data: dict) -> str:
    """Render a daily report with bounded, explicitly counted sections."""

    report = data.get("report") or {}
    if not report:
        return "AI HOT：暂无可用的日报。"
    lines = [f"AI HOT 日报 {report.get('date', '')}".rstrip()]
    lead = report.get("lead") or {}
    title = _clip(lead.get("title"))
    paragraph = _clip(lead.get("leadParagraph"))
    if title:
        lines.append(title)
    if paragraph:
        lines.append(paragraph)

    sections = report.get("sections") or []
    section_visible = min(MAX_DAILY_SECTIONS, len(sections))
    omitted = max(0, len(sections) - section_visible)
    for section in sections[:section_visible]:
        lines.append("")
        lines.append(f"【{_clip(section.get('label'), 100) or '要闻'}】")
        section_items = section.get("items") or []
        item_visible = min(MAX_DAILY_ITEMS_PER_SECTION, len(section_items))
        for item in section_items[:item_visible]:
            _append_daily_item(lines, item)
        if len(section_items) > item_visible:
            lines.append(f"…（本节另有 {len(section_items) - item_visible} 条省略）")

    flashes = report.get("flashes") or []
    if flashes:
        lines.append("")
        lines.append("【快讯】")
        flash_visible = min(MAX_DAILY_FLASHES, len(flashes))
        for flash in flashes[:flash_visible]:
            _append_daily_item(lines, flash)
        if len(flashes) > flash_visible:
            lines.append(f"…（快讯另有 {len(flashes) - flash_visible} 条省略）")
    lines.append("")
    _append_links(lines, report, indent="", primary_label="日报")
    return _finish(lines, omitted=omitted)


def format_dailies_index(data: dict) -> str:
    """Render exactly the API-returned date range, subject to a hard bound."""

    entries = data.get("items") or []
    if not entries:
        return "AI HOT：暂无日报索引。"
    visible = min(MAX_DAILIES_INDEX_ENTRIES, len(entries))
    lines = ["AI HOT 日报索引"]
    for entry in entries[:visible]:
        date = _clip(entry.get("date"), 80)
        lead = _clip(entry.get("leadTitle"))
        lines.append(f"· {date} {lead}".rstrip())
    return _finish(lines, omitted=max(0, len(entries) - visible))


def format_story(data: dict) -> str:
    """Render the newest story reports first, matching the API order."""

    story = data.get("story") or {}
    if not story:
        return "AI HOT：未找到该事件。"
    title = _clip(story.get("title")) or "（无标题）"
    status = _STATUS_LABELS.get(story.get("status", ""), _clip(story.get("status", "")))
    lines = [f"{title}（{status}）" if status else title]
    digest = _clip(story.get("digest"))
    if digest:
        lines.append(digest)
    latest = _clip(story.get("latest"))
    if latest:
        lines.append(f"最新进展：{latest}")
    lines.append(
        f"· 报道 {story.get('reportCount', 0)} 篇｜来源 {story.get('sourceCount', 0)} 个"
    )
    _append_links(lines, story, indent="", primary_label="详情")

    reports = story.get("reports") or []
    visible = min(MAX_STORY_REPORTS, len(reports))
    if reports:
        lines.append("")
        lines.append("【最近报道时间线】")
    for report in reports[:visible]:
        report_title = _clip(report.get("title")) or "（无标题）"
        timestamp = (
            report.get("publishedAt")
            or report.get("published_at")
            or report.get("date")
        )
        if timestamp:
            report_title += f"（{_clip(timestamp, 80)}）"
        lines.append(f"- {report_title}")
        source = _source_name(report)
        if source:
            lines.append(f"   - 来源：{_clip(source, 200)}")
        _append_links(lines, report)
    if len(reports) > visible:
        lines.append(
            f"…（时间线仅显示最近 {visible} 条，另有 {len(reports) - visible} 条省略）"
        )
    return _finish(lines)
