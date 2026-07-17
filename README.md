# 区域企业项目雷达：建设项目公告采集模块

这是第一个 MVP 模块：

- 每天访问指定政府网站栏目。
- 抓取新增建设项目公告。
- 提取企业名称、项目名称、审批事项、日期、链接。
- 保存为 Excel 文件。
- 通过“数据源配置 + 适配器”方便后续增加其他网站。

当前版本不依赖第三方 Python 包，使用系统标准库即可运行。

## 快速运行

在当前项目根目录运行：

```powershell
cd project-radar
python -m app.main run-once
```

也可以显式指定配置文件：

```powershell
cd project-radar
python -m app.main run-once --config .\config\sites.json
```

更稳妥的方式是直接运行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_once.ps1
```

输出文件默认保存到：

```text
project-radar\data\excel\
```

文件名会带运行时间，例如：

```text
project_announcements_2026-07-14_083000.xlsx
```

这样同一天多次运行不会互相覆盖。

## 每天自动运行

推荐用 Windows 任务计划程序。管理员 PowerShell 中运行：

```powershell
cd project-radar
powershell -ExecutionPolicy Bypass -File .\tools\register_daily_task.ps1 -Time "08:30"
```

也可以让 Python 进程常驻：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_watch.ps1
```

## AI 融资机会分析

AI 分析模块会调用 OpenAI 兼容的大语言模型 API，并为每条公告生成结构化 JSON。

输出字段包括：

- 是否存在融资需求
- 预计贷款类型
- 客户价值等级
- 营销建议
- 判断理由
- 置信度

先在 PowerShell 中配置 API：

```powershell
$env:PROJECT_RADAR_LLM_API_KEY="你的API_KEY"
$env:PROJECT_RADAR_LLM_MODEL="你的模型名称"
$env:PROJECT_RADAR_LLM_BASE_URL="https://api.openai.com/v1"
```

也可以复制 `.env.example` 为 `.env`，把真实 Key 和模型名称填进去；`run_once_with_ai.ps1` 会自动读取 `.env`。

如果你使用的是其他 OpenAI 兼容接口，把 `PROJECT_RADAR_LLM_BASE_URL` 改成对应服务商地址。

运行采集 + AI 分析：

```powershell
cd project-radar
powershell -ExecutionPolicy Bypass -File .\run_once_with_ai.ps1
```

或者直接使用命令参数：

```powershell
python -m app.main run-once --with-ai
```

AI JSON 默认保存到：

```text
project-radar\data\ai\
```

输出结构示例：

```json
{
  "generated_at": "2026-07-14 08:30:00",
  "model": "your-model",
  "items": [
    {
      "enterprise_name": "示例企业有限公司",
      "project_name": "年产高端装备零部件项目",
      "approval_item": "项目备案",
      "date": "2026-07-14",
      "source_url": "https://example.com",
      "ai_analysis": {
        "has_financing_need": true,
        "expected_loan_types": ["项目贷款", "设备融资"],
        "customer_value_level": "A",
        "marketing_advice": "建议优先联系企业负责人，了解建设进度和设备采购计划。",
        "reason": "项目备案且涉及制造业扩产，可能存在固定资产投入。",
        "confidence": 0.86
      }
    }
  ]
}
```

## 修改监测网站

编辑：

```text
project-radar\config\sites.json
```

新增网站时，优先新增一段配置；如果网站结构特殊，再在 `app\sources` 下新增适配器。

如果 Python 访问网站时遇到本机证书链问题，可以在该站点配置里设置：

```json
"verify_ssl": false
```

这只影响公开网页采集，不会上传任何本地数据。

## 运行测试

```powershell
cd project-radar
python -m unittest discover -s tests -v
```

## 客户经理驾驶舱

第一版客户经理使用界面使用 Streamlit。

安装依赖：

```powershell
cd project-radar
python -m pip install -r requirements.txt
```

启动驾驶舱：

```powershell
cd project-radar
streamlit run dashboard.py
```

或者使用脚本：

```powershell
cd project-radar
powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1
```

浏览器打开：

```text
http://localhost:8502
```

驾驶舱读取：

```text
project-radar\data\ai\financing_analysis_*.json
```

如果页面提示没有数据，请先运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_once_with_ai.ps1
```

当前页面包括：

- 首页 Dashboard
- 企业机会列表
- 企业详情
- 风险提示

后续升级 Flask 正式系统时，建议保留 `app\dashboard_data.py` 的 JSON 读取和字段标准化逻辑，把 Streamlit 页面替换成：

- Flask/FastAPI 后端 API：提供企业列表、详情、指标、风险提示接口。
- 前端页面：React 或 Vue 企业 CRM 后台。
- 登录权限：客户经理、团队主管、管理员三类角色。
- 数据库：把 JSON 文件落入 PostgreSQL，支持多用户查询和历史追踪。
- 定时任务：继续复用现有采集和 AI 分析模块，改为后台任务写库。

## Streamlit Cloud ??

??? Streamlit Cloud ??????[`STREAMLIT_CLOUD.md`](./STREAMLIT_CLOUD.md)?

