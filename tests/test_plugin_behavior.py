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


if __name__ == "__main__":
    unittest.main()
