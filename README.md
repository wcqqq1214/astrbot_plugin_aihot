# astrbot_plugin_aihot

聚合 [AI HOT](https://aihot.virxact.com/) 的 AI 行业动态、热点榜与日报，供 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 使用。

数据通过 AI HOT 的匿名只读 REST API v1 获取，无需 API Key。接口文档见 <https://aihot.virxact.com/agent>，OpenAPI 规范见 <https://aihot.virxact.com/openapi-v1.json>。

## 功能

- **最新动态**：拉取精选 / 7 天公开池的 AI 行业动态（`GET /api/v1/items`），支持分类过滤与关键词搜索
- **热点榜**：当前 AI 圈热点 TOP 10（`GET /api/v1/hot-topics`）
- **AI 日报**：最新一期或按天获取日报（`GET /api/v1/dailies/latest`、`/api/v1/dailies/{date}`）
- **日报索引**：历史日报日期索引（`GET /api/v1/dailies`）
- **事件详情**：单条热点事件的时间线与 AI 综述（`GET /api/v1/stories/{publicId}`）
- **每日推送**：定时将日报 + 热点榜推送到指定会话

## 指令

| 指令 | 说明 |
| --- | --- |
| `/aihot` | 查看指令树 |
| `/aihot help` | 指令帮助 |
| `/aihot items [数量]` | 最新动态（默认 10 条，1-100） |
| `/aihot hot` | 当前热点榜 |
| `/aihot daily [YYYY-MM-DD]` | 最新一期日报，或指定日期日报 |
| `/aihot dailies [数量]` | 日报索引 |
| `/aihot story <publicId>` | 事件详情 |
| `/aihot search <关键词>` | 关键词搜索（2-200 字） |
| `/aihot push on` | 开启每日推送（推送到当前会话） |
| `/aihot push off` | 关闭每日推送 |

## 安装

将本仓库克隆到 AstrBot 的 `data/plugins/` 目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/wcqqq1214/astrbot_plugin_aihot
```

依赖 `httpx`、`apscheduler` 已写入 `requirements.txt`，AstrBot 会自动安装。然后在 AstrBot WebUI 插件管理中启用。

## 配置

在 AstrBot WebUI 的插件配置中可调整：

- `items_show_limit`：单条回复最多展示的动态条数（默认 10）
- `push_enable`：启用每日定时推送（也可用 `/aihot push on` 开启）
- `push_time`：每日推送时间 `HH:MM`（默认 `08:00`）
- `push_timezone`：推送时区 IANA 名称（默认 `Asia/Shanghai`）
- `push_include_hot`：推送时是否附带热点榜（默认开启）

## 数据来源与合规

- 接口文档：<https://aihot.virxact.com/agent>
- OpenAPI 规范：<https://aihot.virxact.com/openapi-v1.json>
- 公开接入条款：<https://aihot.virxact.com/terms>

本插件遵循接入规范实现：

- 匿名只读，无需 API Key；
- 按 `s-maxage` 频率合同轮询（items 60s、hot-topics 300s），并通过 ETag / `If-None-Match` 条件请求复用缓存（`304` 表示无更新）；
- 收到 `429` 时严格遵守 `Retry-After`，`5xx` 时指数退避；
- 错误响应为 Problem JSON，含稳定 `code` 与 `requestId`。

根据[公开接入条款](https://aihot.virxact.com/terms)，本插件公开使用需在可发现位置标注：

> 数据来源：AI HOT（<https://aihot.virxact.com/>）

所有动态/日报回复末尾均附有此标注。此外，按条款"镜像或对外发布须保留 AI HOT 署名和原文入口"，本插件每条动态/日报/事件均同时展示 **AI HOT 站内阅读链接**与**第三方原文链接**（`links.original`），并保留接口返回的 `attribution` 来源标识。原文版权归各来源所有；AI HOT 提供的摘要与翻译由 AI 生成，重要数字、政策和原话请以原文为准。

## 开发

- 网络请求使用 `httpx`，不使用 `requests`；
- 运行 `ruff format .` 与 `ruff check .` 后再提交；
- 持久化数据（推送目标等）存储在 AstrBot 的 KV 存储中，位于 `data` 目录。

## 许可证

[AGPL-3.0](LICENSE)

**免责声明**：本插件与 AI HOT 无附属关系，使用其数据请遵守其[公开接入条款](https://aihot.virxact.com/terms)。
