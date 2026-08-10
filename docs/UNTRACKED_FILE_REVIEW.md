# 未跟踪文件审查

## 审查结论

Phase 0 开始时共有 15 个未跟踪文件。当前没有执行 `git add`、commit 或 push。稳定代码应在完成安全检查和工作流修正后纳入 Git；生成数据应按 V2 正式数据边界分别保留、迁移或废弃。

## 建议纳入 Git

| 文件 | 结论 | 理由 / 提交前动作 |
|---|---|---|
| `crawler/run_construction_start_permit.py` | 保留并纳入 | 施工许可独立入口；测试通过 |
| `crawler/run_planning_land_permit.py` | 保留并纳入 | 用地规划许可独立入口；测试通过 |
| `data_source/construction_start_permit.py` | 保留并纳入 | 独立官方数据源适配器 |
| `data_source/official_permit_record.py` | 保留并纳入 | 三类许可证统一记录模型 |
| `data_source/planning_land_permit.py` | 保留并纳入 | 独立用地许可采集器 |
| `database/official_permits.py` | 保留并纳入 | 类型隔离的 upsert、查询和公开导出 |
| `tests/test_official_permit_modules.py` | 保留并纳入 | 覆盖类型隔离、导出与错误类型保护 |
| `run_multi_source.ps1` | 暂时保留并纳入 | 作为旧多源入口；README 必须标记兼容用途 |
| `data/licenses/.gitkeep` | 保留 | 仅维持输出目录，不包含业务数据 |
| `data/reports/ownership_classification_report.csv` | 保留为必要报告 | 公开字段，无密钥；提交前确认报告由正式 pipeline 可重复生成 |

## 修正后再纳入 Git

| 文件 | 当前问题 | 修正要求 |
|---|---|---|
| `.github/workflows/daily_crawler.yml` | 尝试提交被忽略的 SQLite；只跑旧任务；未导出三类 Cloud JSON；未跑测试 | Phase 8 重写为统一 pipeline，只提交 `data/cloud/*.json` 与必要报告 |

## 不建议直接纳入正式 V2

| 文件 | 结论 | 处理方案 |
|---|---|---|
| `data/ai/financing_analysis_2026-07-21_132634.json` | 不作为 V2 正式数据 | 旧兼容格式；本地归档或迁移到统一 Cloud schema 后删除，需另行确认 |
| `data/opportunities/enterprise_opportunities_2026-07-21_132634.json` | 不直接提交 | 单次生成快照；迁移有价值记录或本地归档 |
| `data/opportunities/multi_source_report_2026-07-21_132634.json` | 不直接作为生产数据 | 可作为历史诊断证据，本地归档；错误和本机绝对路径不应进入正式 Cloud JSON |

## 明确禁止纳入

- `.env`、真实 API Key、Cookie、Token
- `database/*.db`、`*.db-shm`、`*.db-wal`
- `debug/`、`logs/`、`.playwright-cli/`、`output/playwright/`
- 本机绝对路径、浏览器缓存、临时文件

## 当前建议保留与废弃

建议保留：三类许可证采集器、统一记录与入库模块、对应运行脚本和测试、可重复生成的主体分类报告、Cloud JSON 基线。

建议废弃或归档：散落的旧 `data/ai` 与 `data/opportunities` 时间戳快照作为 V2 正式输入的做法。任何物理删除都不属于 Phase 0，必须经用户确认。
