# 地区硬编码扫描报告

## 扫描范围与结论

- 扫描日期：2026-08-09
- 关键词：`海门`、`海门区`、`南通海门`、`320684`、`areaCode`
- 扫描范围：源代码、配置、脚本、测试和项目文档
- 排除：`.git`、`__pycache__`、`debug`、`.playwright-cli`、`output`、`logs` 与 `data` 数据快照
- 匹配文件：43 个
- 匹配行：206 行
- 生产代码与配置：25 个文件、114 行
- 测试：89 行
- 文档与 learning：3 行

原始关键词出现次数为：`海门` 177、`海门区` 59、`南通海门` 9、`320684` 32、`areaCode` 14。关键词存在包含关系，因此这些数字不能相加作为独立问题数。真正需要参数化的高风险点主要集中在 SQL 过滤、数据源请求参数、归属判断、记录写入和 Dashboard 数据选择。

本报告记录 Phase 0 扫描结果，不在本阶段批量替换。Phase 1 应先引入地区配置对象和兼容默认值，再逐个迁移。

## 生产代码与配置逐项清单

| 文件 | 行号 | 当前内容类别 | 是否需要改 | Phase 1 修改方案 |
|---|---|---|---|---|
| `app/dashboard_data.py` | 379 | 旧数据源显示名固定为海门 | 是 | 从记录或地区服务生成来源显示名 |
| `app/enterprise_map.py` | 49, 50 | 地图标题和说明固定海门 | 是 | 接受当前地区显示名；海门作为默认值 |
| `app/official_permit_data.py` | 90, 119 | SQLite/JSON 固定过滤 `district_code='320684'` | 是，高风险 | 仓储加载函数显式接收 `administrative_code` |
| `app/permit_data.py` | 355 | Cloud JSON 固定过滤 `320684` | 是，高风险 | 按所选地区过滤，禁止跨地区混入 |
| `app/permit_ownership.py` | 219, 343 | 海门地方平台识别规则 | 是 | 将地方平台关键词移入地区/企业规则配置 |
| `config/sites.json` | 3 | 站点名称固定海门 | 是 | V1 兼容配置保留；新能力转入 `source_capabilities.json` |
| `crawler/analyze_recent_permits.py` | 183 | AI 提示词固定海门区 | 是 | 提示词注入地区名称和地区代码 |
| `crawler/run_construction_start_permit.py` | 54 | CLI 描述固定海门 | 是 | CLI 接收地区键，描述动态化 |
| `crawler/run_daily.py` | 171 | 每日任务描述固定海门 | 是 | 由统一 pipeline 读取启用地区 |
| `crawler/run_license.py` | 195, 262, 268, 526, 552, 576, 659, 664, 669, 674 | 诊断、导入、帮助文本及 `areaCode=320684` 固定 | 是，高风险 | 命令参数统一传入 `RegionConfig`；诊断文本使用地区名 |
| `crawler/run_planning_land_permit.py` | 55 | CLI 描述固定海门 | 是 | 接收地区与数据源能力配置 |
| `dashboard.py` | 56, 65, 88, 94, 95, 96, 115, 121, 124, 127, 128, 130, 133, 136, 139, 444, 586 | 页面标题、导航、来源 URL、空状态固定海门 | 是 | Phase 2 增加选择器；Phase 1 先把渲染函数参数化并保留默认海门 |
| `data_source/base.py` | 16, 358, 609-614, 629 | 默认地区、区域识别、地址正则固定海门 | 是，高风险 | 基类接收地区别名、行政区名称和地址词典 |
| `data_source/construction.py` | 106, 168 | 记录 `region` 固定南通市海门区 | 是 | 从采集上下文写入标准地区字段 |
| `data_source/construction_start_permit.py` | 21, 84, 109 | 海门标题提示和归属说明 | 是，高风险 | 标题提示、详情归属规则来自适配器/地区配置 |
| `data_source/investment_project.py` | 7 | 模块说明固定江苏/南通/海门 | 是，低风险 | 更新为能力范围说明 |
| `data_source/jiangsu_license.py` | 173, 971 | 记录地区和海门归属判断固定 | 是，高风险 | 接收地区代码、城市/区县别名和来源范围 |
| `data_source/jiangsu_natural_resource.py` | 16, 17 | 搜索关键词固定海门 | 是 | 从 RegionConfig 构建关键词 |
| `data_source/multi_source_runner.py` | 154 | CLI 描述固定海门 | 是 | 旧入口保留兼容，内部转统一 pipeline |
| `data_source/official_permit_record.py` | 97, 98 | 统一记录强制写海门区/320684 | 是，最高风险 | `from_validation_record` 必须接收地区对象，禁止隐式默认写入其他地区 |
| `data_source/permit_validation.py` | 26, 28, 29, 39, 65, 72, 128, 157-159, 359-360, 367-368, 379, 381, 384, 393, 948 | 海门代码、别名、来源、置信度与正则全部固定 | 是，最高风险 | 把通用验证与海门适配器拆开；地区证据规则由适配器提供 |
| `data_source/planning_construction_permit.py` | 27, 29, 69, 70, 109, 115, 116, 297, 322, 335, 337-344, 372, 394, 403, 616, 617 | `SEARCH_AREA_CODE`、来源名、区县、归属判断和 URL 固定 | 是，最高风险 | 构造函数传入 `RegionConfig` 与 source capability；保留海门默认兼容入口 |
| `data_source/planning_construction_permit_browser.py` | 63, 86, 88 | 浏览器 URL 和页面校验固定 areaCode/海门 | 是，高风险 | 根据 `source_area_code` 构建 URL 并校验选择值 |
| `data_source/planning_land_permit.py` | 15, 29, 30, 73 | 来源、固定区县及归属说明 | 是，高风险 | 保持独立适配器，但地区范围放入 capability 配置 |
| `database/official_permits.py` | 196 | SQL 固定过滤 `district_code='320684'` | 是，最高风险 | 所有查询必须显式传入地区代码并建立组合索引 |
| `database/storage.py` | 838, 839 | 规划许可入库默认海门区/320684 | 是，最高风险 | 参数对象必须携带完整地区字段；迁移旧记录时显式回填海门 |

## 测试与文档命中清单

测试中的海门样本多数应保留为 V1 回归基线，但必须补充南京、苏州以及“跨地区不混入”的测试。固定区划代码应通过 fixture/RegionConfig 生成，避免测试推动生产代码继续硬编码。

| 文件 | 行号 | 处理建议 |
|---|---|---|
| `.learnings/ERRORS.md` | 205 | 历史事实，保留，不参数化 |
| `README.md` | 357 | V2 README 重整时更新为默认海门、支持江苏多地区 |
| `STREAMLIT_CLOUD.md` | 1 | 部署文档标题在 V2 发布阶段更新 |
| `tests/test_dashboard_data.py` | 32, 120, 122 | 保留海门 fixture，新增其他地区 fixture |
| `tests/test_dashboard_smoke.py` | 42, 86, 102, 110, 125, 126 | 保留 V1 默认海门回归；Phase 2 新增三级联动测试 |
| `tests/test_database_storage.py` | 20 | 改用地区 fixture |
| `tests/test_excel_writer.py` | 13, 19 | 输出内容样本，可保留 |
| `tests/test_field_extractor.py` | 9, 10, 14 | 解析样本，可保留并补充南京/苏州 |
| `tests/test_financing_analyzer.py` | 14, 30, 43 | AI 样本，可保留 |
| `tests/test_jiangsu_license.py` | 39, 110, 118, 125, 127, 137, 151, 153, 155, 168, 169, 171, 173, 189, 190, 195, 196, 210, 213 | 抽取 RegionConfig fixture；保留海门真实性回归 |
| `tests/test_official_permit_modules.py` | 42, 43, 49, 51, 52, 54, 67, 87, 127 | 参数化区县与地区隔离测试 |
| `tests/test_permit_data.py` | 146, 185, 187, 188, 190 | 加入不同地区 JSON 混合输入并验证隔离 |
| `tests/test_permit_ownership.py` | 24, 31, 32, 102, 108 | 地方国企规则改为配置 fixture |
| `tests/test_permit_validation.py` | 108, 113, 125, 126, 128, 130, 146, 153, 166, 167, 175 | 保留海门证据基线；为通用验证层增加其他地区 |
| `tests/test_planning_construction_permit.py` | 59, 86, 104, 118, 121, 122, 126, 127, 128, 136, 137 | 搜索参数改用地区 fixture，继续断言海门真实接口基线 |
| `tests/test_planning_permit_storage.py` | 17, 18, 24, 25, 27, 29, 45, 55, 56, 57 | 增加同名项目跨地区不去重、不串数据测试 |
| `tests/test_recent_permit_analysis.py` | 130 | AI 提示词改为动态地区断言 |

## 参数化原则

1. `administrative_code` 与政府数据源的 `source_area_code` 必须分开保存。
2. 所有仓储查询必须显式带地区条件；禁止依靠“数据库里目前只有海门数据”的假设。
3. 三类许可证保持独立适配器、独立关键词和独立解析规则。
4. 页面切换地区只读缓存，不自动高频访问政府网站。
5. 海门常量在完成迁移前允许作为兼容默认值，但必须集中在 `config/regions.json`，不得新增散落常量。
6. Phase 1 只做地区参数化与数据模型准备；三级选择器属于 Phase 2。
