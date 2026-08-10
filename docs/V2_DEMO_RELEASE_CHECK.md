# V2 Demo Release 检查报告

检查日期：2026-08-10  
发布目标：GitHub 展示版本  
分支：`main`  
检查起点 Commit：`7b61da7a14d04c225f64cf62cfadedf113f57a7d`

## 1. 发布结论

V2 Demo Release 整理已完成，当前项目可以正常启动。

- 未新增业务功能；
- 未修改数据库逻辑；
- 正式 Demo 数据库保留 236 条许可证记录；
- 海门历史记录仍为 225 条；
- 删除阶段备份数据库、缓存、日志和调试产物；
- README 和 `.gitignore` 已按 GitHub 展示要求更新；
- 完整自动化测试 190 项通过；
- Streamlit 健康接口和首页实际返回 HTTP 200；
- 未执行 Git commit 或 Git push。

当前工作区包含此前 V2 各阶段尚未提交的变更，因此“可以展示”不等于“已经形成 GitHub Release”。发布前仍需人工核对变更范围并创建一次明确的 Release commit。

## 2. 目录结构检查

保留的核心结构：

```text
project-radar/
├─ .github/              # GitHub Actions
├─ app/                  # Streamlit 数据服务和业务规则
├─ config/               # 区域与来源配置
├─ crawler/              # 采集、导入和导出命令
├─ data/                 # Demo JSON、来源样本和公开导出
├─ data_source/          # 来源适配、校验和分类
├─ database/             # 正式 Demo SQLite 与迁移脚本
├─ docs/                 # 阶段文档和 Release 文档
├─ outputs/              # 工商导入模板和验证工作簿
├─ samples/              # 采集示例
├─ tests/                # 自动化测试及固定夹具
├─ tools/                # 辅助脚本
├─ dashboard.py          # Streamlit 入口
├─ README.md             # GitHub 项目首页
└─ requirements.txt      # 运行依赖
```

`PROJECT_HANDOFF.md` 在当前仓库及当前工作区中均不存在。本次检查以现有源码、Git 状态、数据库和 `docs/` 阶段报告为准。

## 3. 清理结果

首次清理共移除 228 个文件，约 13.95 MB；测试和启动验证后又清理了 11 个新生成的 `__pycache__` 目录。

已删除：

- 所有 `__pycache__`、`.pyc`、`.pyo`；
- 根目录 `tmp/`；
- `.playwright-cli/` 浏览器运行记录；
- `debug/` 调试页面、截图和临时响应；
- `output/` 旧 Playwright 页面截图；
- `logs/` 中的运行日志，保留 `logs/.gitkeep`；
- 根目录 Streamlit 临时日志；
- `data/excel/` 旧运行导出；
- `data/state/` 本地采集缓存；
- `outputs/**/*.inspect.ndjson` 检查器中间文件；
- `data/cloud/planning_construction_permits_pre_phase3_14.json`；
- 8 个阶段备份数据库及其 SQLite sidecar。

已删除的备份数据库：

```text
database/enterprise.phase1_2_backup_20260809_2228.db
database/enterprise.phase2_1_backup_20260810_144740.db
database/enterprise.phase2_2_backup_20260810_150233.db
database/backups/enterprise_before_phase3_5_20260810.db
database/backups/enterprise_before_phase3_8_20260810.db
database/backups/enterprise_pre_phase3_11_20260810_183619.db
database/backups/enterprise_pre_phase3_12_20260810_185247.db
database/backups/enterprise_pre_phase3_14_20260810.db
```

这些备份原本未被 Git 跟踪，删除后无法从当前仓库恢复；正式库 `database/enterprise.db` 未删除、未替换。

清理时发现3个 JSONP 文件实际是解析器回归测试夹具，而非普通调试产物。它们已从 V2 工作副本恢复到 `tests/fixtures/`，测试仅改为读取明确的夹具目录，未修改解析器和数据库逻辑。

最终复扫结果：

- 备份数据库：0；
- `__pycache__`：0；
- `.pyc` / `.pyo`：0；
- Release 临时测试目录：不存在。

## 4. README 与截图位置

`README.md` 已重写，包含：

- 项目介绍；
- 功能说明；
- 安装、启动和测试方式；
- 技术架构和数据流；
- 目录结构；
- 截图位置；
- 数据安全说明；
- 未来规划；
- 当前发布状态。

截图统一放置在：

```text
docs/screenshots/
```

已增加 `docs/screenshots/README.md` 说明文件。旧截图仍显示205条海门规划许可证，与当前236条总数据口径不同，因此没有作为 Release 截图保留。

## 5. `.gitignore` 检查

新规则排除：

- Python 缓存和测试工具缓存；
- 虚拟环境；
- 临时文件；
- 日志和浏览器调试输出；
- 采集状态与旧 Excel 运行输出；
- SQLite sidecar；
- 阶段备份数据库；
- 本地 `.env` 和 Streamlit secrets。

特别处理：

```gitignore
!database/enterprise.db
```

正式 Demo 数据库不再被忽略，当前 Git 状态会显示：

```text
?? database/enterprise.db
```

这保证236条 Demo 数据可以在人工确认后加入 Git；备份数据库仍会被排除。

## 6. 数据库检查

正式数据库：`database/enterprise.db`

| 检查项 | 结果 |
|---|---:|
| `PRAGMA integrity_check` | `ok` |
| `construction_permits` | 236 |
| 海门 `region_key=320684` | 225 |
| `source_region/source_time` 完整 | 236 |
| `schema_meta.schema_version` | 13 |

SHA-256：

```text
7841535477A77622AC619082EA5E33843577CABB890E2A5BD4674D491C548FEF
```

该校验值与 Phase 3.14 完成时一致，说明 Release 整理未改变正式数据库。

## 7. 测试与启动验证

完整测试命令：

```powershell
python -m unittest discover -s tests
```

结果：

```text
Ran 190 tests in 7.783s
OK
```

测试期间只有 Streamlit `use_container_width` 弃用提示和 bare mode 上下文提示，不影响测试结果。

启动验证使用项目虚拟环境，在隔离端口 `127.0.0.1:8514` 临时启动：

| 请求 | 结果 |
|---|---:|
| `/_stcore/health` | HTTP 200 |
| `/` | HTTP 200 |

验证完成后 Streamlit 进程已经停止，启动日志已经删除。

## 8. Git 发布状态

- Branch：`main`
- 起点 Commit：`7b61da7a14d04c225f64cf62cfadedf113f57a7d`
- 工作区：非 clean，包含 V2 各阶段累计变更；
- 正式 Demo 数据库：已解除忽略，但仍是未跟踪文件；
- Git push：未执行。

建议发布前人工执行：

1. 阅读 `git status` 和 `git diff`；
2. 确认 `database/enterprise.db` 的236条记录允许公开展示；
3. 补充当前版本页面截图；
4. 创建独立的 Demo Release commit；
5. 再推送至 GitHub。

本报告没有代替第2步的数据公开授权确认。
