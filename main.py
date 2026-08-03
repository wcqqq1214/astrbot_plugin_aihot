from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# AI HOT 数据源：https://aihot.virxact.com/
# - REST API v1（匿名只读）：https://aihot.virxact.com/api/v1/...
# - OpenAPI 规范：https://aihot.virxact.com/openapi-v1.json
# - 使用条款：https://aihot.virxact.com/terms（公开使用需标注「数据来源：AI HOT」并链接本站）

AIHOT_SITE = "https://aihot.virxact.com/"


@register("astrbot_plugin_aihot", "wcqqq1214", "聚合 AI HOT 的 AI 行业动态、热点榜与日报", "0.1.0")
class AihotPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    # 占位指令：AI HOT 数据接口的功能将在后续版本实现。
    # 发送 `/aihot hello` 触发。
    @filter.command("aihot")
    async def aihot(self, event: AstrMessageEvent):
        """AI HOT 插件占位指令，后续将接入实时动态、热点榜与日报数据。"""
        user_name = event.get_sender_name()
        yield event.plain_result(
            f"Hello, {user_name}! AI HOT 插件已加载。\n"
            f"数据来源：AI HOT（{AIHOT_SITE}）"
        )

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
