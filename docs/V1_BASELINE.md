# 海门企业雷达 V1 基线

## 基线用途

本文件冻结 V2 改造开始前的 V1 状态。后续开发必须保留现有公网地址、海门默认视图、三类许可证展示和公开数据读取能力。除非另有迁移与回滚方案，不得用空数据或未验证数据覆盖本基线。

## 确认信息

- 最后确认日期：2026-08-09（Asia/Shanghai）
- Git 分支：`main`
- 本地、`origin/main` 与 GitHub 远端提交：`7b61da7a14d04c225f64cf62cfadedf113f57a7d`
- 提交时间：2026-07-23 20:07:06 +0800
- 提交说明：`修复Streamlit云端许可证模块导入`
- GitHub 仓库：<https://github.com/yingw4086-code/haimen-enterprise-radar>
- 线上 Streamlit：<https://haimen-enterprise-radar-dva3ajtuc3appmgy8lgmmgf.streamlit.app/>
- 线上标题：`海门企业雷达 · Streamlit`

## 三类许可证数据

| 许可证类型 | Cloud JSON | 记录数 | 最新业务日期 | 最后采集确认时间 |
|---|---|---:|---|---|
| 建设工程规划许可证 | `data/cloud/planning_construction_permits.json` | 205 | 2026-07-20 | 2026-07-23 13:28:59 |
| 建设用地规划许可证 | `data/cloud/planning_land_permits.json` | 19 | 2026-07-14 | 2026-07-23 18:31:21 |
| 建设工程施工许可证 | `data/cloud/construction_start_permits.json` | 1 | 2026-04-08 | 2026-07-23 18:33:30 |

线上浏览器核验与本地 Cloud JSON 数量一致。2026-08-09 检查时，线上数据自 2026-07-23 后没有更新。

## Cloud JSON 基线

V1 公网正式页面使用以下三个已提交文件：

- `data/cloud/planning_construction_permits.json`
- `data/cloud/planning_land_permits.json`
- `data/cloud/construction_start_permits.json`

`data/ai/financing_analysis_*.json` 属于旧版项目数据兼容输入，不得作为 V2 三类许可证与地区统计的正式数据源。线上当前仅能看到已提交的 `financing_analysis_2026-07-14_194011.json`；本地未跟踪的 2026-07-21 AI JSON 不代表线上状态。

## SQLite 基线

- 路径：`database/enterprise.db`
- Git 状态：被 `.gitignore` 忽略，不进入 Git
- Schema 版本：4
- 2026-08-09 本地记录：许可证 225 条、许可证 AI 分析 10 条、统一机会表 0 条

| 表 | 用途 | 关键关系 |
|---|---|---|
| `construction_permits` | 三类许可证与主体分类字段 | 许可证编号、来源链接或项目+类型+日期去重 |
| `permit_ai_analyses` | 必要许可证的 AI 结果缓存 | `permit_id` 一对一关联许可证 |
| `enterprise_opportunities` | 旧多源统一机会记录 | 当前本地正式库为 0 条 |
| `crawler_runs` | 采集任务运行日志 | 保存状态、数量与错误元数据 |
| `schema_meta` | Schema 版本 | 当前 `schema_version=4` |

V1 本地读取规则：存在有效 SQLite 记录时优先 SQLite，否则回退到 Cloud JSON。V2 必须把运行环境明确化：本地允许 SQLite 优先；Streamlit Cloud 只读 Git 中提交的 `data/cloud` 正式文件。

## Dashboard 页面清单

1. 首页 Dashboard
2. 海门建设工程规划许可证
3. 海门建设用地规划许可证
4. 海门建设工程施工许可证
5. 今日营销任务
6. 产业地图
7. 企业机会列表
8. 企业详情
9. 风险提示
10. 政府公益项目
11. 旧版项目数据

V2 初始默认地区必须继续是“江苏省 / 南通市 / 海门区”，保证原用户进入原网址时仍能看到当前海门功能。

## V1 已具备能力

- Streamlit 公网应用及本地运行脚本
- 三类许可证独立展示
- SQLite 表结构、WAL、去重和增量更新时间
- Cloud JSON 只读回退
- 海门归属、分页完整性和异常数据阻断
- 项目主体性质分类框架及人工覆盖入口
- 许可证 AI 分析缓存和失败保护
- Excel、JSON 导出与旧版多源采集兼容代码
- 82 项自动测试（Phase 0 开始前为 81 通过、1 个动态时间断言失败）

## 已知问题

1. GitHub 远端没有已提交的每日工作流，数据停留在 2026-07-23。
2. 当前未跟踪的重要采集、入库、运行脚本、测试和报告尚未纳入版本控制。
3. 草案工作流试图提交被忽略的 SQLite，并且没有串联三类许可证完整链路。
4. 工程规划许可证主体分类中：待核验 191、国有商业企业 11、政府机关 3、民营企业 0；人工覆盖表暂无记录。
5. 施工许可证只有 1 条，数据源覆盖明显不足。
6. 政务站点存在 403、超时、分页接口异常和浏览器依赖风险。
7. `dashboard.py` 约 946 行，继续堆叠会增加维护成本。
8. Streamlit `use_container_width` 已产生弃用警告。
9. README 存在过期描述与乱码。
10. 当前没有 `PROJECT_HANDOFF.md`。

## V1 保护规则

- 不重建仓库、不更换原 Streamlit 应用、不改变原公网地址。
- 不提交 `.env`、API Key、Cookie、SQLite、日志、debug、浏览器缓存或本机路径。
- 数据源异常时保留上次成功 Cloud JSON，不得写空覆盖。
- 未验证地区必须标记 `UNVERIFIED` 或 `NOT_COLLECTED`，不得伪造为 0 条。
- 政府机关、事业单位和纯财政公益项目继续与默认营销机会分离。
- 每个 Phase 完成后先运行测试；当前 Phase 未通过时不得进入下一 Phase。
