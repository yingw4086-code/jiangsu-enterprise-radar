from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from app.dashboard_data import (
    DashboardRecord,
    filter_records,
    format_yuan,
    industry_options,
    infer_financing_window,
    infer_financing_opportunities,
    infer_project_stage,
    infer_project_type,
    infer_risk_level,
    latest_json_files,
    load_records,
    marketing_priority_stars,
    sort_marketing_tasks,
    suggest_visit_time,
)
from app.enterprise_map import render_enterprise_map
from app.official_permit_data import (
    OfficialPermitDataset,
    load_official_permit_dataset,
    sort_official_permits,
    summarize_official_permits,
)
from app.permit_ownership import owner_category_label
from app.permit_data_runtime import (
    OWNER_FILTER_OPTIONS,
    PermitDataset,
    effective_permit_date,
    filter_permits_by_ownership,
    filter_planning_permits,
    load_planning_permit_dataset,
    select_homepage_opportunities,
    sort_classified_opportunities,
    summarize_homepage_permits,
    summarize_ownership_permits,
    summarize_planning_permits,
)


PROJECT_ROOT = Path(__file__).resolve().parent
AI_DATA_DIR = PROJECT_ROOT / "data" / "ai"
DATABASE_PATH = PROJECT_ROOT / "database" / "enterprise.db"
CLOUD_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_construction_permits.json"
CLOUD_LAND_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_land_permits.json"
CLOUD_START_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "construction_start_permits.json"
PLANNING_SOURCE_URL = (
    "http://zrzy.jiangsu.gov.cn/elsearch/search/index?"
    "areaCode=320684&content=%E5%BB%BA%E8%AE%BE%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%92%E8%AE%B8%E5%8F%AF%E8%AF%81"
)
LAND_PERMIT_TYPE = "建设用地规划许可证"
LAND_SOURCE_URL = "https://www.haimen.gov.cn/hmsgtj/xzxk/xzxk.html"
START_PERMIT_TYPE = "建设工程施工许可证"
START_SOURCE_URL = "https://shuju.nantong.gov.cn/ntsxzspj/pzjg/pzjg.html"


st.set_page_config(
    page_title="海门企业雷达",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    inject_styles()
    records = load_records(AI_DATA_DIR)
    files = latest_json_files(AI_DATA_DIR)
    permit_dataset = load_planning_permit_dataset(DATABASE_PATH, CLOUD_PERMIT_PATH)
    land_permit_dataset = load_official_permit_dataset(
        DATABASE_PATH,
        CLOUD_LAND_PERMIT_PATH,
        permit_type=LAND_PERMIT_TYPE,
    )
    start_permit_dataset = load_official_permit_dataset(
        DATABASE_PATH,
        CLOUD_START_PERMIT_PATH,
        permit_type=START_PERMIT_TYPE,
    )

    with st.sidebar:
        st.markdown("## 海门企业雷达")
        st.caption("区域企业融资机会驾驶舱")
        page = st.radio(
            "导航",
            [
                "首页 Dashboard",
                "海门建设工程规划许可证",
                "海门建设用地规划许可证",
                "海门建设工程施工许可证",
                "今日营销任务",
                "产业地图",
                "企业机会列表",
                "企业详情",
                "风险提示",
                "政府公益项目",
                "旧版项目数据",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("旧版项目数据文件")
        if files:
            for file_path in files:
                st.caption(file_path.name)
        else:
            st.caption("尚未发现旧版JSON文件")

    st.markdown('<div class="app-title">海门企业雷达</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">面向银行客户经理的区域企业融资机会监测系统</div>', unsafe_allow_html=True)

    if page == "首页 Dashboard":
        render_dashboard(permit_dataset)
        return
    if page == "海门建设工程规划许可证":
        render_planning_construction_permits(permit_dataset)
        return
    if page == "海门建设用地规划许可证":
        render_official_permit_page(
            land_permit_dataset,
            page_title="海门建设用地规划许可证",
            source_name="海门区自然资源局行政许可",
            source_url=LAND_SOURCE_URL,
            source_note="海门区官方行政许可栏目中的建设用地规划许可证记录。",
        )
        return
    if page == "海门建设工程施工许可证":
        render_official_permit_page(
            start_permit_dataset,
            page_title="海门建设工程施工许可证",
            source_name="南通市数据局批准结果",
            source_url=START_SOURCE_URL,
            source_note="仅展示详情页能以高置信度确认属于海门区的施工许可记录。",
        )
        return
    if page == "旧版项目数据":
        render_legacy_data(records, files)
        return
    if page == "政府公益项目":
        render_government_public_projects(permit_dataset)
        return
    if page == "企业机会列表":
        render_classified_opportunity_list(permit_dataset)
        return

    if not records:
        render_empty_state(has_files=bool(files))
        return

    if page == "今日营销任务":
        render_marketing_tasks(records)
    elif page == "产业地图":
        render_enterprise_map(records)
    elif page == "企业详情":
        render_company_detail(records)
    else:
        render_risk_page(records)


def render_dashboard(dataset: PermitDataset) -> None:
    summary = summarize_homepage_permits(dataset.items)
    ownership_summary = summarize_ownership_permits(dataset.items)
    st.markdown("### 真实许可证概览")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("今日新增许可证数量", summary["today_count"])
    col2.metric("最近30天新增许可证数量", summary["recent_30_days_count"])
    col3.metric("最近90天新增许可证数量", summary["recent_90_days_count"])
    col4.metric("当前真实许可证总数", summary["total_count"])

    st.markdown("### 项目主体性质")
    owner_col1, owner_col2, owner_col3 = st.columns(3)
    owner_col1.metric("民营企业项目数", ownership_summary["private_count"])
    owner_col2.metric("国有商业企业项目数", ownership_summary["state_owned_count"])
    owner_col3.metric("政府公益项目数", ownership_summary["government_public_count"])
    owner_col4, owner_col5 = st.columns(2)
    owner_col4.metric("待核验项目数", ownership_summary["unknown_count"])
    owner_col5.metric(
        "最近30天民营企业项目数",
        ownership_summary["recent_30_private_count"],
    )

    st.markdown("### 重点机会")
    ownership_view = st.selectbox(
        "主体性质筛选",
        OWNER_FILTER_OPTIONS,
        index=0,
        key="homepage_owner_filter",
    )
    top_items = select_homepage_opportunities(
        dataset.items,
        recent_days=90,
        limit=15,
        ownership_view=ownership_view,
    )
    if top_items:
        rows = []
        for item in top_items:
            products = item.get("recommended_products") or []
            if isinstance(products, str):
                products = [products] if products.strip() else []
            effective_date = effective_permit_date(item)
            rows.append(
                {
                    "企业或建设单位": _homepage_company_name(
                        item.get("owner_name") or item.get("company_name")
                    ),
                    "项目名称": item.get("project_name") or "项目名称暂未披露",
                    "主体性质": owner_category_label(item.get("owner_category")),
                    "营销优先级": item.get("marketing_priority") or "待核验",
                    "许可证类型": item.get("permit_type") or "建设工程规划许可证",
                    "许可证编号": item.get("permit_number") or "未披露",
                    "发现时间": effective_date.isoformat() if effective_date else "未披露",
                    "数据来源": item.get("source_name") or "政府公开信息",
                    "官方来源": item.get("source_url") or "",
                    "新鲜度": int(item.get("fresh_score") or 0),
                    "AI机会等级": item.get("ai_opportunity_level") or "待分析",
                    "推荐产品": "、".join(products) if products else "待分析",
                }
            )
        st.caption(
            f"当前筛选：{ownership_view}。仅展示最近90天真实许可证，"
            "按主体性质、营销优先级、近期程度、日期、新鲜度和AI机会等级排序。"
        )
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "官方来源": st.column_config.LinkColumn(
                    "官方来源",
                    display_text="查看原文",
                ),
                "新鲜度": st.column_config.NumberColumn(
                    "新鲜度",
                    min_value=0,
                    max_value=100,
                ),
            },
        )
    else:
        st.info(f"最近90天没有符合“{ownership_view}”条件的许可证记录。")

    with st.expander("数据诊断", expanded=False):
        diagnostics = {
            "当前数据源": dataset.storage_source,
            "实际读取文件": dataset.source_path,
            "实际读取记录数": summary["total_count"],
            "最新记录日期": summary["latest_date"],
            "最近30天数量": summary["recent_30_days_count"],
            "最近90天数量": summary["recent_90_days_count"],
            "可营销企业项目数": sum(
                bool(item.get("marketing_eligible")) for item in dataset.items
            ),
            "最近30天可营销企业数": ownership_summary[
                "recent_30_marketing_eligible_count"
            ],
        }
        st.dataframe(
            pd.DataFrame(
                [{"诊断项": key, "结果": str(value)} for key, value in diagnostics.items()]
            ),
            use_container_width=True,
            hide_index=True,
        )
    st.caption("数据来源于政府公开信息，AI分析仅用于营销线索筛选，不作为授信审批依据。")


def render_government_public_projects(dataset: PermitDataset) -> None:
    st.markdown("### 政府公益项目")
    st.caption("政府机关和事业单位项目仅用于审计，不进入首页默认重点机会。")
    items = filter_permits_by_ownership(dataset.items, "已排除政府公益项目")
    items = sorted(
        items,
        key=lambda item: effective_permit_date(item) or date.min,
        reverse=True,
    )
    government_count = sum(
        str(item.get("owner_category") or "") == "government_agency"
        for item in items
    )
    public_count = sum(
        str(item.get("owner_category") or "") == "public_institution"
        for item in items
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("政府机关项目", government_count)
    col2.metric("事业单位项目", public_count)
    col3.metric("审计记录总数", len(items))

    rows = []
    for item in items:
        effective_date = effective_permit_date(item)
        rows.append(
            {
                "建设单位": _homepage_company_name(
                    item.get("owner_name") or item.get("company_name")
                ),
                "项目名称": item.get("project_name") or "项目名称暂未披露",
                "主体性质": owner_category_label(item.get("owner_category")),
                "许可证日期": effective_date.isoformat() if effective_date else "未披露",
                "排除原因": item.get("exclusion_reason") or "政府公益项目",
                "判断依据": item.get("ownership_basis") or "待核验",
                "置信度": int(item.get("ownership_confidence") or 0),
                "官方来源": item.get("source_url") or "",
            }
        )
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "置信度": st.column_config.NumberColumn(
                    "置信度",
                    min_value=0,
                    max_value=100,
                ),
                "官方来源": st.column_config.LinkColumn(
                    "官方来源",
                    display_text="查看原文",
                ),
            },
        )
    else:
        st.info("当前没有已识别的政府机关或事业单位项目。")
    st.caption("原始许可证记录未删除，分类结果可通过人工覆盖表修正。")


def render_classified_opportunity_list(dataset: PermitDataset) -> None:
    st.markdown("### 企业机会列表")
    st.caption("列表使用真实建设工程规划许可证，并按项目主体性质筛选营销机会。")

    filter_col1, filter_col2, filter_col3 = st.columns([1.2, 1, 1.5])
    with filter_col1:
        ownership_view = st.selectbox(
            "主体性质",
            OWNER_FILTER_OPTIONS,
            index=0,
            key="opportunity_owner_filter",
        )
    with filter_col2:
        date_scope = st.segmented_control(
            "日期范围",
            ["最近30天", "最近90天", "全部"],
            default="最近90天",
            key="opportunity_date_scope",
        )
    with filter_col3:
        search = st.text_input(
            "搜索企业或项目",
            placeholder="输入建设单位或项目名称",
            key="opportunity_search",
        ).strip()

    recent_days = 30 if date_scope == "最近30天" else 90 if date_scope == "最近90天" else None
    filtered = filter_permits_by_ownership(dataset.items, ownership_view)
    filtered = filter_planning_permits(
        filtered,
        ai_level="全部",
        recent_days=recent_days,
    )
    if search:
        keyword = search.casefold()
        filtered = [
            item
            for item in filtered
            if keyword
            in " ".join(
                [
                    str(item.get("owner_name") or item.get("company_name") or ""),
                    str(item.get("project_name") or ""),
                    str(item.get("permit_number") or ""),
                ]
            ).casefold()
        ]
    filtered = sort_classified_opportunities(filtered)

    st.metric("当前筛选项目数", len(filtered))
    rows = []
    for item in filtered:
        effective_date = effective_permit_date(item)
        rows.append(
            {
                "企业或建设单位": _homepage_company_name(
                    item.get("owner_name") or item.get("company_name")
                ),
                "项目名称": item.get("project_name") or "项目名称暂未披露",
                "主体性质": owner_category_label(item.get("owner_category")),
                "营销优先级": item.get("marketing_priority") or "待核验",
                "许可证编号": item.get("permit_number") or "未披露",
                "许可证日期": effective_date.isoformat() if effective_date else "未披露",
                "数据来源": item.get("source_name") or "政府公开信息",
                "人工核验": "是" if item.get("manual_review_required") else "否",
                "官方来源": item.get("source_url") or "",
            }
        )
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "官方来源": st.column_config.LinkColumn(
                    "官方来源",
                    display_text="查看原文",
                ),
            },
        )
    else:
        st.info("当前筛选条件下没有真实许可证项目。")
    st.caption("数据来源于政府公开信息，仅用于营销线索筛选，不作为授信审批依据。")


def render_legacy_data(records: list[DashboardRecord], files: list[Path]) -> None:
    st.markdown("### 旧版项目数据")
    st.caption("以下内容来自旧版融资分析JSON，仅作历史查询，不参与首页统计和重点机会排序。")
    if files:
        st.caption("实际读取文件：" + "、".join(file_path.name for file_path in files))
    if not records:
        st.info("暂无旧版项目数据。")
        return
    rows = [record.to_table_row() for record in records]
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


def _homepage_company_name(value: object) -> str:
    text = str(value or "").strip()
    if not text or text in {"未披露", "未识别"}:
        return "建设单位暂未披露"
    return text


def render_planning_construction_permits(dataset: PermitDataset) -> None:
    st.markdown("### 海门建设工程规划许可证")
    st.markdown(f"官方数据来源：[江苏自然资源政务信息检索服务]({PLANNING_SOURCE_URL})")
    st.caption(f"最后更新时间：{dataset.last_updated}　数据读取：{dataset.storage_source}")

    summary = summarize_planning_permits(dataset.items)
    col1, col2, col3 = st.columns(3)
    col1.metric("总记录数", summary["total_count"])
    col2.metric("最近90天", summary["recent_90_days_count"])
    col3.metric("最近30天", summary["recent_30_days_count"])

    if dataset.items:
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            ai_level = st.segmented_control(
                "AI机会等级",
                ["全部", "A", "B", "C"],
                default="全部",
                key="planning_permit_ai_level",
            )
        with filter_col2:
            recent_30_only = st.toggle(
                "仅显示最近30天",
                value=False,
                key="planning_permit_recent_30",
            )
        filtered_items = filter_planning_permits(
            dataset.items,
            ai_level=ai_level or "全部",
            recent_days=30 if recent_30_only else None,
        )
        st.caption(f"当前显示 {len(filtered_items)} 条，按发证日期或发布日期倒序。")
        rows = []
        for item in filtered_items:
            company_name = _homepage_company_name(
                item.get("owner_name") or item.get("company_name")
            )
            permit_date = item.get("permit_date") or "未披露"
            publish_date = item.get("publish_date") or "未披露"
            recommended_products = item.get("recommended_products") or []
            rows.append(
                {
                    "企业或建设单位": company_name,
                    "项目名称": item.get("project_name") or "未披露",
                    "主体性质": owner_category_label(item.get("owner_category")),
                    "营销优先级": item.get("marketing_priority") or "待核验",
                    "分类置信度": int(item.get("ownership_confidence") or 0),
                    "人工核验": (
                        "是" if item.get("manual_review_required") else "否"
                    ),
                    "许可证编号": item.get("permit_number") or "未披露",
                    "发证日期": permit_date,
                    "发布日期": publish_date,
                    "项目地址": item.get("project_address") or "未披露",
                    "fresh_score": int(item.get("fresh_score") or 0),
                    "AI机会等级": item.get("ai_opportunity_level") or "待分析",
                    "融资需求": item.get("financing_need") or "待分析",
                    "推荐产品": "、".join(recommended_products) if recommended_products else "待分析",
                    "营销判断": item.get("marketing_summary") or "待分析",
                    "拜访建议": item.get("visit_suggestion") or "待分析",
                    "置信度": item.get("confidence"),
                    "风险提示": item.get("risk_notice") or "待分析",
                    "官方来源链接": item.get("source_url") or "",
                }
            )
        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fresh_score": st.column_config.NumberColumn("fresh_score", min_value=0, max_value=100),
                    "分类置信度": st.column_config.NumberColumn(
                        "分类置信度",
                        min_value=0,
                        max_value=100,
                    ),
                    "置信度": st.column_config.NumberColumn("置信度", min_value=0, max_value=100),
                    "官方来源链接": st.column_config.LinkColumn("官方来源链接", display_text="查看原文"),
                },
            )
        else:
            st.info("当前筛选条件下没有许可证记录。")
    else:
        st.info("建设工程规划许可证正式数据尚未导入。")

    st.caption("建设用地规划许可证和建设工程施工许可证已在独立标签页展示。")
    st.caption("数据来源于政府公开信息，AI分析仅用于营销线索筛选，不作为授信审批依据。")


def render_official_permit_page(
    dataset: OfficialPermitDataset,
    *,
    page_title: str,
    source_name: str,
    source_url: str,
    source_note: str,
) -> None:
    st.markdown(f"### {page_title}")
    st.markdown(f"官方数据来源：[{source_name}]({source_url})")
    st.caption(f"最后更新时间：{dataset.last_updated}　数据读取：{dataset.storage_source}")
    st.caption(source_note)

    summary = summarize_official_permits(dataset.items)
    col1, col2, col3 = st.columns(3)
    col1.metric("总记录数", summary["total_count"])
    col2.metric("最近90天", summary["recent_90_days_count"])
    col3.metric("最近30天", summary["recent_30_days_count"])

    rows = []
    for item in sort_official_permits(dataset.items):
        rows.append(
            {
                "企业或建设单位": item.get("company_name") or "未披露",
                "项目名称": item.get("project_name") or "未披露",
                "许可证编号": item.get("permit_number") or "未披露",
                "发证日期": item.get("permit_date") or "未披露",
                "发布日期": item.get("publish_date") or "未披露",
                "项目地址": item.get("project_address") or "未披露",
                "发证机关": item.get("issuing_authority") or "未披露",
                "fresh_score": int(item.get("fresh_score") or 0),
                "官方来源链接": item.get("source_url") or "",
            }
        )

    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "fresh_score": st.column_config.NumberColumn(
                    "fresh_score",
                    min_value=0,
                    max_value=100,
                ),
                "官方来源链接": st.column_config.LinkColumn(
                    "官方来源链接",
                    display_text="查看原文",
                ),
            },
        )
    else:
        st.info("当前没有通过海门归属核验的正式记录。")

    st.caption("数据来源于政府公开信息，仅用于营销线索筛选，不作为授信审批依据。")


def render_marketing_tasks(records: list[DashboardRecord]) -> None:
    st.markdown("### 今日营销任务")
    st.caption("按 AI 客户等级和投资金额自动排序，帮助客户经理确定当天优先拜访对象。")

    tasks = sort_marketing_tasks(records)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("待跟进企业", len(tasks))
    col2.metric("A级优先任务", len([record for record in tasks if record.customer_level == "A"]))
    col3.metric("存在融资需求", len([record for record in tasks if record.financing_need == "存在"]))
    col4.metric("建议今日优先拜访", len([record for record in tasks if record.customer_level == "A"][:5]))

    task_level = st.segmented_control("任务等级", ["全部", "A", "B", "C"], default="全部")
    if task_level != "全部":
        tasks = [record for record in tasks if record.customer_level == task_level]

    if not tasks:
        st.info("当前筛选条件下没有营销任务。")
        return

    for index, record in enumerate(tasks, start=1):
        render_marketing_task_card(index, record)


def render_marketing_task_card(index: int, record: DashboardRecord) -> None:
    opportunities = infer_financing_opportunities(record)
    opportunity_labels = [label for label, enabled in opportunities.items() if enabled]
    if not opportunity_labels:
        opportunity_labels = ["待核实"]

    card_class = f"task-card level-{record.customer_level.lower()}"
    st.markdown(
        f"""
<div class="{card_class}">
  <div class="task-card-header">
    <div>
      <div class="task-rank">#{index} 今日营销任务</div>
      <div class="task-company">{record.enterprise_name}</div>
    </div>
    <div class="task-level">AI等级 {record.customer_level}</div>
  </div>
  <div class="task-grid">
    <div><span>投资金额</span><strong>{record.investment_amount}</strong></div>
    <div><span>项目类型</span><strong>{infer_project_type(record)}</strong></div>
    <div><span>当前阶段</span><strong>{infer_project_stage(record)}</strong></div>
    <div><span>融资窗口</span><strong>{infer_financing_window(record)}</strong></div>
    <div><span>融资机会</span><strong>{"、".join(opportunity_labels)}</strong></div>
    <div><span>推荐产品</span><strong>{record.recommended_products}</strong></div>
    <div><span>风险</span><strong>{infer_risk_level(record)}</strong></div>
    <div><span>营销优先级</span><strong>{marketing_priority_stars(record)}</strong></div>
  </div>
  <div class="task-project"><span>项目：</span>{record.project_name}</div>
  <div class="task-visit"><span>建议拜访时间：</span>{suggest_visit_time(record)}</div>
  <div class="task-script"><span>AI营销话术：</span>{record.marketing_advice}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_opportunity_list(records: list[DashboardRecord]) -> None:
    st.markdown("### 企业机会列表")
    filtered = render_filters(records)
    table = pd.DataFrame([record.to_table_row() for record in filtered])
    st.caption(f"当前筛选结果：{len(filtered)} 条")
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    rows = getattr(getattr(event, "selection", None), "rows", [])
    if rows:
        selected_record = filtered[rows[0]]
        st.session_state["selected_company_project"] = f"{selected_record.enterprise_name}｜{selected_record.project_name}"
        st.success("已选中企业，可切换到“企业详情”查看完整分析。")


def render_company_detail(records: list[DashboardRecord]) -> None:
    st.markdown("### 企业详情")
    options = [f"{record.enterprise_name}｜{record.project_name}" for record in records]
    default_selected = st.session_state.get("selected_company_project")
    default_index = options.index(default_selected) if default_selected in options else 0
    selected = st.selectbox("选择企业项目", options, index=default_index)
    record = records[options.index(selected)]

    col1, col2, col3 = st.columns([1, 1, 1])
    col1.metric("AI客户等级", record.customer_level)
    col2.metric("融资需求判断", record.financing_need)
    col3.metric("模型置信度", f"{record.confidence:.0%}")

    st.markdown("#### 企业基本信息")
    st.table(
        pd.DataFrame(
            [
                ["企业名称", record.enterprise_name],
                ["所属行业", record.industry],
                ["项目地址", record.project_address],
                ["发现时间", record.discovery_time],
            ],
            columns=["字段", "内容"],
        )
    )

    st.markdown("#### 项目审批信息")
    st.table(
        pd.DataFrame(
            [
                ["项目名称", record.project_name],
                ["审批事项", record.approval_item],
                ["投资金额", record.investment_amount],
                ["数据来源", record.data_source],
                ["原始标题", record.source_title],
                ["来源链接", record.source_url],
            ],
            columns=["字段", "内容"],
        )
    )

    st.markdown("#### AI分析结果")
    st.write(record.reason)
    st.markdown("#### 融资机会")
    opportunities = infer_financing_opportunities(record)
    cols = st.columns(5)
    for index, (label, enabled) in enumerate(opportunities.items()):
        cols[index].metric(label, "有机会" if enabled else "暂不明显")

    st.markdown("#### AI推荐营销话术")
    st.info(record.marketing_advice)


def render_risk_page(records: list[DashboardRecord]) -> None:
    st.markdown("### 风险提示")
    low_value = [record for record in records if record.customer_level == "C"]
    duplicate_names = find_duplicate_enterprises(records)
    abnormal = [
        record
        for record in records
        if "未" in f"{record.enterprise_name}{record.project_name}{record.discovery_time}" or record.confidence < 0.5
    ]

    col1, col2, col3 = st.columns(3)
    col1.metric("低价值线索", len(low_value))
    col2.metric("重复企业", len(duplicate_names))
    col3.metric("数据异常", len(abnormal))

    st.markdown("#### 低价值线索")
    st.dataframe(pd.DataFrame([record.to_table_row() for record in low_value]), use_container_width=True, hide_index=True)

    st.markdown("#### 重复企业")
    if duplicate_names:
        st.dataframe(pd.DataFrame({"企业名称": duplicate_names}), use_container_width=True, hide_index=True)
    else:
        st.success("暂未发现重复企业")

    st.markdown("#### 数据异常")
    st.dataframe(pd.DataFrame([record.to_table_row() for record in abnormal]), use_container_width=True, hide_index=True)


def render_filters(records: list[DashboardRecord]) -> list[DashboardRecord]:
    col1, col2, col3, col4 = st.columns([1.5, 1, 1, 1.4])
    search = col1.text_input("搜索企业", placeholder="输入企业名称或项目关键词")
    level = col2.selectbox("按等级筛选", ["全部", "A", "B", "C"])
    industry = col3.selectbox("按行业筛选", industry_options(records))
    default_start = date.today() - timedelta(days=365)
    date_range = col4.date_input("按时间筛选", value=(default_start, date.today()))
    start_date, end_date = parse_date_range(date_range)
    return filter_records(records, search=search, level=level, industry=industry, start_date=start_date, end_date=end_date)


def parse_date_range(value) -> tuple[date | None, date | None]:
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], value[1]
    if isinstance(value, date):
        return value, value
    return None, None


def find_duplicate_enterprises(records: list[DashboardRecord]) -> list[str]:
    counts: dict[str, int] = {}
    for record in records:
        if record.enterprise_name == "未披露":
            continue
        counts[record.enterprise_name] = counts.get(record.enterprise_name, 0) + 1
    return sorted([name for name, count in counts.items() if count > 1])


def render_empty_state(has_files: bool) -> None:
    if has_files:
        st.warning("已发现 AI JSON 文件，但暂时没有可展示的企业机会记录。")
    else:
        st.warning("尚未读取到 AI 分析 JSON。")
    st.markdown(
        """
请先运行采集 + AI 分析，生成 `data/ai/financing_analysis_*.json` 文件：

```powershell
cd C:\\Users\\Administrator\\Documents\\包装agent实验1\\project-radar
powershell -ExecutionPolicy Bypass -File .\\run_once_with_ai.ps1
```
        """
    )


def inject_styles() -> None:
    st.markdown(
        """
<style>
  .stApp {
    background: #f4f7fb;
    color: #1d2733;
  }
  section[data-testid="stSidebar"] {
    background: #0f2742;
  }
  section[data-testid="stSidebar"] * {
    color: #f7fbff;
  }
  .app-title {
    font-size: 28px;
    font-weight: 700;
    color: #10243d;
    margin-bottom: 2px;
  }
  .app-subtitle {
    color: #5b6b7f;
    margin-bottom: 22px;
  }
  div[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #d9e2ec;
    border-radius: 6px;
    padding: 14px 16px;
  }
  div[data-testid="stMetricLabel"] {
    color: #637487;
  }
  div[data-testid="stMetricValue"] {
    color: #15395b;
  }
  .stDataFrame {
    border: 1px solid #d9e2ec;
  }
  .task-card {
    background: #ffffff;
    border: 1px solid #d9e2ec;
    border-left: 5px solid #8aa4bd;
    border-radius: 8px;
    padding: 18px 20px;
    margin: 14px 0;
    box-shadow: 0 2px 8px rgba(16, 36, 61, 0.04);
  }
  .task-card.level-a {
    border-left-color: #b68a24;
  }
  .task-card.level-b {
    border-left-color: #1f6f8b;
  }
  .task-card.level-c {
    border-left-color: #78909c;
  }
  .task-card-header {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: flex-start;
    margin-bottom: 14px;
  }
  .task-rank {
    color: #62748a;
    font-size: 13px;
    margin-bottom: 4px;
  }
  .task-company {
    color: #10243d;
    font-size: 22px;
    font-weight: 700;
    line-height: 1.25;
  }
  .task-level {
    color: #10243d;
    background: #eef4f9;
    border: 1px solid #d2deea;
    border-radius: 6px;
    padding: 6px 10px;
    font-weight: 700;
    white-space: nowrap;
  }
  .task-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 14px;
  }
  .task-grid div {
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
    min-height: 74px;
  }
  .task-grid span,
  .task-project span,
  .task-visit span,
  .task-script span {
    display: block;
    color: #66788a;
    font-size: 13px;
    margin-bottom: 4px;
  }
  .task-grid strong {
    color: #1d2733;
    font-size: 15px;
    line-height: 1.35;
    word-break: break-word;
  }
  .task-project,
  .task-visit,
  .task-script {
    border-top: 1px solid #edf2f7;
    padding-top: 10px;
    margin-top: 10px;
    color: #1d2733;
    line-height: 1.55;
  }
  .task-script {
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px;
  }
  @media (max-width: 1100px) {
    .task-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 700px) {
    .task-card-header {
      display: block;
    }
    .task-level {
      display: inline-block;
      margin-top: 10px;
    }
    .task-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
