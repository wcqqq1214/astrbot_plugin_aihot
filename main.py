"""AI HOT AstrBot plugin.

Aggregates AI industry news, the hot-topic board and daily reports from
AI HOT (https://aihot.virxact.com/) through its anonymous, read-only REST
API v1. See https://aihot.virxact.com/agent for the integration contract.

Public use of the data requires a discoverable attribution statement:
"数据来源：AI HOT" with a link to the site (see the access terms).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import PermissionType
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .client import AihotAPIError, AihotClient, AihotError

ATTR_TEXT = "数据来源：AI HOT（https://aihot.virxact.com/）"
PUSH_JOB_ID = "aihot_daily_push"
PUSH_TARGET_KV = "aihot_push_target"
DEFAULT_PUSH_TIME = "08:00"
DEFAULT_PUSH_TZ = "Asia/Shanghai"

CATEGORY_LABELS = {
    "ai-models": "模型",
    "ai-products": "产品",
    "industry": "产业",
    "paper": "论文",
    "tip": "技巧",
}

_STATUS_LABELS = {"active": "进行中", "settled": "已完结"}


def _clip(text: str | None, limit: int | None = None) -> str:
    """Collapse whitespace in ``text``; truncate to ``limit`` only if given."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    if limit is None or len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _source_name(obj: dict | None) -> str:
    return ((obj or {}).get("source") or {}).get("name", "") or ""


def _link(obj: dict | None, *keys: str) -> str | None:
    links = (obj or {}).get("links") or {}
    for key in keys:
        if links.get(key):
            return str(links[key])
    return None


def _append_links(
    lines: list[str],
    obj: dict | None,
    *,
    indent: str = "   ",
    primary_keys: tuple[str, ...] = ("aihot",),
    primary_label: str = "详情",
) -> None:
    """Append the AI HOT in-site link and the third-party original link.

    The AI HOT terms require redistribution to retain the original entry
    link, and ask users to verify facts against the original source, so
    both are rendered whenever present.
    """
    primary = _link(obj, *primary_keys)
    original = _link(obj, "original")
    if primary:
        lines.append(f"{indent}- {primary_label}: {primary}")
    if original and original != primary:
        lines.append(f"{indent}- 原文: {original}")


def _append_daily_item(lines: list[str], item: dict) -> None:
    """Render one daily report item/flash with its original entry link."""
    title = item.get("title") or "（无标题）"
    lines.append(f"- {title}")
    meta = []
    source = _source_name(item)
    if source:
        meta.append(f"来源：{source}")
    if meta:
        lines.append("   - " + "｜".join(meta))
    original = _link(item, "original")
    if original:
        lines.append(f"   - 原文: {original}")


# ----------------------------------------------------------------- formatting


def format_items(data: dict, show: int) -> str:
    """Render a v1 ``items`` response as plain text."""
    items = data.get("items") or []
    if not items:
        return "AI HOT：当前没有符合条件的动态。"
    lines = ["AI HOT 动态"]
    for i, item in enumerate(items[:show], 1):
        # Use AI HOT's curated Chinese title so the list reads uniformly,
        # regardless of the source language.
        title = item.get("title") or "（无标题）"
        lines.append(f"{i}. {title}")
        summary = _clip(item.get("summary"))
        if summary:
            lines.append(f"   {summary}")
        meta = []
        source = _source_name(item)
        if source:
            meta.append(f"来源：{source}")
        category = item.get("category")
        if category:
            meta.append(CATEGORY_LABELS.get(category, category))
        if meta:
            lines.append("   - " + "｜".join(meta))
        _append_links(lines, item, primary_label="详情")
    if len(items) > show:
        lines.append(f"…（共 {len(items)} 条，仅显示前 {show} 条）")
    lines.append("\n" + ATTR_TEXT)
    return "\n".join(lines)


def format_hot_topics(data: dict) -> str:
    """Render a v1 ``hot-topics`` response as plain text."""
    items = data.get("items") or []
    if not items:
        return "AI HOT：当前没有热点话题。"
    lines = [f"AI HOT 热点榜（{data.get('count') or len(items)}）"]
    for topic in items[:10]:
        title = topic.get("title") or "（无标题）"
        lines.append(f"{topic.get('rank', '?')}. {title}")
        meta = []
        source = _source_name(topic)
        if source:
            meta.append(f"来源：{source}")
        meta.append(f"报道 {topic.get('sourceCount', 0)} 篇")
        meta.append(f"信号 {topic.get('signalCount', 0)}")
        lines.append("   - " + "｜".join(meta))
        _append_links(
            lines, topic, primary_keys=("story", "aihot"), primary_label="事件"
        )
    lines.append("\n" + ATTR_TEXT)
    return "\n".join(lines)


def format_daily(data: dict) -> str:
    """Render a v1 ``dailies/{date|latest}`` response as plain text."""
    report = data.get("report") or {}
    if not report:
        return "AI HOT：暂无可用的日报。"
    lines = [f"AI HOT 日报 {report.get('date', '')}".rstrip()]
    lead = report.get("lead")
    if lead:
        title = (lead.get("title") or "").strip()
        if title:
            lines.append(title)
        paragraph = _clip(lead.get("leadParagraph"))
        if paragraph:
            lines.append(paragraph)
    sections = report.get("sections") or []
    for section in sections[:3]:
        lines.append("")
        lines.append(f"【{section.get('label') or '要闻'}】")
        for item in (section.get("items") or [])[:5]:
            _append_daily_item(lines, item)
    flashes = report.get("flashes") or []
    if flashes:
        lines.append("")
        lines.append("【快讯】")
        for flash in flashes[:5]:
            _append_daily_item(lines, flash)
    lines.append("")
    _append_links(lines, report, indent="", primary_label="日报")
    lines.append("\n" + ATTR_TEXT)
    return "\n".join(lines)


def format_dailies_index(data: dict) -> str:
    """Render a v1 ``dailies`` index response as plain text."""
    entries = data.get("items") or []
    if not entries:
        return "AI HOT：暂无日报索引。"
    lines = ["AI HOT 日报索引"]
    for entry in entries[:20]:
        date = entry.get("date", "")
        lead = _clip(entry.get("leadTitle"))
        lines.append(f"· {date} {lead}".rstrip())
    lines.append("\n" + ATTR_TEXT)
    return "\n".join(lines)


def format_story(data: dict) -> str:
    """Render a v1 ``stories/{publicId}`` response as plain text."""
    story = data.get("story") or {}
    if not story:
        return "AI HOT：未找到该事件。"
    title = story.get("title") or "（无标题）"
    status = _STATUS_LABELS.get(story.get("status", ""), story.get("status", ""))
    lines = [f"{title}（{status}）".rstrip()]
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
    for report_item in reversed(story.get("reports") or []):
        original = _link(report_item, "original")
        if original:
            lines.append(f"- 原文: {original}")
            break
    lines.append("\n" + ATTR_TEXT)
    return "\n".join(lines)


# -------------------------------------------------------------- command group


@filter.command_group("aihot")
def _aihot_group():
    """AI HOT 聚合指令组。"""


@_aihot_group.command("help")
async def _aihot_help(self, event: AstrMessageEvent):
    text = (
        "AI HOT 指令：\n"
        "· /aihot items [数量] 最新动态\n"
        "· /aihot hot 热点榜\n"
        "· /aihot daily [YYYY-MM-DD] 日报\n"
        "· /aihot dailies 日报索引\n"
        "· /aihot story <publicId> 事件详情\n"
        "· /aihot search <关键词> 关键词搜索\n"
        "· /aihot push on|off 每日推送\n\n" + ATTR_TEXT
    )
    return event.plain_result(text)


@_aihot_group.command("items")
async def _aihot_items(self, event: AstrMessageEvent, limit: int = 10):
    show = self._int_config("items_show_limit", 10)
    return await self._run(
        event,
        lambda: self._client.get_items(limit=limit),
        lambda data: format_items(data, min(limit, show)),
    )


@_aihot_group.command("hot")
async def _aihot_hot(self, event: AstrMessageEvent):
    return await self._run(event, self._client.get_hot_topics, format_hot_topics)


@_aihot_group.command("daily")
async def _aihot_daily(self, event: AstrMessageEvent, date: str = ""):
    return await self._run(
        event,
        lambda: (
            self._client.get_daily(date) if date else self._client.get_latest_daily()
        ),
        format_daily,
    )


@_aihot_group.command("dailies")
async def _aihot_dailies(self, event: AstrMessageEvent, limit: int = 10):
    return await self._run(
        event,
        lambda: self._client.get_dailies(limit=limit),
        format_dailies_index,
    )


@_aihot_group.command("story")
async def _aihot_story(self, event: AstrMessageEvent, public_id: GreedyStr):
    return await self._run(
        event,
        lambda: self._client.get_story(public_id),
        format_story,
    )


@_aihot_group.command("search")
async def _aihot_search(self, event: AstrMessageEvent, keyword: GreedyStr):
    show = self._int_config("items_show_limit", 10)

    def _search_formatter(data: dict) -> str:
        if not (data.get("items") or []):
            return f"AI HOT：没有找到与“{keyword}”相关的动态。"
        return format_items(data, show).replace("AI HOT 动态", f"搜索“{keyword}”")

    return await self._run(
        event,
        lambda: self._client.get_items(q=keyword, mode="all", limit=50),
        _search_formatter,
    )


@_aihot_group.command("push")
@filter.permission_type(PermissionType.ADMIN)
async def _aihot_push(self, event: AstrMessageEvent, action: str = ""):
    if action not in ("on", "off"):
        return event.plain_result(
            "用法：/aihot push on 开启每日推送；/aihot push off 关闭。"
        )
    if action == "on":
        target = event.unified_msg_origin
        if not self._schedule_push(target):
            return event.plain_result("开启推送失败：无法访问定时调度器。")
        self._push_target = target
        await self.put_kv_data(PUSH_TARGET_KV, target)
        self.config["push_enable"] = True
        await self.config.save_config_async()
        hh, mm = self._parse_push_time(self.config.get("push_time", DEFAULT_PUSH_TIME))
        tz = self.config.get("push_timezone", DEFAULT_PUSH_TZ)
        return event.plain_result(
            f"已开启 AI HOT 每日推送，将于每天 {hh:02d}:{mm:02d}（{tz}）推送到本会话。"
        )
    self._unschedule_push()
    self._push_target = None
    await self.delete_kv_data(PUSH_TARGET_KV)
    self.config["push_enable"] = False
    await self.config.save_config_async()
    return event.plain_result("已关闭 AI HOT 每日推送。")


# --------------------------------------------------------------------- plugin


@register(
    "astrbot_plugin_aihot",
    "wcqqq1214",
    "聚合 AI HOT 的 AI 行业动态、热点榜与日报",
    "0.2.0",
)
class AihotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        self._client = AihotClient()
        self._push_target: str | None = None

    async def initialize(self) -> None:
        """(Re)create the HTTP client and re-arm the scheduled push, if enabled."""
        await self._client.close()
        self._client = AihotClient()
        self._push_target = await self.get_kv_data(PUSH_TARGET_KV, None)
        if self.config.get("push_enable", False) and self._push_target:
            self._schedule_push(self._push_target)

    async def terminate(self) -> None:
        self._unschedule_push()
        await self._client.close()

    # ----------------------------------------------------------------- push

    def _scheduler(self):
        """The AstrBot APScheduler instance, or None if unavailable.

        Never call ``start()`` on it: CronJobManager owns its lifecycle, and an early
        start makes CronJobManager.start() raise SchedulerAlreadyRunningError on boot,
        which kills AstrBot's own cron sync. Jobs added to a stopped scheduler fire
        once AstrBot starts it during startup.
        """
        cron = getattr(self.context, "cron_manager", None)
        return getattr(cron, "scheduler", None)

    def _schedule_push(self, target: str) -> bool:
        scheduler = self._scheduler()
        if scheduler is None:
            return False
        hh, mm = self._parse_push_time(self.config.get("push_time", DEFAULT_PUSH_TIME))
        tz = self.config.get("push_timezone", DEFAULT_PUSH_TZ)
        try:
            tzinfo = ZoneInfo(tz)
        except (KeyError, ValueError):
            tzinfo = None
        scheduler.add_job(
            self._run_push,
            trigger=CronTrigger(hour=hh, minute=mm, timezone=tzinfo),
            args=[target],
            id=PUSH_JOB_ID,
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info(
            "AI HOT scheduled daily push to %s at %02d:%02d (%s).", target, hh, mm, tz
        )
        return True

    def _unschedule_push(self) -> None:
        scheduler = self._scheduler()
        if scheduler is None:
            return
        if scheduler.get_job(PUSH_JOB_ID):
            scheduler.remove_job(PUSH_JOB_ID)

    async def _run_push(self, target: str) -> None:
        chain = await self._build_push_message()
        if chain is None:
            logger.warning("AI HOT push: nothing to send, skipped.")
            return
        try:
            await self.context.send_message(target, chain)
        except Exception as exc:  # noqa: BLE001 - never break the scheduler loop
            logger.error("AI HOT push to %s failed: %s", target, exc)

    async def _build_push_message(self) -> MessageChain | None:
        parts = []
        try:
            daily = await self._client.get_latest_daily()
            parts.append(format_daily(daily))
        except AihotError as exc:
            logger.warning("AI HOT push: latest daily unavailable: %s", exc)
        if self.config.get("push_include_hot", True):
            try:
                hot = await self._client.get_hot_topics()
                parts.append(format_hot_topics(hot))
            except AihotError as exc:
                logger.warning("AI HOT push: hot topics unavailable: %s", exc)
        if not parts:
            return None
        return MessageChain().message("\n\n".join(parts))

    # ----------------------------------------------------------------- utils

    async def _run(self, event, coro_factory, formatter):
        """Run an API call with the shared error handling for all commands."""
        try:
            data = await coro_factory()
        except ValueError as exc:
            return event.plain_result(f"参数有误：{exc}")
        except AihotError as exc:
            return event.plain_result(self._error_text(exc))
        return event.plain_result(formatter(data))

    def _int_config(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_push_time(raw: str) -> tuple[int, int]:
        try:
            hh, mm = str(raw).split(":")
            hour, minute = int(hh), int(mm)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            hour, minute = 8, 0
        return hour, minute

    @staticmethod
    def _error_text(exc: AihotError) -> str:
        if isinstance(exc, AihotAPIError):
            suffix = f"（requestId: {exc.request_id}）" if exc.request_id else ""
            return f"AI HOT 接口返回错误：{exc.code}{suffix}"
        return f"AI HOT 获取数据失败：{exc}"
