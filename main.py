"""AI HOT AstrBot plugin.

The plugin uses AI HOT's anonymous, read-only REST API v1 and keeps all
AstrBot handler registration on :class:`AihotPlugin`.  Rendering lives in the
AstrBot-independent :mod:`formatter` module so it can be tested without a
running AstrBot process.
"""

from __future__ import annotations

import functools
import inspect
from zoneinfo import ZoneInfo

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import CustomFilter, PermissionType
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

from .client import AihotAPIError, AihotClient, AihotError
from .formatter import (
    ATTR_TEXT,
    format_dailies_index,
    format_daily,
    format_hot_topics,
    format_items,
    format_story,
)

PUSH_JOB_ID = "aihot_daily_push"
PUSH_TARGET_KV = "aihot_push_target"
DEFAULT_PUSH_TIME = "08:00"
DEFAULT_PUSH_TZ = "Asia/Shanghai"


class _NotBareAihotFilter(CustomFilter):
    """Route only subcommands to the command group."""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        return event.message_str.strip() != "aihot"


class _BareAihotFilter(CustomFilter):
    """Match only a bare ``aihot`` invocation."""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        return event.is_at_or_wake_command and event.message_str.strip() == "aihot"


def _help_text() -> str:
    return (
        "AI HOT 指令：\n"
        "· /aihot items [数量] 最新动态\n"
        "· /aihot hot 热点榜\n"
        "· /aihot daily [YYYY-MM-DD] 日报\n"
        "· /aihot dailies [数量] 日报索引\n"
        "· /aihot story <publicId> 事件详情\n"
        "· /aihot search <关键词> 关键词搜索\n"
        "· /aihot push on 开启实验性每日推送（管理员）\n"
        "· /aihot push off 关闭实验性每日推送（管理员）\n"
        "\n推送首次必须在目标会话执行 push on；当前仅保存一个目标，后一次开启会覆盖前一次。"
        "\n" + ATTR_TEXT
    )


class AihotPlugin(Star):
    """AI HOT command handlers and lifecycle."""

    # Register handlers on the plugin class.  AstrBot binds these functions to
    # the live instance when it activates the Star.
    @filter.command_group("aihot")
    def _aihot_group(self):
        """AI HOT command group."""

    _aihot_group.parent_group.add_custom_filter(_NotBareAihotFilter())

    @filter.custom_filter(_BareAihotFilter)
    async def _aihot_bare(self, event: AstrMessageEvent):
        return await self._aihot_help(event)

    @_aihot_group.command("help")
    async def _aihot_help(self, event: AstrMessageEvent):
        return event.plain_result(_help_text())

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
                self._client.get_daily(date)
                if date
                else self._client.get_latest_daily()
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
            return format_items(data, show).replace(
                "AI HOT 动态", f"搜索“{keyword}”", 1
            )

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
                "用法：/aihot push on 开启实验性每日推送；/aihot push off 关闭。"
            )
        if action == "on":
            target = str(getattr(event, "unified_msg_origin", "") or "").strip()
            if not target:
                return event.plain_result("开启推送失败：当前会话没有可保存的目标。")
            if not await self._schedule_push(target):
                return event.plain_result("开启推送失败：无法访问定时调度器。")
            self._push_target = target
            await self.put_kv_data(PUSH_TARGET_KV, target)
            self.config["push_enable"] = True
            await self._save_config()
            hh, mm, tz = self._push_schedule()
            return event.plain_result(
                f"已开启 AI HOT 每日推送，将于每天 {hh:02d}:{mm:02d}（{tz}）推送到本会话。"
            )
        if not await self._unschedule_push():
            return event.plain_result("关闭推送失败：定时任务仍保留，未修改配置。")
        self._push_target = None
        await self.delete_kv_data(PUSH_TARGET_KV)
        self.config["push_enable"] = False
        await self._save_config()
        return event.plain_result("已关闭 AI HOT 每日推送。")

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        self._client = AihotClient(logger=self.logger)
        self._push_target: str | None = None
        self._push_job_id: str | None = None

    async def initialize(self) -> None:
        """Recreate the HTTP client and restore a valid scheduled push."""

        await self._client.close()
        self._client = AihotClient(logger=self.logger)
        self._push_target = await self.get_kv_data(PUSH_TARGET_KV, None)
        if not self.config.get("push_enable", False):
            return
        if not self._push_target:
            self.logger.warning(
                "AI HOT push_enable is true but no target session is stored; disabling push."
            )
            self.config["push_enable"] = False
            await self._save_config()
            return
        if not await self._schedule_push(self._push_target):
            self.logger.warning("AI HOT push could not be restored; disabling push.")
            self.config["push_enable"] = False
            await self._save_config()

    async def terminate(self) -> None:
        if not await self._unschedule_push():
            self.logger.error("AI HOT push cleanup failed during plugin termination.")
        await self._client.close()

    # ----------------------------------------------------------------- push

    async def _schedule_push(self, target: str) -> bool:
        """Schedule one target through CronJobManager's public API."""

        if not target:
            return False
        hh, mm, tz = self._push_schedule()
        cron = getattr(self.context, "cron_manager", None)
        add_basic_job = getattr(cron, "add_basic_job", None)
        if not callable(add_basic_job):
            self.logger.error("AI HOT push scheduling API is unavailable.")
            return False
        old_job_id = self._push_job_id
        try:
            job_result = add_basic_job(
                name=PUSH_JOB_ID,
                cron_expression=f"{mm} {hh} * * *",
                handler=functools.partial(self._run_push, target),
                description="AI HOT experimental daily push",
                timezone=tz,
                persistent=False,
            )
            job = await job_result if inspect.isawaitable(job_result) else job_result
        except Exception as exc:  # noqa: BLE001
            self.logger.error("AI HOT push scheduling failed: %s", exc)
            return False
        new_job_id = getattr(job, "job_id", None)
        if not new_job_id:
            self.logger.error("AI HOT push scheduler returned no job id.")
            return False

        if old_job_id and old_job_id != new_job_id:
            delete_job = getattr(cron, "delete_job", None)
            if not callable(delete_job):
                self.logger.error("AI HOT push cleanup API is unavailable.")
                await self._rollback_new_job(cron, new_job_id)
                return False
            try:
                result = delete_job(old_job_id)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                self.logger.error("AI HOT old push job cleanup failed: %s", exc)
                await self._rollback_new_job(cron, new_job_id)
                return False

        self._push_job_id = new_job_id
        self.logger.info(
            "AI HOT scheduled daily push to %s at %02d:%02d (%s).", target, hh, mm, tz
        )
        return True

    async def _rollback_new_job(self, cron, job_id: str) -> None:
        delete_job = getattr(cron, "delete_job", None)
        if not callable(delete_job):
            return
        try:
            result = delete_job(job_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            self.logger.error("AI HOT new push job rollback failed: %s", exc)

    async def _unschedule_push(self) -> bool:
        cron = getattr(self.context, "cron_manager", None)
        if not self._push_job_id:
            return True
        delete_job = getattr(cron, "delete_job", None)
        if not callable(delete_job):
            self.logger.error("AI HOT push cleanup API is unavailable.")
            return False
        try:
            result = delete_job(self._push_job_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            self.logger.error("AI HOT push cleanup failed: %s", exc)
            return False
        self._push_job_id = None
        return True

    async def _run_push(self, target: str) -> None:
        chain = await self._build_push_message()
        if chain is None:
            self.logger.warning("AI HOT push: nothing to send, skipped.")
            return
        try:
            await self.context.send_message(target, chain)
        except Exception as exc:  # noqa: BLE001 - never break scheduler loop
            self.logger.error("AI HOT push to %s failed: %s", target, exc)

    async def _build_push_message(self) -> MessageChain | None:
        parts: list[str] = []
        try:
            daily = await self._client.get_latest_daily()
            parts.append(format_daily(daily))
        except AihotError as exc:
            self.logger.warning("AI HOT push: latest daily unavailable: %s", exc)
        if self.config.get("push_include_hot", True):
            try:
                hot = await self._client.get_hot_topics()
                parts.append(format_hot_topics(hot))
            except AihotError as exc:
                self.logger.warning("AI HOT push: hot topics unavailable: %s", exc)
        if not parts:
            return None
        return MessageChain().message("\n\n".join(parts))

    # ----------------------------------------------------------------- utils

    async def _run(self, event, coro_factory, formatter):
        """Run an API call with shared user-facing error handling."""

        try:
            data = await coro_factory()
        except ValueError as exc:
            return event.plain_result(f"参数有误：{exc}")
        except AihotError as exc:
            return event.plain_result(self._error_text(exc))
        return event.plain_result(formatter(data))

    async def _save_config(self) -> None:
        save = getattr(self.config, "save_config_async", None)
        if callable(save):
            result = save()
            if inspect.isawaitable(result):
                await result

    def _int_config(self, key: str, default: int) -> int:
        try:
            return max(1, int(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _push_schedule(self) -> tuple[int, int, str]:
        """Resolve push time and timezone from config with safe fallbacks."""

        hh, mm = self._parse_push_time(self.config.get("push_time", DEFAULT_PUSH_TIME))
        tz = self.config.get("push_timezone", DEFAULT_PUSH_TZ)
        try:
            ZoneInfo(tz)
        except (KeyError, TypeError, ValueError):
            self.logger.warning(
                "AI HOT invalid push_timezone %r; falling back to %s.",
                tz,
                DEFAULT_PUSH_TZ,
            )
            tz = DEFAULT_PUSH_TZ
        return hh, mm, tz

    @staticmethod
    def _parse_push_time(raw: str) -> tuple[int, int]:
        try:
            hh, mm = str(raw).split(":")
            hour, minute = int(hh), int(mm)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (TypeError, ValueError):
            hour, minute = 8, 0
        return hour, minute

    @staticmethod
    def _error_text(exc: AihotError) -> str:
        if isinstance(exc, AihotAPIError):
            suffix = f"（requestId: {exc.request_id}）" if exc.request_id else ""
            return f"AI HOT 接口返回错误：{exc.code}{suffix}"
        return f"AI HOT 获取数据失败：{exc}"
