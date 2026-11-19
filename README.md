# 彩票预测实验室 · Render 部署版

## 当前部署内容

这是当前界面的静态预览部署版，包含：

- 预测中心
  - AI 预测模型：3组结果
  - Feel the Chee：2组结果
- 管理员后台
  - 历史开奖记录
  - 10条/页
  - 搜索、编辑、删除
  - 等待自动同步 / 已同步 / 同步失败
- 模型学习
  - 模型权重
  - 学习路径日志

## Render 部署

1. 登录 Render。
2. 选择 `New` > `Blueprint`。
3. 连接此 GitHub 仓库。
4. Render 会读取根目录中的 `render.yaml`。
5. 确认创建服务。

该版本是静态前端演示。自动抓取、数据库持久化、定时同步和真实模型学习需要后端服务版本。

## Simulation dashboard and daily run

- Dashboard: [Simulation Dashboard](./simulation.html)
- Schedule: daily at 18:00 Asia/Shanghai (10:00 UTC)
- Workload: 100 independent full-history simulations per batch
- Results: the latest 30 batch summaries are published to the `simulation-data` branch and read by the static dashboard
- Compute: GitHub Actions hosted runner; no additional Render service or database is required

The daily workflow runs contract tests before simulations, validates every chronological replay, stores a representative trace and compact run summaries as a 30-day GitHub Actions artifact, and publishes a compact dashboard feed. Simulation runs do not write to live prediction locks or live model state.
