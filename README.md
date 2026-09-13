<h1 align="center">astrbot_plugin_aihot</h1>

<p align="center">
  <a href="https://github.com/wcqqq1214/astrbot_plugin_aihot/releases/tag/1.0.3"><img src="https://img.shields.io/badge/version-1.0.3-4b8bbe?style=flat-square" alt="Version 1.0.3"></a>
  <a href="https://github.com/AstrBotDevs/AstrBot"><img src="https://img.shields.io/badge/AstrBot-%E2%89%A54.26.8-4b8bbe?style=flat-square" alt="AstrBot ≥ 4.26.8"></a>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python ≥ 3.12">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-blue?style=flat-square" alt="License: AGPL-3.0-or-later"></a>
</p>

一个面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 AI HOT 客户端插件：通过 AI HOT 的匿名、只读 REST API v1 展示 AI 行业动态、热点榜、日报和事件详情。

## 功能

- 精选动态：`GET /api/v1/items`，支持命令数量限制
- 关键词搜索：`GET /api/v1/items?q=...`
- 当前热点榜：`GET /api/v1/hot-topics`
- 最新/指定日期日报：`GET /api/v1/dailies/latest`、`GET /api/v1/dailies/{date}`
- 日报索引：`GET /api/v1/dailies?limit=...`
- 事件详情：`GET /api/v1/stories/{publicId}`，按 API 返回顺序展示最近时间线
- 最新 Codex 重置：`GET /api/v1/codex-resets`，区分全员重置、发重置卡、预告与确认，附北京时间、中文译文和原帖
- 实验性重置监控：每 5 分钟检查新增或实质更新，管理员在目标会话开启
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
| `/aihot reset` | 最新一次 Codex 重置/发卡事件及当前状态 |
| `/aihot resetwatch on` | 管理员开启本会话重置监控，首次不推送历史 |
| `/aihot resetwatch off` | 管理员关闭重置监控并清除订阅与去重状态 |
| `/aihot resetwatch status` | 管理员查看重置监控状态 |
| `/aihot push on` | 管理员开启实验性每日推送 |
| `/aihot push off` | 管理员关闭实验性每日推送 |

推送首次必须从目标会话执行 `push on`。插件只保存一个目标会话，后一次 `push on` 会覆盖前一次；`push_enable=true` 但没有目标时会告警并自动回滚为 `false`。推送依赖适配器支持主动发送，机器人重启或适配器不支持主动发送时可能无法投递，其他查询指令不受影响。

## Codex 重置监控

输入 `/aihot reset`只查看最新一条重置/发卡事件，包括预告或确认状态、北京时间和原帖。按已核实发生日期排序；未知时依次采用确认帖时间、预告创建时间，不使用记录编辑时间或未来预计时间，避免旧记录修正挤到最前面。不再提供历史条数查询。AstrBot 已将 `/reset` 用作开启新会话，本插件保留 `aihot` 前缀避免命令冲突。命令是否需要 `/` 等唤醒前缀取决于 AstrBot 配置。

在目标会话执行 `/aihot resetwatch on`。首次开启先读取完整快照建立基线，不推送已有历史；此后每 5 分钟检查一次，并遵守服务端缓存与重试信号。重复对同一会话开启不会重建基线；切换目标会重新建立基线。监控与每日推送独立，各自只保存一个目标会话。

新增事件、预告转为确认、来源或内容修正会触发通知；仅核验时间或更新时间变化不通知。接口撤回的记录会从去重状态移除，不当成新重置推送。重启恢复订阅和去重状态，在下一轮检查中处理停机期间的变化。发送失败保留未确认状态以便重试；在发送成功与本地保存之间异常退出时，可能重复通知。

输出区分原始预告、已核实发生日期和确认帖时间；未知时间保留为未知，确认帖时间不代表精确执行时间。`上游最近核验` 是服务端最近成功核验时间，可能滞后于当前时间。记录反映公开事件，不代表个人账户额度或实际到账情况。

主动通知需要适配器支持 AstrBot 的 `send_message`。**QQ 官方 API 适配器不支持此主动发送接口**；该平台可使用 `/aihot reset` 查询。功能默认关闭，安装或重载插件不会自动为未订阅的会话开启通知。

## 输出示例

```text
AI HOT 动态
1. 新模型发布……
   摘要……
   - 来源：Example
   - 详情: https://aihot.news/...

数据来源：AI HOT（https://aihot.news/）
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

## 数据流与隐私

- 查询词 `q` 会发送到 `https://aihot.news/api/v1/items`；仅发送本次命令所需参数。
- `push on` 保存当前会话的 `unified_msg_origin`，用于之后主动投递；只保留一个目标，`push off` 会删除它。
- `resetwatch on` 通过 AstrBot 插件 KV 存储在 `data` 下保存目标会话和当前快照的事件 ID/内容哈希；不持久化原帖或完整 API 响应。`resetwatch off` 删除这些状态。
- HTTP 响应和 ETag 只保存在插件进程内的有界内存缓存；不会上传聊天历史。
- 插件不要求、不保存 AI HOT API Key，也不会把聊天内容作为搜索词以外的数据上传。
- 日志可能记录请求错误和推送目标，部署者应按自己的日志保留策略管理日志。

## AI HOT 条款提示

AI HOT 更新日志显示，《AI HOT 公开使用规则 1.0》将于 **2026-08-10** 生效：个人非商业使用、公益非商业项目和组织内部使用仍可匿名免费接入；收费产品、客户服务、公开镜像、对外代理/转售、批量公开再分发以及向外部提供的模型应用等用途，需要事先取得书面授权。仅因 API 无需 Key、接口公开、未收费或已标注来源，并不自动获得这些用途的授权。

本仓库只提供 AstrBot 客户端代码，不包含 AI HOT 数据副本，也不代表任何具体部署场景已经获准。部署者应自行确认机器人所在会话、产品或服务符合最新规则，不要将插件部署为对外数据代理或镜像。当前实现仅保留有界内存缓存，回复保留 AI HOT 来源链接，并按 API 返回的缓存、条件请求和重试信号访问服务；原始来源的版权和事实准确性仍由相应来源负责。

本项目已经使用新版 `/api/v1` 接口，不使用即将停用的旧 `/api/public` 接口；根据更新日志，旧接口计划于 **2026-12-31** 停止服务，因此本次规则/API 更新不需要迁移代码。

条款与接口文档：

- <https://aihot.news/changelog>
- <https://aihot.news/terms>
- <https://aihot.news/agent>
- <https://aihot.news/openapi-v1.json>

## 许可证与声明

本项目代码采用 SPDX `AGPL-3.0-or-later`，完整文本见 [LICENSE](LICENSE)，版权声明见 [NOTICE](NOTICE)。本插件与 AI HOT 无附属关系；使用数据时请遵守 AI HOT 最新公开条款及原始来源要求。未使用未经授权的 AI HOT 品牌图片，logo 仅可由部署者按其许可自行添加。
