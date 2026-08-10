# TODO

## 模型排行榜支持（待官方 API）

- [ ] 接入 AIHOT 模型排行榜（`/leaderboard`）
  - 背景：排行榜于 2026-08-10 上线，聚合多家公开评测榜单（LMSYS Arena、LiveBench、Epoch 等），给出 AIHOT 共识分，总榜前 30 名，含模型详情页 `/leaderboard/{slug}`。
  - 现状：**暂无公开 API 接口**。OpenAPI v1（`openapi-v1.json`）未收录任何排行榜端点，探测候选路径均 404；数据是服务端渲染进页面 HTML（Next.js RSC payload）。
  - 备注：`/api/v1/items?category=ai-models` 是模型相关新闻，不是榜单。
  - 待官方补充 API 后再接入；若长期无 API，可评估解析 `/leaderboard` 页面（注意页面结构变更风险）。
  - 相关：2026-08-10 aihot 更新公开使用规则，个人/公益/内部匿名免费，商业用途需授权。
