# astrbot_plugin_aihot

[![AstrBot ≥ 4.26.8](https://img.shields.io/badge/AstrBot-%E2%89%A54.26.8-4b8bbe)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE)

一个面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 AI HOT 客户端插件：通过 AI HOT 的匿名、只读 REST API v1 展示 AI 行业动态、热点榜、日报和事件详情。

## 功能

- 精选动态：`GET /api/v1/items`，支持命令数量限制
- 关键词搜索：`GET /api/v1/items?q=...`
- 当前热点榜：`GET /api/v1/hot-topics`
- 最新/指定日期日报：`GET /api/v1/dailies/latest`、`GET /api/v1/dailies/{date}`
- 日报索引：`GET /api/v1/dailies?limit=...`
- 事件详情：`GET /api/v1/stories/{publicId}`，按 API 返回顺序展示最近时间线
- 实验性每日推送：管理员在目标会话中执行 `push on` 后启用

插件界面仅承诺本 README 列出的精选动态和关键词搜索功能；其他底层参数按公开接口合同校验，但不作为额外浏览界面承诺。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/aihot` | 查看指令树 |
| `/aihot help` | 指令帮助 |
| `/aihot items [数量]` | 最新精选动态（默认 10 条，API 上限 100） |
| `/aihot hot` | 当前热点榜 |
| `/aihot daily [YYYY-MM-DD]` | 最新一期或指定日期日报 |
| `/aihot dailies [数量]` | 日报索引（1–180） |
| `/aihot story <publicId>` | 事件详情与最近时间线 |
| `/aihot search <关键词>` | 关键词搜索（2–200 字） |
| `/aihot push on` | 管理员开启实验性每日推送 |
| `/aihot push off` | 管理员关闭实验性每日推送 |

推送首次必须从目标会话执行 `push on`。插件只保存一个目标会话，后一次 `push on` 会覆盖前一次；`push_enable=true` 但没有目标时会告警并自动回滚为 `false`。推送依赖适配器支持主动发送，机器人重启或适配器不支持主动发送时可能无法投递，其他查询指令不受影响。

## 输出示例

```text
AI HOT 动态
1. 新模型发布……
   摘要……
   - 来源：Example
   - 详情: https://aihot.virxact.com/...

数据来源：AI HOT（https://aihot.virxact.com/）
```

日报、索引和时间线会尽量展示 API 返回的完整范围；达到单条消息安全上限时会明确提示省略数量。所有输出都保留产品级来源标注，链接字段按 API 实际返回展示，不假定每条记录同时提供 AI HOT 与第三方链接。

## 安装

将仓库克隆到 AstrBot 的插件目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/wcqqq1214/astrbot_plugin_aihot
```

启用插件后，AstrBot 会安装 `httpx`。插件运行时不要求 API Key，也不把 AstrBot 加入自身 runtime 依赖。

## 配置

- `items_show_limit`：动态单条回复最多展示条数（默认 10）
- `push_enable`：是否启用每日推送（默认 `false`；必须同时存在目标会话）
- `push_time`：每日推送时间 `HH:MM`（默认 `08:00`）
- `push_timezone`：IANA 时区（默认 `Asia/Shanghai`）
- `push_include_hot`：推送是否附带热点榜（默认 `true`）

## 兼容矩阵

| 组件 | 支持范围 |
| --- | --- |
| AstrBot | `>=4.26.8,<5` |
| Python | `>=3.12` |
| HTTP 客户端 | `httpx>=0.27,<1` |
| 定时调度 | AstrBot `CronJobManager` 公共 API |
| 平台推送 | 取决于适配器主动发送能力；查询功能不依赖推送 |

## 数据流与隐私

- 查询词 `q` 会发送到 `https://aihot.virxact.com/api/v1/items`；仅发送本次命令所需参数。
- `push on` 保存当前会话的 `unified_msg_origin`，用于之后主动投递；只保留一个目标，`push off` 会删除它。
- HTTP 响应和 ETag 只保存在插件进程内的有界内存缓存；不会上传聊天历史。
- 插件不要求、不保存 AI HOT API Key，也不会把聊天内容作为搜索词以外的数据上传。
- 日志可能记录请求错误和推送目标，部署者应按自己的日志保留策略管理日志。

## AI HOT 条款提示

本插件按 **2026-08-01** 可见的 AI HOT 接入条款实现匿名只读客户端，并在回复中标注“数据来源：AI HOT”及站点链接。条款允许独立客户端接入并不等同于默认授权：纯镜像/换皮服务或批量公开再分发不应视为默认获准用途；请在部署前阅读最新条款并自行确认适用范围。原始来源的版权和事实准确性仍由相应来源负责。

条款与接口文档：

- <https://aihot.virxact.com/terms>
- <https://aihot.virxact.com/agent>
- <https://aihot.virxact.com/openapi-v1.json>

## 开发

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv lock --check
uv run python -m unittest discover -v
```

插件只把运行数据交给 AstrBot `data` 目录的 KV 存储；代码目录不用于持久化用户数据。

## 许可证与声明

本项目代码采用 SPDX `AGPL-3.0-or-later`，完整文本见 [LICENSE](LICENSE)，版权声明见 [NOTICE](NOTICE)。本插件与 AI HOT 无附属关系；使用数据时请遵守 AI HOT 最新公开条款及原始来源要求。未使用未经授权的 AI HOT 品牌图片，logo 仅可由部署者按其许可自行添加。
