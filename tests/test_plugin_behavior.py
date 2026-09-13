from __future__ import annotations

import importlib.util
import unittest

ASTRBOT_AVAILABLE = importlib.util.find_spec("astrbot") is not None


@unittest.skipUnless(ASTRBOT_AVAILABLE, "AstrBot is supplied by the host process")
class PluginPushBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from astrbot_plugin_aihot.main import AihotPlugin

        self.AihotPlugin = AihotPlugin

    async def test_webui_enable_without_target_rolls_back(self) -> None:
        class Config(dict):
            saves = 0

            async def save_config_async(self):
                self.saves += 1

        class Context:
            cron_manager = None

        plugin = self.AihotPlugin(Context(), Config(push_enable=True))
        plugin.get_kv_data = lambda key, default=None: _return_none()
        await plugin.initialize()
        self.assertFalse(plugin.config["push_enable"])
        self.assertEqual(plugin.config.saves, 1)

    async def test_push_schedule_uses_public_cron_api_and_one_target(self) -> None:
        class Job:
            def __init__(self, job_id):
                self.job_id = job_id

        class Cron:
            def __init__(self):
                self.added = []
                self.deleted = []

            async def add_basic_job(self, **kwargs):
                self.added.append(kwargs)
                return Job(f"job-{len(self.added)}")

            async def delete_job(self, job_id):
                self.deleted.append(job_id)

        class Context:
            def __init__(self):
                self.cron_manager = Cron()

        class Event:
            def __init__(self, target):
                self.unified_msg_origin = target

            def plain_result(self, text):
                return text

        plugin = self.AihotPlugin(Context(), {})

        saved_targets = []

        async def save_target(key, value):
            saved_targets.append(value)

        plugin.put_kv_data = save_target
        first_result = await plugin._aihot_push(Event("first"), "on")
        second_result = await plugin._aihot_push(Event("second"), "on")
        self.assertIn("已开启", first_result)
        self.assertIn("已开启", second_result)
        self.assertEqual(saved_targets, ["first", "second"])
        self.assertEqual(len(plugin.context.cron_manager.added), 2)
        self.assertEqual(
            plugin.context.cron_manager.added[-1]["timezone"], "Asia/Shanghai"
        )
        self.assertEqual(plugin.context.cron_manager.deleted, ["job-1"])

    async def test_replacing_target_rolls_back_when_old_job_delete_fails(self) -> None:
        class Job:
            def __init__(self, job_id):
                self.job_id = job_id

        class Cron:
            def __init__(self):
                self.added = []
                self.deleted = []

            async def add_basic_job(self, **kwargs):
                self.added.append(kwargs)
                return Job(f"job-{len(self.added)}")

            async def delete_job(self, job_id):
                self.deleted.append(job_id)
                if job_id == "job-1":
                    raise RuntimeError("old job cannot be deleted")

        class Context:
            def __init__(self):
                self.cron_manager = Cron()

        class Event:
            def __init__(self, target):
                self.unified_msg_origin = target

            def plain_result(self, text):
                return text

        plugin = self.AihotPlugin(Context(), {})
        saved_targets = []
        plugin.put_kv_data = lambda key, value: _record(saved_targets, value)
        await plugin._aihot_push(Event("first"), "on")
        result = await plugin._aihot_push(Event("second"), "on")
        self.assertIn("失败", result)
        self.assertEqual(saved_targets, ["first"])
        self.assertEqual(plugin.context.cron_manager.deleted, ["job-1", "job-2"])

    async def test_push_off_keeps_state_when_job_delete_fails(self) -> None:
        class Job:
            job_id = "job-1"

        class Cron:
            async def add_basic_job(self, **kwargs):
                return Job()

            async def delete_job(self, job_id):
                raise RuntimeError("cannot delete")

        class Context:
            def __init__(self):
                self.cron_manager = Cron()

        class Event:
            unified_msg_origin = "target"

            def plain_result(self, text):
                return text

        plugin = self.AihotPlugin(Context(), {})
        saved = []
        deleted = []
        plugin.put_kv_data = lambda key, value: _record(saved, value)
        plugin.delete_kv_data = lambda key: _record(deleted, key)
        await plugin._aihot_push(Event(), "on")
        result = await plugin._aihot_push(Event(), "off")
        self.assertIn("失败", result)
        self.assertTrue(plugin.config.get("push_enable"))
        self.assertEqual(saved, ["target"])
        self.assertEqual(deleted, [])

    async def test_handlers_are_registered_on_plugin_module(self) -> None:
        from astrbot.core.star.star_handler import star_handlers_registry

        module_name = self.AihotPlugin.__module__
        names = {
            handler.handler_name
            for handler in star_handlers_registry.get_handlers_by_module_name(
                module_name
            )
        }
        self.assertTrue({"_aihot_group", "_aihot_bare", "_aihot_push"} <= names)


async def _return_none():
    return None


async def _record(collection, value):
    collection.append(value)


@unittest.skipUnless(ASTRBOT_AVAILABLE, "AstrBot is supplied by the host process")
class ResetMonitorBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import copy
        import logging
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from astrbot_plugin_aihot.reset_monitor import ResetMonitor

        self.ResetMonitor = ResetMonitor
        self.copy = copy.deepcopy
        self.payload = {
            "schemaVersion": 1,
            "checkedAt": None,
            "events": [self.event("old")],
        }
        self.stored = {}
        self.client = SimpleNamespace(
            get_codex_resets=AsyncMock(side_effect=lambda: self.copy(self.payload))
        )
        self.send = AsyncMock(return_value=True)
        self.logger = logging.getLogger("test.reset_monitor")
        self.monitors = []
        self.monitor = self.make_monitor()

    @staticmethod
    def event(event_id, **kwargs):
        return {
            "id": event_id,
            "type": "direct_reset",
            "status": "announced",
            "posts": [],
            **kwargs,
        }

    def make_monitor(self):
        async def load(key, default):
            return self.copy(self.stored.get(key, default))

        async def save(key, value):
            self.stored[key] = self.copy(value)

        async def delete(key):
            self.stored.pop(key, None)

        monitor = self.ResetMonitor(
            self.client,
            load_state=load,
            save_state=save,
            delete_state=delete,
            send=self.send,
            logger=self.logger,
        )
        self.monitors.append(monitor)
        return monitor

    async def asyncTearDown(self):
        for monitor in self.monitors:
            await monitor.close()

    async def test_baseline_scan_timestamp_and_bookkeeping_edits_are_silent(self):
        await self.monitor.enable("session")
        await self.monitor.poll()
        self.payload["checkedAt"] = "2026-09-14T00:00:00+08:00"
        self.payload["events"][0]["updatedAt"] = "2026-09-14T00:00:00+08:00"
        await self.monitor.poll()
        self.send.assert_not_awaited()
        self.assertNotIn("posts", str(self.stored))

    async def test_new_event_confirmation_and_source_correction_notify_once(self):
        await self.monitor.enable("session")
        self.payload["events"].append(self.event("new"))
        await self.monitor.poll()
        self.payload["events"][1]["status"] = "confirmed"
        await self.monitor.poll()
        self.payload["events"][1]["posts"] = [{"text": "Corrected source"}]
        await self.monitor.poll()
        await self.monitor.poll()
        self.assertEqual(self.send.await_count, 3)
        self.assertEqual(self.send.call_args.args[0], "session")

    async def test_partial_delivery_failure_retries_only_unacknowledged_event(self):
        await self.monitor.enable("session")
        self.payload["events"].extend(
            [self.event("one", title="one"), self.event("two", title="two")]
        )
        self.send.side_effect = [True, RuntimeError("delivery failed")]
        with self.assertRaises(RuntimeError):
            await self.monitor.poll()
        self.send.reset_mock(side_effect=True)
        self.send.return_value = True
        await self.monitor.poll()
        self.send.assert_awaited_once()
        self.assertIn("two", self.send.call_args.args[1])
        self.assertNotIn("one", self.send.call_args.args[1])

    async def test_no_matching_platform_does_not_acknowledge(self):
        from astrbot_plugin_aihot.client import AihotError

        await self.monitor.enable("session")
        self.payload["events"].append(self.event("new"))
        self.send.return_value = False
        with self.assertRaises(AihotError):
            await self.monitor.poll()
        self.assertNotIn("new", self.monitor.state["fingerprints"])
        self.send.return_value = True
        await self.monitor.poll()
        self.assertIn("new", self.monitor.state["fingerprints"])

    async def test_restore_preserves_baseline_and_reports_changes_while_stopped(self):
        await self.monitor.enable("session")
        await self.monitor.close()
        self.payload["events"][0]["status"] = "confirmed"
        restored = self.make_monitor()
        await restored.restore()
        await restored.poll()
        await restored.poll()
        self.send.assert_awaited_once()

    async def test_withdrawal_replaces_snapshot_without_false_confirmation(self):
        await self.monitor.enable("session")
        self.payload["events"] = []
        await self.monitor.poll()
        self.assertEqual(self.monitor.state["fingerprints"], {})
        self.send.assert_not_awaited()

    async def test_repeated_enable_keeps_pending_changes_and_target_switch_seeds_baseline(
        self,
    ):
        await self.monitor.enable("first")
        self.payload["events"].append(self.event("new"))
        await self.monitor.enable("first")
        await self.monitor.poll()
        self.send.assert_awaited_once()
        await self.monitor.enable("second")
        await self.monitor.poll()
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.monitor.state["target"], "second")

    async def test_failed_enable_preserves_previous_subscription(self):
        await self.monitor.enable("first")
        self.client.get_codex_resets.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            await self.monitor.enable("second")
        self.assertEqual(self.monitor.state["target"], "first")

    async def test_disable_deletes_subscription_and_stops_requests(self):
        await self.monitor.enable("session")
        await self.monitor.disable()
        self.client.get_codex_resets.reset_mock()
        await self.monitor.poll()
        self.assertIsNone(self.monitor.state)
        self.assertEqual(self.stored, {})
        self.client.get_codex_resets.assert_not_awaited()
        restored = self.make_monitor()
        await restored.restore()
        self.assertIsNone(restored._task)

    async def test_concurrent_polls_do_not_duplicate_and_close_cancels_loop(self):
        import asyncio

        await self.monitor.enable("session")
        task = self.monitor._task
        self.payload["events"].append(self.event("new"))
        await asyncio.gather(self.monitor.poll(), self.monitor.poll())
        self.send.assert_awaited_once()
        await self.monitor.close()
        self.assertTrue(task.cancelled())

    async def test_latest_reset_and_admin_command_registration(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from astrbot.core.star.star_handler import star_handlers_registry

        from astrbot_plugin_aihot.main import AihotPlugin, _help_text

        plugin = AihotPlugin(SimpleNamespace(), {})
        plugin._client.get_codex_resets = AsyncMock(return_value=self.payload)
        event = SimpleNamespace(plain_result=lambda text: text)
        try:
            self.assertIn("Codex 最新重置", await plugin._aihot_reset(event))
            self.assertIn("/aihot reset", _help_text())
            self.assertNotIn("/aihot resets", _help_text())
            self.assertIn("/aihot resetwatch", _help_text())
            handlers = star_handlers_registry.get_handlers_by_module_name(
                AihotPlugin.__module__
            )
            names = {h.handler_name for h in handlers}
            self.assertIn("_aihot_reset", names)
            self.assertNotIn("_reset", names)
            self.assertNotIn("_aihot_resets", names)
            watch = next(h for h in handlers if h.handler_name == "_aihot_resetwatch")
            from astrbot.api.event.filter import PermissionType, PermissionTypeFilter

            self.assertTrue(
                any(
                    isinstance(f, PermissionTypeFilter)
                    and f.permission_type == PermissionType.ADMIN
                    for f in watch.event_filters
                )
            )
        finally:
            await plugin._client.close()


if __name__ == "__main__":
    unittest.main()
