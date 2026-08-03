# astrbot_plugin_aihot

聚合 [AI HOT](https://aihot.virxact.com/) 的 AI 行业动态、热点榜与日报，供 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 使用。

## 功能

> 开发中，初始骨架已就绪。后续将接入：

- **每日动态**：拉取精选/7 天公开池的 AI 行业动态（`GET /api/v1/items`）
- **热点榜**：当前 AI 圈热点话题（`GET /api/v1/hot-topics`）
- **AI 日报**：按天获取/最新一期日报（`GET /api/v1/dailies`）
- **事件时间线**：单条事件的时间线与 AI 综述（`GET /api/v1/stories/{publicId}`）
- 定时推送 + 关键词订阅

## 数据来源与合规

- 接口文档：<https://aihot.virxact.com/agent>
- OpenAPI 规范：<https://aihot.virxact.com/openapi-v1.json>
- 公开接入条款：<https://aihot.virxact.com/terms>

根据 [公开接入条款](https://aihot.virxact.com/terms)，本插件公开使用需在可发现位置标注：

> 数据来源：AI HOT（<https://aihot.virxact.com/>）

并遵守频率合同（按 `s-maxage`/ETag 条件轮询，429 按 `Retry-After` 退避），不批量公开再分发。

## 安装

将本仓库克隆到 AstrBot 的 `data/plugins/` 目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/wcqqq1214/astrbot_plugin_aihot
```

然后在 AstrBot WebUI 插件管理中启用，或在聊天中发送 `/aihot hello` 验证加载。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/aihot hello` | 占位指令，验证插件已加载 |

## 许可证

[AGPL-3.0](LICENSE)

**免责声明**：原文版权归各来源所有；AI HOT 提供的摘要与翻译由 AI 生成，重要数字、政策和原话请以原文为准。本插件与 AI HOT 无附属关系，使用其数据请遵守其[公开接入条款](https://aihot.virxact.com/terms)。
