# V2 Phase 3.14：江苏重点区域真实许可证数据接入报告

## 1. 完成结论

Phase 3.14 已完成。系统新增了受控的区域许可证导入能力，并将 11 条经政府官网逐条核验的许可证样本写入正式 SQLite：南京 4 条、苏州 5 条、南通市其他区域 2 条。

海门历史数据仍为 225 条，未删除、未覆盖、未重建。正式导入前后对海门历史记录计算的保护指纹完全一致：

`5a82c63d665bd3f72c46b5886bc3fd004d86c0526515fd2f366eeb9aa3afe7bb`

本阶段未新增 CRM、客户管理或 AI 功能，也未执行 Git push。

## 2. 正式数据库结果

| 范围 | region_key | 已导入项目数 |
|---|---:|---:|
| 江苏省 | - | 236 |
| 南京市 | - | 4 |
| 南京市江宁区 | 320115 | 2 |
| 南京市六合区 | 320116 | 2 |
| 苏州市 | - | 5 |
| 苏州市吴江区 | 320509 | 5 |
| 南通市 | - | 227 |
| 南通市海门区（历史数据） | 320684 | 225 |
| 南通市崇川区（本阶段新增） | 320613 | 2 |

说明：以上数字是当前数据库中已接入记录的数量，不代表各地政府网站公布的许可证总量；未接入为 0 也不能解释为当地没有许可证。

数据库完整性检查结果为 `ok`，当前 `schema_version=13`，总记录数为 236。全部 236 条记录均已有非空 `source_region` 和 `source_time`；海门旧数据由迁移脚本依据原有地区与记录时间做保守回填。

## 3. 数据来源与真实性边界

| 区域 | 官方来源 | 本阶段核验方式 | 导入数 |
|---|---|---|---:|
| 南京 | [南京市规划和自然资源局审批查询](https://ghj.nanjing.gov.cn/zhcx/spcx/) | 官网公开查询结果及详情字段人工核验 | 4 |
| 苏州 | [苏州市吴江区政府许可证公示样例](https://www.wujiang.gov.cn/zgwj/ggkjgh/202607/9cb5ef5ae5ea40d98c86a1a5dfaa1bf9.shtml) | 官网公示详情逐条核验 | 5 |
| 南通其他区域 | [南通市数据局许可证公示样例](https://shuju.nantong.gov.cn/ntsxzspj/sphjgs/content/3c00b10f-9c58-4fca-86e8-67e10cb12872.html) | 官网公示详情逐条核验 | 2 |

导入器只接受 `config/regional_permit_sources.json` 中状态为 `verified` 的来源、配置内的 HTTPS 官方域名和已配置 `region_key`。来源网址、来源地区、来源核验时间和许可证发布日期均需通过校验。南京官网对普通脚本访问存在访问控制，因此本阶段没有制作未经验证的实时抓取器，而是保留受控 JSON 批量导入通道。

南通新增的 2 条记录来自崇川区官网公示，原公示页未披露建设单位时，数据库保留“未披露”，未推测或补造企业名称。

## 4. 字段与迁移

统一导入字段：

- `project_name`：项目名称
- `construction_unit`：建设单位
- `permit_type`：许可证类型
- `publish_date` / `permit_date`：发布日期/许可日期
- `project_address`：地址
- `region_key`：区县行政区划键
- `source_region`：来源区域
- `source_time`：来源核验时间

迁移脚本 `database/migrations/013_regional_permit_sources.py`：

- 幂等增加 `source_region`、`source_time`；
- 增加区域与来源时间联合索引；
- 只对空值进行海门旧数据回填；
- 在迁移前后检查全库条数、海门条数和海门历史指纹。

正式迁移前数据库备份：

`database/backups/enterprise_pre_phase3_14_20260810.db`

备份 SHA-256：

`C83CB706CA2135CA3BD6461B6C20C05AAF30C63C6071CBA40C47936114154D4C`

## 5. 区域导入能力

新增命令：

```powershell
python crawler/import_regional_permits.py `
  --db database/enterprise.db `
  --input data/region_imports/phase3_14_verified_permits.json `
  --regions config/regions.json `
  --sources config/regional_permit_sources.json `
  --dry-run
```

移除 `--dry-run` 后才会写库。导入具备以下保护：

- 海门 `320684` 被列为保护区，区域批量导入器拒绝写入；
- 同一数据文件可重复运行，第二次执行结果为新增 0、更新 0、跳过 11；
- 来源域名、来源区域、区域键、许可证类型、日期字段均严格校验；
- 导入结束再次验证海门条数与历史指纹。

## 6. Dashboard 与 Cloud JSON

Dashboard 首页新增“区域数据数量”，展示：

- 江苏省项目总数；
- 南京项目数；
- 苏州项目数；
- 南通项目数。

区域三级选择和既有查询继续依据 `region_key` 过滤；当前区域项目总数仍显示在原统计区域。页面明确提示这些数字是已导入数据库记录数。

Cloud JSON 已重新导出，共 216 条建设工程规划许可证记录，其中海门 205、南京 4、苏州 5、南通其他区域 2。海门数据库总数 225 与 Cloud JSON 的规划许可证数 205 不同，是因为数据库还包括其他许可证类型。

导出前 Cloud JSON 备份：

`data/cloud/planning_construction_permits_pre_phase3_14.json`

## 7. 文件清单

本阶段主要新增：

- `config/regional_permit_sources.json`
- `data_source/regional_permit_import.py`
- `crawler/import_regional_permits.py`
- `data/region_imports/phase3_14_verified_permits.json`
- `database/migrations/013_regional_permit_sources.py`
- `app/region_permit_summary.py`
- `tests/test_phase3_14_regional_import.py`
- `docs/V2_PHASE3_14_REAL_REGION_PERMITS.md`

本阶段主要调整：

- `database/storage.py`
- `app/permit_data.py`
- `app/official_permit_data.py`
- `crawler/export_cloud_data.py`
- `dashboard.py`
- `data/cloud/planning_construction_permits.json`
- `tests/test_phase3_13_region_queries.py`
- `tests/test_phase3_12_integration.py`

## 8. 验证结果

- 区域导入专项测试：通过；
- 数据库迁移与幂等测试：通过；
- 南京、苏州、南通海门区域查询测试：通过；
- Python 编译检查：通过；
- 完整测试：`Ran 190 tests`，结果 `OK`；
- 正式库 `PRAGMA integrity_check`：`ok`；
- 海门正式库记录：225，保护指纹未变化；
- 未执行 Git push。

## 9. 后续边界

当前完成的是“可审计的真实样本接入”和稳定的区域导入基础设施，并非江苏各市许可证全量同步。若进入下一阶段，建议按区县逐个确认官方接口、分页规则、访问限制和数据使用条款，再扩大数据量；不能用搜索摘要或跨地区同名项目替代官网详情。
