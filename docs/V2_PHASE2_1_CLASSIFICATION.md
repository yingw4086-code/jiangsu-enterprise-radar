# V2 Phase 2.1 区域查询与项目主体分类

## 1. 阶段结论

Phase 2.1 已完成数据层和逻辑层升级，未修改 `dashboard.py`，未新增或调整 Streamlit 页面。

- 新增区域查询服务，可按 `region_key` 查询，也可将“省/市/区县”转换为 `region_key`。
- `construction_permits` 新增 `project_type` 字段，Schema 版本由 6 升至 7。
- 现有 225 条海门数据已完成分类，记录总数保持不变。
- 迁移脚本已连续运行两次，第二次未重复增加字段，分类数量保持一致。
- 已保留迁移前数据库备份，未删除任何历史数据。

## 2. 区域查询服务

实现文件：`app/region_service.py`

配置来源：`config/regions.json`

当前配置仍为海门：

```json
{
  "region_key": "320684",
  "province": "江苏省",
  "city": "南通市",
  "district": "海门区",
  "area_code": "320684"
}
```

查询能力：

```python
from app.region_service import RegionQueryService

service = RegionQueryService.from_file()
region = service.get_by_region_key("320684")
region_key = service.resolve_region_key("江苏省", "南通市", "海门区")
region_key = service.resolve_path("江苏省/南通市/海门区")
```

服务同时兼容三种配置形态：单个区域对象、区域数组、包含 `regions` 数组的对象。未来增加昆山等地区时无需修改查询算法。未知区域、空字段和重复配置会显式报错，避免静默落到错误地区。

## 3. project_type 分类规则

实现文件：`data_source/project_classification.py`

允许值：

- `enterprise`
- `government`
- `unknown`

### 3.1 企业优先规则

只要项目主体名称 `company_name` 包含下列任一关键词，优先分类为 `enterprise`：

- 有限公司
- 股份有限公司
- 科技有限公司
- 集团有限公司
- 制造有限公司

“企业优先”意味着：即使项目名称同时包含“市政”“道路”“医院”等政府类关键词，只要主体名称命中企业关键词，结果仍为 `enterprise`。

### 3.2 政府类规则

在未命中企业规则时，合并检查 `company_name`、`construction_unit` 和 `project_name`。包含以下任一关键词时分类为 `government`：

- 政府
- 交通局
- 住建局
- 自然资源局
- 市政
- 道路
- 桥梁
- 公园
- 学校
- 医院

“医院（政府建设）”按规则实现为：先执行企业优先判断，再检查“医院”关键词。因此私营医院有限公司仍为 `enterprise`，未命中企业标记的医院建设项目为 `government`。

### 3.3 保守兜底

未命中上述规则的记录分类为 `unknown`，不根据常识补猜。例如“管理委员会”不在本阶段给定关键词中，因此不会自行扩展为政府类。

## 4. 正式库迁移

数据库：`database/enterprise.db`

迁移脚本：`database/migrations/007_project_type.py`

数据库变化：

```sql
ALTER TABLE construction_permits
ADD COLUMN project_type TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_permit_region_project_type
ON construction_permits(region_key, project_type);
```

迁移行为：

1. 检查 `construction_permits` 是否存在。
2. 仅在缺少 `project_type` 时增加字段。
3. 按统一分类函数重新计算所有现有记录。
4. 创建 `(region_key, project_type)` 联合索引，为后续按区域筛选融资机会建立基础。
5. 校验迁移前后记录总数、字段取值和分类总数。
6. 将 `schema_meta.schema_version` 更新为 `7`。

幂等验证：

- 第一次运行：增加 `project_type`，225 条分类完成。
- 第二次运行：`added_columns=[]`，仍为 225 条，分类数量完全一致。

迁移前备份：

- 文件：`database/enterprise.phase2_1_backup_20260810_144740.db`
- SHA-256：`2EE48991613F26B0CA121E6516063AB9370C5566236D1F2DCFCFD885C54282BC`
- 大小：1,122,304 字节

## 5. 225 条正式数据分类结果

| project_type | 数量 | 占比 |
|---|---:|---:|
| enterprise | 151 | 67.11% |
| government | 1 | 0.44% |
| unknown | 73 | 32.44% |
| 合计 | 225 | 100.00% |

核验结果：

- `PRAGMA integrity_check`：`ok`
- 外键违规：0
- 空值或非法 `project_type`：0
- `region_key=320684`：225 条
- 联合索引 `idx_permit_region_project_type`：已存在

## 6. 数据链路改动

- `database/storage.py`
  - Schema 版本升级为 7。
  - 新建库和既有库均确保存在 `project_type`。
  - 普通许可证、建设工程规划许可证的新写入记录会同步计算 `project_type`。
  - 公共规划许可证读取结果增加 `project_type`。
- `database/official_permits.py`
  - 建设用地规划许可证和建设工程施工许可证等官方许可证写入时同步分类。
  - 公共导出字段增加 `project_type`，属于向后兼容的附加字段。
- `app/permit_data.py`
  - SQLite 有字段时读取实际 `project_type`。
  - 旧 SQLite 或旧 Cloud JSON 没有该字段时回退为 `unknown`，保证 V1 读取链路兼容。
- `app/region_service.py`
  - 提供区域代码与省/市/区县之间的逻辑层查询能力。

## 7. 测试覆盖

新增测试：

- `tests/test_region_service.py`
  - 海门按代码与名称查询。
  - 未来多区域配置。
  - 未知区域、非法路径和重复配置。
- `tests/test_project_classification.py`
  - 企业优先级。
  - 政府关键词覆盖。
  - 私营医院企业优先。
  - 未匹配记录保持 `unknown`。
  - 007 迁移幂等、记录保留、Schema 和索引检查。
- `tests/test_planning_permit_storage.py`
  - 新写入规划许可证自动产生 `enterprise` 分类。

测试结果：

- Phase 2.1 目标测试：24/24 通过。
- 项目全量回归：95/95 通过。
- 现有 Streamlit 冒烟测试通过；测试输出仅包含既有 `use_container_width` 弃用警告。

## 8. 风险与边界

- 关键词分类是融资机会筛选的基础标签，不等于最终客户性质认定。
- `unknown` 占 32.44%，主要风险来自建设单位未披露或名称不命中给定关键词，后续应通过更完整主体信息降低占比。
- 企业优先规则可能把政府背景平台公司分类为 `enterprise`；这是本阶段明确规则的结果，后续可叠加所有制分类，而不应直接改写本字段语义。
- 政府关键词可能出现在项目名称中，因此少数企业承建公共项目会因主体信息缺失而落入 `government`；后续应优先补齐真实建设主体。
- 本阶段未增加页面区域选择控件，也未修改任何 Streamlit 展示逻辑。

## 9. 下一阶段建议

1. 在保持默认 `region_key=320684` 的前提下，将区域查询服务接入页面选择控件。
2. 在数据层增加按 `region_key + project_type` 的组合查询接口。
3. 对 `unknown` 样本进行来源字段补全和人工抽检。
4. 将 `project_type` 与既有 `owner_category`、融资机会评分组合，形成可解释的筛选规则。

本阶段未执行 Git push。
