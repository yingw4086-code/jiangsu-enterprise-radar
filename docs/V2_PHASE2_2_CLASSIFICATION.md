# V2 Phase 2.2 项目主体识别增强

## 1. 阶段结论

Phase 2.2 已完成项目主体多规则分类和置信度升级。正式 SQLite 已从 Schema 7 升级到 Schema 8，225 条历史记录全部保留。

- `enterprise`：177
- `government`：1
- `unknown`：47
- `classification_confidence`：high 152、medium 26、low 47
- 从 Phase 2.1 的 `unknown` 中提升出 26 条潜在企业融资机会。
- 未修改 `dashboard.py`，未修改 Streamlit 页面展示逻辑。

## 2. 分类实现

实现文件：`data_source/project_classification.py`

核心返回对象：

```python
ProjectClassification(
    project_type="enterprise | government | unknown",
    confidence="high | medium | low",
)
```

兼容接口 `classify_project_type(...)` 仍保留，现有调用方无需一次性重构。

## 3. 规则与优先级

规则按以下顺序执行，前面的规则优先级更高。

### 3.1 企业主体关键词

在 `company_name` 和 `construction_unit` 中检查：

- 有限公司
- 股份有限公司
- 科技有限公司
- 制造有限公司
- 集团
- 产业有限公司
- 实业有限公司
- 新能源
- 智能装备
- 电子科技
- 材料科技

命中结果：

- `project_type=enterprise`
- `classification_confidence=high`

企业主体关键词保持最高优先级。即使项目名称同时包含“市政”“道路”“医院”等词，只要建设主体命中企业关键词，仍优先判断为企业。

### 3.2 政府项目关键词

在主体名称和项目名称中检查：

- 政府
- 财政
- 交通局
- 住建局
- 自然资源局
- 市政
- 道路
- 桥梁
- 公园
- 公共服务
- 学校
- 医院
- 保障房

命中结果：

- 主体名称命中：`government + high`
- 仅项目名称命中：`government + medium`

政府关键词判断先于项目名称的企业倾向信号，因此“学校扩建项目”仍属于 `government + medium`。

### 3.3 项目名称企业倾向信号

在未命中任何政府关键词时，项目名称包含以下任一信号：

- 年产
- 生产基地
- 产业化
- 扩建
- 技改
- 设备升级

命中结果：

- `project_type=enterprise`
- `classification_confidence=medium`

这类记录通常缺少明确企业名称，因此不设为 `high`。

### 3.4 无规则命中

未命中以上规则：

- `project_type=unknown`
- `classification_confidence=low`

本阶段严格使用指定词表，不自行把“中学”“管理委员会”等近义或关联概念扩展到政府关键词，以避免隐藏规则漂移。

## 4. 数据库变化

迁移脚本：`database/migrations/008_classification_confidence.py`

新增字段：

```sql
classification_confidence TEXT NOT NULL DEFAULT 'low'
```

新增索引：

```sql
CREATE INDEX IF NOT EXISTS idx_permit_region_project_classification
ON construction_permits(
    region_key,
    project_type,
    classification_confidence
);
```

Schema 版本：`7 -> 8`

迁移脚本会：

1. 检查 Schema 7 前置字段。
2. 仅在缺少字段时增加 `classification_confidence`。
3. 使用统一分类函数同时重算 `project_type` 和置信度。
4. 校验迁移前后记录总数及所有字段取值。
5. 创建按地区、主体类型和置信度筛选的联合索引。
6. 保留高于当前迁移版本的 Schema 版本，避免版本倒退。

正式库连续运行两次结果一致，第二次 `added_columns=[]`。

## 5. 225 条历史数据结果

### 5.1 project_type 分布

| project_type | Phase 2.1 | Phase 2.2 | 变化 | Phase 2.2 占比 |
|---|---:|---:|---:|---:|
| enterprise | 151 | 177 | +26 | 78.67% |
| government | 1 | 1 | 0 | 0.44% |
| unknown | 73 | 47 | -26 | 20.89% |
| 合计 | 225 | 225 | 0 | 100.00% |

分类迁移路径：

- `enterprise -> enterprise`：151
- `government -> government`：1
- `unknown -> enterprise`：26
- `unknown -> unknown`：47

### 5.2 confidence 分布

| classification_confidence | 数量 | 占比 |
|---|---:|---:|
| high | 152 | 67.56% |
| medium | 26 | 11.56% |
| low | 47 | 20.89% |
| 合计 | 225 | 100.00% |

联合分布：

- `enterprise + high`：151
- `enterprise + medium`：26
- `government + high`：1
- `unknown + low`：47

## 6. 数据层接线

- `database/storage.py`
  - Schema 版本升级为 8。
  - 新建库和既有库自动具备置信度字段。
  - 普通许可证和建设工程规划许可证写入时同时保存类型和置信度。
  - 公共数据读取结果包含两个分类字段。
- `database/official_permits.py`
  - 建设用地规划许可证和建设工程施工许可证写入、读取及公开导出包含置信度。
- `app/permit_data.py`
  - 规划许可证 SQLite 读取增加置信度。
  - 旧 SQLite 或旧 Cloud JSON 缺少字段时回退为 `low`。
- `app/official_permit_data.py`
  - 官方许可证 SQLite/Cloud 读取增加分类字段及旧数据兼容回退。
- `crawler/export_cloud_data.py`
  - Cloud JSON 公开字段增加 `project_type` 和 `classification_confidence`。

以上均为数据层和逻辑层变化；没有增加页面控件或改变页面展示方式。

## 7. 安全与数据完整性

正式库核验：

- 迁移前记录：225
- 迁移后记录：225
- `PRAGMA integrity_check`：`ok`
- 外键违规：0
- 非法类型或置信度：0
- `region_key=320684`：225
- 除 `project_type` 和新增置信度字段外，所有许可证业务字段与备份逐行一致。

迁移前备份：

- 文件：`database/enterprise.phase2_2_backup_20260810_150233.db`
- 备份文件 SHA-256：`FA7DC7DDAA78183E5EF758CBFB2CB60503DB95365E672795036DF16967BEB8DD`
- 迁移前源库 SHA-256：`16581DB25DE0FC2127A3F3D8E73110AB2FF82E198CF599A50C6F9C8FD704B763`
- 逻辑内容 SHA-256：`B31B5AC358DEBA69B1CA35A1F03DDD2F0DA3720AB5D4A6077EBA0551C4326F1B`
- 源库与备份的表结构、逐表行数和确定性内容摘要一致。

SQLite Backup API 生成的文件页头可能与源文件不同，因此两个文件的二进制 SHA 不同；恢复有效性采用数据库完整性、外键、表结构、逐表行数和逻辑内容摘要验证。

## 8. 测试结果

- Phase 2.2 目标测试：30/30 通过。
- 项目全量回归：102/102 通过。
- 覆盖全部企业关键词、全部政府关键词、项目名称信号、优先级、三档置信度、迁移幂等、正式写入链路、Cloud 导出和旧数据回退。
- 现有 Streamlit 冒烟测试通过；输出仅包含既有 `use_container_width` 弃用警告。

## 9. 使用边界与后续建议

- `classification_confidence` 表示规则证据强弱，不表示银行授信通过概率。
- `medium` 企业记录适合作为客户经理待核验线索，不应直接等同于已确认企业客户。
- `unknown + low` 仍有 47 条，下一阶段可通过补齐建设主体、企业工商信息或人工复核降低未知比例。
- 建议后续筛选优先级为：`enterprise + high`、`enterprise + medium`、`unknown + low`，政府项目单独留作审计或排除视图。

本阶段未执行 Git push。
