# daily_crawler 设计审查

## 当前状态

`.github/workflows/daily_crawler.yml` 目前是未跟踪文件，GitHub 远端 `main` 不包含任何 workflow，因此线上 V1 没有正在执行的每日自动更新任务。

## 阻塞问题

1. 工作流运行 `python -m crawler.run_daily --min-records 1`，只覆盖旧 `JiangsuLicenseCrawler` 链路。
2. 未执行建设工程规划、建设用地规划、建设工程施工三个独立采集入口。
3. 未执行企业主体分类、项目生命周期、必要 AI 分析和三类 Cloud JSON 导出。
4. 执行 `git add database/enterprise.db`，但 `.gitignore` 明确忽略 `database/*.db`；数据库也不应进入 Git。
5. 提交目标是旧 `data/ai`、`data/opportunities`、`data/licenses` 时间戳文件，而不是 V2 正式 `data/cloud` 集合。
6. 没有自动测试步骤，无法阻止错误数据发布。
7. Python Playwright 包安装后没有安装 Chromium；GitHub Ubuntu 不能依赖本机 Edge 回退。
8. 数据源异常状态没有统一写入 Cloud 状态文件，公网无法区分 `NO_DATA`、`NOT_COLLECTED`、`UNVERIFIED` 和 `SOURCE_ERROR`。
9. 失败时缺少“保留上次成功 Cloud JSON”的发布级原子保护。
10. 当前工作流拥有 `contents: write`，但没有对变更范围进行严格校验。

## 唯一数据规则

- 本地开发：SQLite 为工作库，Cloud JSON 为可发布快照。
- Streamlit Cloud：只读取 Git 中已提交的正式 Cloud JSON。
- GitHub：不提交 SQLite，只提交 `data/cloud/*.json` 和必要统计/状态报告。
- 旧 `data/ai`、Excel 和测试数据不得被公网主页面自动发现为正式数据。

## V2 统一任务设计

计划新增 `pipeline/run_pipeline.py`，执行顺序固定为：

1. 读取启用地区与数据源能力。
2. 检查地区+许可证类型缓存 TTL。
3. 分别采集三类许可证。
4. 验证来源、地区、分页完整性与最低健康基线。
5. 去重并写本地 SQLite。
6. 关联 `project_master` 生命周期。
7. 更新 `enterprise_master` 分类。
8. 筛选 `marketing_eligible=true` 且近期的记录。
9. 仅对必要记录调用 AI，并复用输入哈希缓存。
10. 导出到临时目录并校验 Cloud JSON schema。
11. 运行自动测试。
12. 全部通过后原子替换正式 Cloud JSON。
13. 生成 pipeline 运行报告和地区数据源状态。

## GitHub Actions 目标行为

- 定时和手动触发统一 pipeline。
- 安装明确版本依赖；如需要浏览器回退，显式安装 Playwright Chromium 及系统依赖。
- 任一地区/来源失败时不清空旧数据。
- 只暂存允许列表：`data/cloud/*.json` 与必要报告。
- 提交前运行秘密、本机路径和大文件检查。
- 没有正式数据变更时不创建 commit。
- 保留 `last_success_at`，同时记录本次 `SOURCE_ERROR`。

该重写属于 Phase 8。本 Phase 0 只完成审查和接口设计，不修改或提交现有 workflow。
