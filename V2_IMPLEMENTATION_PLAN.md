# 江苏区域企业融资机会雷达 V2 实施计划

## 目标与边界

V2 在原仓库、原 `main` 历史、原 Streamlit 应用和原公网地址上渐进升级，不推倒重写 V1。

第一阶段目标是打通三个真实测试地区的：地区选择 → 官方数据源 → 三类许可证 → 企业主体 → 项目生命周期 → 融资机会。禁止模拟数据，禁止一次抓全江苏，禁止 React/FastAPI/PostgreSQL/CRM/登录体系重写。

默认地区始终为：江苏省 / 南通市 / 海门区。

## Phase 0 交付物

- `docs/V1_BASELINE.md`：V1 线上、数据、SQLite、页面和已知问题基线
- `docs/REGION_HARDCODE_REPORT.md`：43 文件、206 匹配行的地区硬编码审查
- `docs/UNTRACKED_FILE_REVIEW.md`：未跟踪文件保留、修正、归档建议
- `docs/DAILY_CRAWLER_REVIEW.md`：现有工作流问题与统一 pipeline 设计
- `tests/test_dashboard_smoke.py`：实时数量改为动态计算与时间窗口关系断言
- 本文件：V2 目录、数据库、Cloud JSON、阶段和 Phase 1 文件级计划

## 渐进式目录结构

现有 `data_source/` 已被大量代码引用。为避免同时存在 `data_source` 与 `data_sources` 两套包，V2 保留它作为唯一采集包，并逐步增加子目录；不做一次性移动。

```text
project-radar/
├─ app/
│  ├─ components/
│  │  ├─ region_selector.py
│  │  ├─ metric_cards.py
│  │  └─ opportunity_table.py
│  ├─ pages/
│  │  ├─ overview.py
│  │  ├─ permits.py
│  │  ├─ opportunities.py
│  │  └─ system_status.py
│  ├─ services/
│  │  ├─ region_service.py
│  │  ├─ project_service.py
│  │  └─ opportunity_service.py
│  └─ repositories/
│     ├─ permit_repository.py
│     ├─ company_repository.py
│     └─ project_repository.py
├─ config/
│  ├─ regions.json
│  ├─ source_capabilities.json
│  └─ sites.json
├─ data_source/
│  ├─ base.py
│  ├─ region_context.py
│  └─ adapters/
│     ├─ jiangsu_natural_resource.py
│     ├─ nantong_natural_resource.py
│     ├─ local_government.py
│     └─ housing_construction.py
├─ database/
│  ├─ storage.py
│  ├─ enterprise_master.py
│  ├─ project_master.py
│  └─ migrations/
├─ pipeline/
│  ├─ run_pipeline.py
│  ├─ cache_policy.py
│  ├─ cloud_export.py
│  └─ status_report.py
├─ data/
│  ├─ cache/<province>/<city>/<district>/
│  ├─ cloud/
│  │  ├─ regions.json
│  │  ├─ projects.json
│  │  ├─ enterprises.json
│  │  ├─ opportunities.json
│  │  ├─ permit_events.json
│  │  └─ system_status.json
│  └─ reports/
└─ tests/
   ├─ fixtures/regions/
   ├─ test_region_config.py
   ├─ test_region_isolation.py
   ├─ test_enterprise_master.py
   ├─ test_project_lifecycle.py
   └─ test_pipeline.py
```

目录按 Phase 逐步创建；Phase 0 不创建空包或占位代码。

## 地区配置模型

`config/regions.json` 的每个区县至少保存：

- `province_name`、`province_code`
- `city_name`、`city_code`
- `district_name`
- `administrative_code`
- `source_area_code`
- `enabled`
- `data_source_status`
- `last_verified_at`

`administrative_code` 是标准行政区划标识；`source_area_code` 是具体政府网站查询参数，二者禁止互相推导。地区通过稳定 `region_key` 引用，例如 `jiangsu/nantong/haimen`。

## 数据库改造方案

继续使用 SQLite，Phase 1 不迁移 PostgreSQL。Schema 采用版本化增量迁移，旧海门数据显式回填，禁止删除重建。

### 现有 `construction_permits` 增加

- `province`、`province_code`
- `city`、`city_code`
- `district`
- `administrative_code`
- `source_area_code`
- `region_key`

去重键与查询索引必须包含地区，避免不同区县同名项目被错误合并。

### 新建 `enterprise_master`

保存：企业名称、标准化名称、统一社会信用代码、完整地区、所有制类型、分类置信度、依据、营销资格、优先级、验证来源、验证时间和人工复核状态。普通“有限公司”不得直接判定为民营企业。

### 新建 `project_master`

保存：项目主体、标准项目名、地址、地区、当前阶段、最近事件、活跃度、融资窗口与匹配置信度。

### 新建 `permit_events`

每张许可证作为项目事件，关联 `project_master`。关联依据按建设单位、项目名、地址、时间和许可证编号组合评分；低置信度只进入人工复核，不强行合并。

### 新建 `pipeline_runs` / `region_source_status`

区分 `AVAILABLE`、`NO_DATA`、`NOT_COLLECTED`、`UNVERIFIED`、`SOURCE_ERROR`，记录 `last_attempt_at`、`last_success_at`、数量、错误与数据源。

## Cloud JSON 改造方案

V2 公网正式读取只允许：

- `regions.json`：地区树、启用状态与数据源状态
- `projects.json`：项目主数据和生命周期摘要
- `enterprises.json`：企业主体与分类
- `opportunities.json`：默认可营销机会
- `permit_events.json`：三类许可证事件
- `system_status.json`：pipeline 和数据新鲜度

每个文件都包含 `schema_version`、`generated_at`、`last_success_at`。所有业务项必须带 `region_key` 和标准地区字段。导出先写临时目录、完成 schema/数量/地区隔离检查后再原子替换。失败时保留上次成功文件，并只更新状态为 `SOURCE_ERROR`。

旧三个许可证 Cloud JSON 在 V2 过渡期继续保留，直到新 Dashboard 已验证读取统一 schema，防止破坏 V1。

## 缓存规则

- 维度：地区 + 许可证类型 + 数据源
- 默认 TTL：24 小时
- 用户切换地区：只读缓存，不触发网络采集
- 用户点击“刷新当前地区数据”：只刷新当前地区，并受速率限制
- 自动任务：只刷新 `enabled=true` 的测试地区
- 无缓存：显示 `NOT_COLLECTED`；数据源未经验证：显示 `UNVERIFIED`

## 三个真实测试地区

1. 江苏省 / 南通市 / 海门区（现有完整 V1 基线）
2. 江苏省 / 苏州市 / 待 Phase 3 官方数据源验证后确定一个区
3. 江苏省 / 南京市 / 待 Phase 3 官方数据源验证后确定一个区

Phase 0 不凭经验选择苏州、南京测试区，也不编造 `source_area_code`。Phase 3 必须以官方查询页面实际参数为证据。

## 开发阶段与停止条件

| Phase | 内容 | 通过条件 |
|---|---|---|
| 0 | 冻结 V1、修遗留、审查与计划 | 文档齐全；82 项测试全部通过 |
| 1 | 地区参数化 | 海门结果不变；生产代码不再依赖散落 `320684` |
| 2 | 江苏三级地区选择器 | 默认海门；城市与区县联动；切换只读缓存 |
| 3 | 三测试区真实数据源验证 | 三地区均有官方证据或明确 `UNVERIFIED`，无模拟数据 |
| 4 | 三类许可证统一地区架构 | 三类独立适配器、统一接口、地区隔离通过 |
| 5 | `enterprise_master` | 主体只取建设单位/项目业主；分类可追溯 |
| 6 | `project_master` 生命周期 | 三类许可证可关联为项目事件，低置信度可复核 |
| 7 | 融资机会筛选 | 公益默认排除；企业机会独立输出 |
| 8 | 每日自动更新闭环 | 统一 pipeline；失败保留旧数据；生成状态报告 |
| 9 | Cloud JSON 与 Streamlit 更新 | 统一 schema 上线，原网址和海门默认功能正常 |
| 10 | 测试与 V2 发布 | 全部测试通过，三地区隔离与线上验收通过 |

任一 Phase 未通过时先修复当前 Phase，不进入下一 Phase。

## Phase 1 文件级实施清单

Phase 1 只做地区参数化，不实现选择器、不抓苏州南京、不重写 Dashboard。

### 新增

- `config/regions.json`：先收录完整江苏城市树；仅海门 `enabled=true`，未验证地区状态明确
- `config/source_capabilities.json`：记录数据源支持地区、许可证类型和实际区域参数
- `data_source/region_context.py`：不可变 `RegionConfig`、加载和校验
- `tests/test_region_config.py`：行政代码/source code 分离、默认海门、非法配置测试
- `tests/test_region_isolation.py`：SQLite 与 JSON 跨地区隔离测试
- `database/migrations/005_region_fields.py`：旧海门数据显式回填

### 修改

- `data_source/base.py`：去除散落默认地区判断，接收 RegionConfig
- `data_source/planning_construction_permit.py`：请求与归属判断使用 `source_area_code`
- `data_source/planning_construction_permit_browser.py`：浏览器 URL/选中项校验参数化
- `data_source/permit_validation.py`：通用验证与海门证据规则解耦
- `data_source/planning_land_permit.py`：地区范围来自 capability
- `data_source/construction_start_permit.py`：标题提示和详情归属规则来自地区适配器
- `data_source/official_permit_record.py`：记录必须携带完整地区字段
- `data_source/jiangsu_license.py`、`jiangsu_natural_resource.py`、`construction.py`：移除固定 region 写入
- `database/storage.py`：Schema 5、地区字段、组合索引、带地区去重
- `database/official_permits.py`：所有查询和导出显式接收地区
- `app/permit_data.py`、`app/official_permit_data.py`：加载函数接受地区，默认海门
- `crawler/run_license.py` 及两个独立入口：增加 `--region-key`，默认海门
- 相关测试：使用 RegionConfig fixture，保留海门真实基线并新增跨地区隔离

### Phase 1 验证

1. 运行完整测试。
2. 海门 Cloud JSON 数量、来源和页面行为不变。
3. 同名项目在不同地区不会合并。
4. 任一查询缺少地区参数时测试失败，而不是默认为全库。
5. Git diff 不包含密钥、数据库、日志、debug 或本机绝对路径。

## 当前停止点

按照 `v2.docx` 指令，Phase 0 完成后停止。未经用户确认，不开始创建 `regions.json`、数据库迁移、地区选择器或 Phase 1 生产代码。
