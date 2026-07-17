# 海门企业雷达 Streamlit Cloud 部署说明

## GitHub 仓库要求

推荐把 `project-radar` 作为一个单独 GitHub 仓库上传。

如果上传的是上一级大仓库，也可以部署，但在 Streamlit Cloud 创建 App 时，入口文件要填写：

```text
project-radar/dashboard.py
```

## 入口文件

```text
dashboard.py
```

## 依赖文件

```text
requirements.txt
```

当前依赖：

```text
streamlit
pandas
folium
streamlit-folium
```

## Secrets 配置

不要把 `.env` 或真实 API Key 提交到 GitHub。

在 Streamlit Cloud 的 App 设置里添加 Secrets：

```toml
PROJECT_RADAR_LLM_API_KEY = "your_deepseek_api_key"
PROJECT_RADAR_LLM_MODEL = "deepseek-chat"
PROJECT_RADAR_LLM_BASE_URL = "https://api.deepseek.com"
```

当前 Dashboard 主要读取 `data/ai/financing_analysis_*.json`，正常展示不要求运行 LLM。
只有后续在云端触发 AI 分析时才需要这些 Secrets。

## 数据文件

Dashboard 会读取：

```text
data/ai/financing_analysis_*.json
```

为了让 GitHub 部署后能直接看到已有数据，`.gitignore` 已保留 `data/ai/` 下的 JSON 文件。
本地生成的 Excel 和去重状态文件仍然不会提交：

```text
data/excel/
data/state/
```

## 本地验证

在项目目录运行：

```powershell
python -m pip install -r requirements.txt
streamlit run dashboard.py
```

打开：

```text
http://localhost:8501
```

如果本地需要固定 8502 端口：

```powershell
streamlit run dashboard.py --server.port 8502
```

## Streamlit Cloud 创建 App

1. 登录 Streamlit Cloud。
2. 选择 GitHub 仓库。
3. 设置入口文件：
   - 单独仓库：`dashboard.py`
   - 上一级大仓库：`project-radar/dashboard.py`
4. 设置 Secrets。
5. Deploy。
