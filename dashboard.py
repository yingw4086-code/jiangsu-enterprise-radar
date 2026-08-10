from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from app.company_registry import (
    CompanyRegistryValidationError,
    enrich_items_with_company_registry,
    enrich_registry_completeness,
    summarize_registry_coverage,
)
from app.company_data_provider import CompanyDataProviderError
from app.company_import import (
    CompanyImportConfirmationError,
    execute_company_registry_excel_import,
    list_company_import_logs,
    preview_company_registry_excel,
)
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
from app.credit_analysis import (
    analyze_credit_opportunity,
    build_financing_report,
    enrich_credit_opportunity,
)
from app.enterprise_profile import EnterpriseProfile, build_enterprise_profile
from app.enterprise_profile_enhance import (
    ALL_FILTER as ALL_ENTERPRISE_PROFILE_FILTER,
    COMPANY_SCALE_OPTIONS,
    OWNERSHIP_TYPE_OPTIONS,
    EnhancedEnterpriseProfile,
    assess_company_strength,
    build_enhanced_enterprise_profile,
    enrich_company_strength,
)
from app.enterprise_map import render_enterprise_map
from app.finance_estimation import (
    FinanceEstimation,
    enrich_finance_estimations,
    estimate_finance_need,
    estimation_confidence_label,
)
from app.finance_scoring import (
    FINANCE_LEVEL_LABELS,
    FINANCE_LEVEL_OPTIONS,
    enrich_finance_opportunities,
    rank_finance_opportunities,
)
from app.industry_classification import enrich_industry_assessment
from app.marketing_report import (
    build_marketing_report,
    marketing_report_filename,
    render_marketing_report_pdf,
)
from app.marketing_tracking import (
    ALL_STATUS_FILTER,
    MARKETING_STATUSES,
    MarketingRecord,
    MarketingTrackingValidationError,
    add_marketing_record,
    get_marketing_record,
    list_marketing_records,
    update_marketing_record,
)
from app.official_permit_data import (
    OfficialPermitDataset,
    load_official_permit_dataset,
    sort_official_permits,
    summarize_official_permits,
)
from app.permit_ownership import (
    GOVERNMENT_AGENCY,
    PUBLIC_INSTITUTION,
    owner_category_label,
)
from app.permit_data_runtime import (
    OWNER_FILTER_OPTIONS,
    PROJECT_TYPE_FILTER_OPTIONS,
    PermitDataset,
    effective_permit_date,
    filter_permits_by_ownership,
    filter_permits_by_project_type,
    filter_planning_permits,
    load_planning_permit_dataset,
    select_priority_enterprise_opportunities,
    sort_classified_opportunities,
    summarize_planning_permits,
    summarize_region_opportunities,
)
from app.region_service import RegionConfig, RegionConfigError, RegionQueryService
from app.region_permit_summary import load_region_permit_summary


PROJECT_ROOT = Path(__file__).resolve().parent
AI_DATA_DIR = PROJECT_ROOT / "data" / "ai"
DATABASE_PATH = PROJECT_ROOT / "database" / "enterprise.db"
CLOUD_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_construction_permits.json"
CLOUD_LAND_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_land_permits.json"
CLOUD_START_PERMIT_PATH = PROJECT_ROOT / "data" / "cloud" / "construction_start_permits.json"
REGION_CONFIG_PATH = PROJECT_ROOT / "config" / "regions.json"
COMPANY_REGISTRY_TEMPLATE_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "phase3_10"
    / "company_registry_import_template.xlsx"
)
PLANNING_SOURCE_URL = (
    "http://zrzy.jiangsu.gov.cn/elsearch/search/index?"
    "areaCode=320684&content=%E5%BB%BA%E8%AE%BE%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%92%E8%AE%B8%E5%8F%AF%E8%AF%81"
)
LAND_PERMIT_TYPE = "建设用地规划许可证"
LAND_SOURCE_URL = "https://www.haimen.gov.cn/hmsgtj/xzxk/xzxk.html"
START_PERMIT_TYPE = "建设工程施工许可证"
START_SOURCE_URL = "https://shuju.nantong.gov.cn/ntsxzspj/pzjg/pzjg.html"


st.set_page_config(
    page_title="区域企业融资机会雷达",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    inject_styles()
    records = load_records(AI_DATA_DIR)
    files = latest_json_files(AI_DATA_DIR)
    try:
        region_service = RegionQueryService.from_file(REGION_CONFIG_PATH)
    except RegionConfigError as exc:
        st.error(f"区域配置加载失败：{exc}")
        st.stop()

    with st.sidebar:
        st.markdown("## 区域企业融资机会雷达")
        st.caption("银行客户经理融资机会驾驶舱")
        page = st.radio(
            "导航",
            [
                "首页 Dashboard",
                "AI授信分析",
                "企业画像",
                "我的客户列表",
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
            key="navigation_page",
        )
        selected_region = _default_region(region_service)
        if page in {"首页 Dashboard", "企业画像"}:
            st.divider()
            st.markdown("### 区域选择")
            selected_region = render_region_selector(region_service)
        st.divider()
        st.caption("旧版项目数据文件")
        if files:
            for file_path in files:
                st.caption(file_path.name)
        else:
            st.caption("尚未发现旧版JSON文件")

    permit_dataset = load_planning_permit_dataset(
        DATABASE_PATH,
        CLOUD_PERMIT_PATH,
        region_key=selected_region.region_key,
    )
    land_permit_dataset = load_official_permit_dataset(
        DATABASE_PATH,
        CLOUD_LAND_PERMIT_PATH,
        permit_type=LAND_PERMIT_TYPE,
        region_key=selected_region.region_key,
    )
    start_permit_dataset = load_official_permit_dataset(
        DATABASE_PATH,
        CLOUD_START_PERMIT_PATH,
        permit_type=START_PERMIT_TYPE,
        region_key=selected_region.region_key,
    )
    region_dataset = combine_region_datasets(
        permit_dataset,
        land_permit_dataset,
        start_permit_dataset,
    )

    if page == "首页 Dashboard":
        title = f"{selected_region.district}企业融资机会雷达"
    elif page == "AI授信分析":
        title = f"{selected_region.district}企业授信机会分析"
    elif page == "企业画像":
        title = f"{selected_region.district}企业工商画像"
    elif page == "我的客户列表":
        title = "客户经理跟进管理"
    else:
        title = "海门企业雷达"
    st.markdown(f'<div class="app-title">{title}</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">面向银行客户经理的区域企业融资机会监测系统</div>', unsafe_allow_html=True)

    if page == "首页 Dashboard":
        render_dashboard(region_dataset, selected_region)
        return
    if page == "AI授信分析":
        render_enterprise_analysis_page(region_dataset, selected_region)
        return
    if page == "企业画像":
        render_enhanced_enterprise_profile_page(region_dataset, selected_region)
        return
    if page == "我的客户列表":
        render_my_customer_list(DATABASE_PATH)
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


def render_region_selector(region_service: RegionQueryService) -> RegionConfig:
    default_region = _default_region(region_service)
    provinces = list(region_service.list_provinces())
    if str(st.session_state.get("region_province") or "") not in provinces:
        st.session_state["region_province"] = default_region.province
    province = st.selectbox("省", provinces, key="region_province")

    cities = list(region_service.list_cities(province))
    default_city = (
        default_region.city if default_region.province == province else cities[0]
    )
    if str(st.session_state.get("region_city") or "") not in cities:
        st.session_state["region_city"] = default_city
    city = st.selectbox("市", cities, key="region_city")

    districts = list(region_service.list_districts(province, city))
    default_district = (
        default_region.district
        if default_region.province == province and default_region.city == city
        else districts[0]
    )
    if str(st.session_state.get("region_district") or "") not in districts:
        st.session_state["region_district"] = default_district
    district = st.selectbox("区县", districts, key="region_district")
    region_key = region_service.resolve_region_key(province, city, district)
    st.session_state["selected_region_key"] = region_key
    selected_region = region_service.get_by_region_key(region_key)
    if selected_region.administrative_code != region_key:
        st.caption(
            f"数据查询键：{region_key}；"
            f"现行行政区划代码：{selected_region.administrative_code}"
        )
    else:
        st.caption(f"区域代码：{region_key}")
    return selected_region


def _default_region(region_service: RegionQueryService) -> RegionConfig:
    selected_region_key = str(
        st.session_state.get("selected_region_key") or "320684"
    )
    try:
        return region_service.get_by_region_key(selected_region_key)
    except LookupError:
        return region_service.list_regions()[0]


def combine_region_datasets(
    planning_dataset: PermitDataset,
    land_dataset: OfficialPermitDataset,
    start_dataset: OfficialPermitDataset,
) -> PermitDataset:
    registry_items = enrich_items_with_company_registry(
        [
            *planning_dataset.items,
            *land_dataset.items,
            *start_dataset.items,
        ],
        DATABASE_PATH,
    )
    completeness_items = [
        enrich_registry_completeness(item) for item in registry_items
    ]
    industry_items = [
        enrich_industry_assessment(item) for item in completeness_items
    ]
    strength_items = [enrich_company_strength(item) for item in industry_items]
    finance_items = enrich_finance_opportunities(strength_items)
    estimated_items = enrich_finance_estimations(finance_items)
    items = [enrich_credit_opportunity(item) for item in estimated_items]
    storage_sources = list(
        dict.fromkeys(
            source
            for source in (
                planning_dataset.storage_source,
                land_dataset.storage_source,
                start_dataset.storage_source,
            )
            if source
        )
    )
    last_updated = max(
        (
            value
            for value in (
                planning_dataset.last_updated,
                land_dataset.last_updated,
                start_dataset.last_updated,
            )
            if value and value != "未披露"
        ),
        default="未披露",
    )
    return PermitDataset(
        items=items,
        storage_source=" + ".join(storage_sources) or "暂无正式数据",
        last_updated=last_updated,
        source_path=planning_dataset.source_path,
    )


def render_dashboard(dataset: PermitDataset, region: RegionConfig) -> None:
    summary = summarize_region_opportunities(dataset.items)
    st.markdown(f"### {region.province} / {region.city} / {region.district}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("当前区域项目总数", summary["total_count"])
    col2.metric("企业项目数量", summary["enterprise_count"])
    col3.metric("政府项目数量", summary["government_count"])
    col4.metric(
        "高可信机会数量",
        summary["high_confidence_opportunity_count"],
    )

    regional_counts = load_region_permit_summary(
        DATABASE_PATH,
        REGION_CONFIG_PATH,
        province=region.province,
    )
    st.markdown("### 区域数据数量")
    province_col, nanjing_col, suzhou_col, nantong_col = st.columns(4)
    province_col.metric(
        f"{region.province}项目总数",
        regional_counts.province_total,
    )
    nanjing_col.metric("南京市", regional_counts.city_count("南京市"))
    suzhou_col.metric("苏州市", regional_counts.city_count("苏州市"))
    nantong_col.metric("南通市", regional_counts.city_count("南通市"))
    st.caption(
        "以上为当前数据库已导入记录数；未导入或来源尚未验证的区域不代表官方项目数为零。"
    )

    st.markdown("### 重点融资机会排行榜")
    available_finance_levels = {
        str(item.get("finance_level") or "")
        for item in dataset.items
        if bool(item.get("eligible_for_recommendation"))
    }
    default_finance_level = next(
        (
            level
            for level in FINANCE_LEVEL_OPTIONS
            if level in available_finance_levels
        ),
        "A",
    )
    finance_level = st.selectbox(
        "融资等级筛选",
        FINANCE_LEVEL_OPTIONS,
        index=FINANCE_LEVEL_OPTIONS.index(default_finance_level),
        key="homepage_finance_level_filter",
        format_func=lambda value: FINANCE_LEVEL_LABELS[value],
    )
    finance_items = rank_finance_opportunities(
        dataset.items,
        finance_level=finance_level,
    )
    st.caption(
        f"当前等级：{FINANCE_LEVEL_LABELS[finance_level]}，共 {len(finance_items)} 条；"
        "政府项目不进入融资推荐。"
    )
    if finance_items:
        st.dataframe(
            pd.DataFrame(_finance_opportunity_rows(finance_items)),
            use_container_width=True,
            hide_index=True,
        )
        render_finance_profile_links(finance_items)
    else:
        st.info(f"当前区域暂无 {FINANCE_LEVEL_LABELS[finance_level]}。")

    st.markdown("### 重点机会")
    priority_items = select_priority_enterprise_opportunities(dataset.items)
    st.caption(
        "仅展示企业项目；按分类置信度 high、medium、low 排序，"
        "同一置信度内按发布时间倒序。"
    )
    if priority_items:
        st.dataframe(
            pd.DataFrame(_opportunity_rows(priority_items)),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("当前区域暂无已识别的企业融资机会。")

    st.markdown("### 区域项目筛选")
    project_type_view = st.selectbox(
        "项目类型筛选",
        PROJECT_TYPE_FILTER_OPTIONS,
        index=0,
        key="homepage_project_type_filter",
    )
    filtered_items = filter_permits_by_project_type(dataset.items, project_type_view)
    if project_type_view == "企业项目":
        filtered_items = select_priority_enterprise_opportunities(filtered_items)
    else:
        filtered_items = sorted(
            filtered_items,
            key=lambda item: str(item.get("publish_date") or ""),
            reverse=True,
        )
    st.caption(f"当前筛选：{project_type_view}，共 {len(filtered_items)} 条。")
    if filtered_items:
        st.dataframe(
            pd.DataFrame(_opportunity_rows(filtered_items)),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(f"当前区域没有“{project_type_view}”记录。")

    with st.expander("数据诊断", expanded=False):
        diagnostics = {
            "region_key": region.region_key,
            "当前数据源": dataset.storage_source,
            "实际读取文件": dataset.source_path,
            "实际读取记录数": summary["total_count"],
            "最新同步时间": dataset.last_updated,
            "企业项目数": summary["enterprise_count"],
            "政府项目数": summary["government_count"],
            "高可信企业机会数": summary["high_confidence_opportunity_count"],
        }
        st.dataframe(
            pd.DataFrame(
                [{"诊断项": key, "结果": str(value)} for key, value in diagnostics.items()]
            ),
            use_container_width=True,
            hide_index=True,
        )
    st.caption("数据来源于政府公开信息，分类仅用于营销线索筛选，不作为授信审批依据。")


def _opportunity_rows(items: list[dict[str, object]]) -> list[dict[str, object]]:
    project_type_labels = {
        "enterprise": "企业项目",
        "government": "政府项目",
        "unknown": "待识别",
    }
    confidence_labels = {"high": "高", "medium": "中", "low": "低"}
    return [
        {
            "企业名称": _homepage_company_name(
                item.get("company_name") or item.get("construction_unit")
            ),
            "项目名称": item.get("project_name") or "项目名称暂未披露",
            "所属行业": item.get("industry") or "未披露",
            "发布时间": item.get("publish_date") or "未披露",
            "项目类型": project_type_labels.get(
                str(item.get("project_type") or "unknown"),
                "待识别",
            ),
            "置信度": confidence_labels.get(
                str(item.get("classification_confidence") or "low"),
                "低",
            ),
        }
        for item in items
    ]


def _finance_opportunity_rows(
    items: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "企业名称": _homepage_company_name(
                item.get("company_name") or item.get("construction_unit")
            ),
            "项目名称": item.get("project_name") or "项目名称暂未披露",
            "行业": item.get("industry") or "未披露",
            "融资评分": int(item.get("finance_score") or 0),
            "推荐贷款类型": item.get("loan_type") or "待核验",
            "建议联系时间": item.get("suggested_contact_time") or "建议30天内复核",
        }
        for item in items
    ]


def render_finance_profile_links(items: list[dict[str, object]]) -> None:
    with st.expander("点击企业名称进入详情页", expanded=False):
        st.caption("选择企业后将进入独立的企业画像与 AI 授信分析页面。")
        for index, item in enumerate(items[:20]):
            company_name = _homepage_company_name(
                item.get("company_name") or item.get("construction_unit")
            )
            columns = st.columns([2, 3, 1, 1])
            columns[0].button(
                company_name,
                key=f"open_enterprise_profile_{index}",
                on_click=_select_enterprise_for_analysis,
                args=(item,),
                use_container_width=True,
            )
            columns[1].write(item.get("project_name") or "项目名称暂未披露")
            columns[2].write(f"{int(item.get('finance_score') or 0)}分")
            columns[3].write(str(item.get("finance_level") or "C"))


def render_enterprise_analysis_page(
    dataset: PermitDataset,
    region: RegionConfig,
) -> None:
    st.markdown("### 企业画像与 AI 授信分析")
    st.caption(
        f"当前区域：{region.province} / {region.city} / {region.district}。"
        "分析基于公开许可证和现有融资评分，由本地规则生成，不调用外部 AI API。"
    )
    eligible_items = sorted(
        (
            item
            for item in dataset.items
            if bool(item.get("eligible_for_recommendation"))
            and _homepage_company_name(
                item.get("company_name") or item.get("construction_unit")
            )
            != "建设单位暂未披露"
        ),
        key=lambda item: (
            -int(item.get("finance_score") or 0),
            str(item.get("company_name") or ""),
            str(item.get("project_name") or ""),
        ),
    )
    if not eligible_items:
        st.info("当前区域暂无可生成企业画像的融资线索。")
        return

    items_by_key = {
        _enterprise_selection_key(item): item for item in eligible_items
    }
    selection_options = list(items_by_key)
    selected_key = str(
        st.session_state.get("analysis_enterprise_selector")
        or st.session_state.get("selected_enterprise_key")
        or ""
    )
    if selected_key not in items_by_key:
        selected_key = selection_options[0]
        st.session_state["analysis_enterprise_selector"] = selected_key

    selected_key = st.selectbox(
        "选择企业项目",
        selection_options,
        key="analysis_enterprise_selector",
        format_func=lambda value: _enterprise_option_label(items_by_key[value]),
    )
    st.session_state["selected_enterprise_key"] = selected_key
    selected_item = items_by_key[selected_key]
    profile = build_enterprise_profile(selected_item)
    analysis = analyze_credit_opportunity(selected_item, profile=profile)
    estimation = estimate_finance_need(selected_item)

    score_col, level_col, product_col = st.columns(3)
    score_col.metric("融资评分", int(selected_item.get("finance_score") or 0))
    level_col.metric("机会等级", str(selected_item.get("finance_level") or "C"))
    product_col.metric(
        "推荐贷款产品",
        "、".join(analysis.recommended_products) or "待核验",
    )

    investment_col, credit_col, estimated_product_col = st.columns(3)
    investment_col.metric("预计投资规模", estimation.estimated_investment)
    credit_col.metric("预计融资需求", estimation.estimated_credit_need)
    estimated_product_col.metric(
        "金额预测推荐产品",
        estimation.recommended_product,
    )
    st.caption(
        "金额预测置信度："
        f"{estimation_confidence_label(estimation.estimation_confidence)}。"
        "规则区间仅用于营销线索筛选，不代表企业实际投资或可授信额度。"
    )
    with st.expander("查看融资金额预测依据", expanded=False):
        for basis in estimation.estimation_basis:
            st.write(f"- {basis}")

    st.markdown("#### 企业画像")
    st.dataframe(
        pd.DataFrame(_enterprise_profile_rows(profile)),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 授信机会初步判断")
    st.write(f"**预计资金需求：** {analysis.estimated_financing_need}")
    st.write(
        "**推荐贷款产品：** "
        + ("、".join(analysis.recommended_products) or "待核验")
    )
    st.write(f"**建议营销时间：** {analysis.suggested_marketing_time}")

    render_marketing_tracking_action(selected_item, profile)

    if st.button(
        "生成 AI 分析报告",
        type="primary",
        key=f"generate_ai_report_{selected_key}",
    ):
        st.session_state["generated_report_key"] = selected_key

    if st.session_state.get("generated_report_key") == selected_key:
        report = build_financing_report(selected_item, profile=profile)
        st.markdown(f"### {report.title}")
        st.caption(f"生成方式：{report.analysis_method}")
        for section in report.sections:
            st.markdown(f"#### {section.title}")
            st.write(section.content)
        st.warning(
            "本报告仅基于政府公开项目信息进行营销线索分析；成立时间、注册资本、"
            "征信、财务数据等未披露内容仍需客户经理尽调，不作为授信审批依据。"
        )

    st.markdown("#### 客户经理营销建议报告")
    if st.button(
        "生成营销报告",
        type="primary",
        key=f"generate_marketing_report_{selected_key}",
    ):
        st.session_state["generated_marketing_report_key"] = selected_key

    if st.session_state.get("generated_marketing_report_key") == selected_key:
        marketing_report = build_marketing_report(selected_item, profile=profile)
        st.markdown(f"### {marketing_report.title}")
        st.caption(
            f"生成方式：{marketing_report.analysis_method}　"
            f"报告日期：{marketing_report.generated_date}"
        )
        for section in marketing_report.sections:
            st.markdown(f"#### {section.title}")
            st.write(section.content)

        with st.expander("查看规则生成依据", expanded=False):
            for basis in marketing_report.explanation_basis:
                st.write(f"- {basis}")

        try:
            pdf_bytes = render_marketing_report_pdf(marketing_report)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.download_button(
                "下载PDF",
                data=pdf_bytes,
                file_name=marketing_report_filename(marketing_report),
                mime="application/pdf",
                key=f"download_marketing_report_{selected_key}",
                use_container_width=True,
            )
        st.warning(
            "营销报告仅基于政府公开信息和本地规则生成；未披露的工商、征信、"
            "财务和担保信息需要另行尽调，不作为授信审批依据。"
        )


def render_enhanced_enterprise_profile_page(
    dataset: PermitDataset,
    region: RegionConfig,
) -> None:
    st.markdown("### 企业工商画像")
    st.caption(
        f"当前区域：{region.province} / {region.city} / {region.district}。"
        "工商字段仅展示现有数据；未披露内容不推测、不补造。"
    )
    with st.expander("导入企业工商信息 Excel", expanded=False):
        import_flash = st.session_state.pop("company_registry_import_flash", "")
        if import_flash:
            st.success(import_flash)
        if COMPANY_REGISTRY_TEMPLATE_PATH.exists():
            st.download_button(
                "下载工商信息导入模板",
                data=COMPANY_REGISTRY_TEMPLATE_PATH.read_bytes(),
                file_name="company_registry_import_template.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                key="download_company_registry_import_template",
            )
        else:
            st.warning("工商信息导入模板暂不可用，请联系系统管理员。")
        st.caption(
            "支持 .xlsx；表头必须包含：企业名称、统一社会信用代码、法人、"
            "注册资本、成立日期、注册地址、经营范围、企业状态、行业分类（兼容行业）。"
            "空字段不会覆盖已有工商信息。"
        )
        registry_excel = st.file_uploader(
            "上传企业名单.xlsx",
            type=("xlsx",),
            key="company_registry_excel_uploader",
        )
        preview_state_key = "company_registry_import_preview"
        preview = None
        if registry_excel is not None:
            uploaded_bytes = registry_excel.getvalue()
            uploaded_sha256 = hashlib.sha256(uploaded_bytes).hexdigest().upper()
            preview_state = st.session_state.get(preview_state_key)
            if (
                preview_state
                and preview_state.get("file_sha256") != uploaded_sha256
            ):
                st.session_state.pop(preview_state_key, None)
                preview_state = None
            if st.button(
                "确认文件并生成预览",
                key="preview_company_registry_excel",
            ):
                try:
                    preview = preview_company_registry_excel(
                        DATABASE_PATH,
                        uploaded_bytes,
                        file_name=registry_excel.name,
                        permit_items=dataset.items,
                    )
                except (
                    OSError,
                    sqlite3.Error,
                    CompanyDataProviderError,
                    CompanyRegistryValidationError,
                ) as exc:
                    st.session_state.pop(preview_state_key, None)
                    st.error(f"工商信息预览失败：{exc}")
                else:
                    st.session_state[preview_state_key] = {
                        "file_name": preview.file_name,
                        "file_sha256": preview.file_sha256,
                        "total_count": preview.total_count,
                    }

            preview_state = st.session_state.get(preview_state_key)
            if preview_state and preview is None:
                try:
                    preview = preview_company_registry_excel(
                        DATABASE_PATH,
                        uploaded_bytes,
                        file_name=registry_excel.name,
                        permit_items=dataset.items,
                    )
                except (
                    OSError,
                    sqlite3.Error,
                    CompanyDataProviderError,
                    CompanyRegistryValidationError,
                ) as exc:
                    st.session_state.pop(preview_state_key, None)
                    st.error(f"工商信息预览已失效：{exc}")
                    preview = None

        if preview is not None:
            st.markdown("#### 数据预览")
            preview_col1, preview_col2, preview_col3, preview_col4 = st.columns(4)
            preview_col1.metric("待导入记录", preview.total_count)
            preview_col2.metric("预计新增", preview.inserted_count)
            preview_col3.metric("预计更新", preview.updated_count)
            preview_col4.metric(
                "匹配许可证企业",
                preview.permit_matched_company_count,
            )
            st.caption(
                f"文件：{preview.file_name}；预计匹配许可证项目 "
                f"{preview.permit_matched_project_count} 个。"
            )
            st.dataframe(
                pd.DataFrame(preview.to_display_rows()),
                use_container_width=True,
                hide_index=True,
            )
            unmatched_count = (
                preview.total_count - preview.permit_matched_company_count
            )
            if unmatched_count:
                st.warning(
                    f"有 {unmatched_count} 家企业未匹配当前区域许可证名称，"
                    "请确认名称后再导入。"
                )
            confirmed = st.checkbox(
                "我已核对预览内容，并确认写入 company_registry",
                key="confirm_company_registry_import",
            )
            if st.button(
                "确认导入 company_registry",
                key="execute_company_registry_excel_import",
                disabled=not confirmed,
                type="primary",
            ):
                try:
                    result = execute_company_registry_excel_import(
                        DATABASE_PATH,
                        uploaded_bytes,
                        file_name=preview.file_name,
                        expected_sha256=preview.file_sha256,
                        expected_total_count=preview.total_count,
                    )
                except (
                    OSError,
                    sqlite3.Error,
                    CompanyImportConfirmationError,
                    CompanyDataProviderError,
                    CompanyRegistryValidationError,
                ) as exc:
                    st.error(f"工商信息导入失败：{exc}")
                else:
                    st.session_state.pop(preview_state_key, None)
                    st.session_state["company_registry_import_flash"] = (
                        f"导入完成：成功 {result.total_count} 条，失败 0 条；"
                        f"新增 {result.inserted_count} 条，更新 "
                        f"{result.updated_count} 条。企业画像、融资评分和"
                        "营销报告已重新计算。"
                    )
                    st.cache_data.clear()
                    st.rerun()

    coverage = summarize_registry_coverage(dataset.items)
    coverage_col1, coverage_col2, coverage_col3, coverage_col4 = st.columns(4)
    coverage_col1.metric("当前区域项目总数", coverage.total_project_count)
    coverage_col2.metric("已匹配企业项目", coverage.matched_project_count)
    coverage_col3.metric("已匹配企业数", coverage.matched_company_count)
    coverage_col4.metric("工商信息覆盖率", f"{coverage.coverage_percentage:.1f}%")

    entries = []
    for item in dataset.items:
        company_name = _homepage_company_name(
            item.get("company_name") or item.get("construction_unit")
        )
        if (
            str(item.get("project_type") or "unknown") != "enterprise"
            or str(item.get("owner_category") or "")
            in {GOVERNMENT_AGENCY, PUBLIC_INSTITUTION}
            or company_name == "建设单位暂未披露"
        ):
            continue
        profile = build_enhanced_enterprise_profile(item)
        estimation = estimate_finance_need(item)
        entries.append((item, profile, estimation))

    ownership_filter_col, scale_filter_col = st.columns(2)
    ownership_filter = ownership_filter_col.selectbox(
        "按企业性质筛选",
        (ALL_ENTERPRISE_PROFILE_FILTER, *OWNERSHIP_TYPE_OPTIONS),
        key="enhanced_profile_ownership_filter",
    )
    scale_filter = scale_filter_col.selectbox(
        "按规模筛选",
        (ALL_ENTERPRISE_PROFILE_FILTER, *COMPANY_SCALE_OPTIONS),
        key="enhanced_profile_scale_filter",
    )
    filtered_entries = [
        entry
        for entry in entries
        if (
            ownership_filter == ALL_ENTERPRISE_PROFILE_FILTER
            or entry[1].ownership_type == ownership_filter
        )
        and (
            scale_filter == ALL_ENTERPRISE_PROFILE_FILTER
            or entry[1].company_scale == scale_filter
        )
    ]
    filtered_entries.sort(
        key=lambda entry: (
            -int(entry[0].get("finance_score") or 0),
            entry[1].company_name,
            str(entry[0].get("project_name") or ""),
        )
    )

    company_count = len({entry[1].company_name for entry in filtered_entries})
    disclosed_business_count = sum(
        any(
            value != "未披露"
            for value in (
                entry[1].legal_person,
                entry[1].registered_capital,
                entry[1].establish_date,
                entry[1].company_address,
                entry[1].business_scope,
                entry[1].company_status,
            )
        )
        for entry in filtered_entries
    )
    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("企业数量", company_count)
    metric2.metric("企业项目数量", len(filtered_entries))
    metric3.metric("有工商字段项目数", disclosed_business_count)

    if not filtered_entries:
        st.info("当前筛选条件下没有企业画像记录。")
        return

    st.dataframe(
        pd.DataFrame(
            [
                _enhanced_enterprise_profile_row(item, profile, estimation)
                for item, profile, estimation in filtered_entries
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    entries_by_key = {
        _enterprise_selection_key(item): (item, profile, estimation)
        for item, profile, estimation in filtered_entries
    }
    selected_key = st.selectbox(
        "查看企业画像详情",
        list(entries_by_key),
        key="enhanced_profile_detail_selector",
        format_func=lambda value: _enterprise_option_label(entries_by_key[value][0]),
    )
    selected_item, selected_profile, selected_estimation = entries_by_key[selected_key]
    base_profile = build_enterprise_profile(selected_item)

    st.markdown("#### 企业基本信息")
    st.dataframe(
        pd.DataFrame(_enhanced_enterprise_basic_rows(selected_profile)),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        f"企业性质依据：{selected_profile.ownership_basis}；"
        f"企业规模依据：{selected_profile.company_scale_basis}。"
    )

    st.markdown("#### 项目情况")
    st.dataframe(
        pd.DataFrame(
            [
                {"项目字段": "项目名称", "内容": base_profile.project_name},
                {"项目字段": "所属行业", "内容": base_profile.industry},
                {"项目字段": "项目阶段", "内容": base_profile.project_stage},
                {
                    "项目字段": "许可证类型",
                    "内容": str(selected_item.get("permit_type") or "未披露"),
                },
                {
                    "项目字段": "所属地区",
                    "内容": base_profile.region,
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    selected_strength = assess_company_strength(
        selected_item,
        profile=selected_profile,
    )
    score_col, strength_col, completeness_col, scale_col, industry_col = st.columns(5)
    score_col.metric("融资评分", int(selected_item.get("finance_score") or 0))
    strength_col.metric("企业实力等级", selected_strength.strength_label)
    completeness_col.metric(
        "工商信息完整度",
        f"{int(selected_item.get('registry_completeness_percentage') or 0)}% "
        f"{str(selected_item.get('registry_completeness_level') or 'D')}",
    )
    scale_col.metric("企业规模判断", selected_profile.company_scale)
    industry_col.metric(
        "行业判断",
        str(selected_item.get("industry_classification") or "待判断"),
    )
    st.caption(
        "行业判断依据："
        f"{str(selected_item.get('industry_classification_basis') or '当前信息不足')}；"
        "企业规模判断依据："
        f"{selected_profile.company_scale_basis}。"
    )
    amount_col, product_col = st.columns(2)
    amount_col.metric("预计融资金额", selected_estimation.estimated_credit_need)
    product_col.metric("推荐产品", selected_estimation.recommended_product)
    st.markdown("#### 融资评分构成")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "评分维度": "项目价值（40%）",
                    "得分": int(selected_item.get("project_value_score") or 0),
                    "满分": 40,
                },
                {
                    "评分维度": "企业实力（20%）",
                    "得分": int(selected_item.get("enterprise_strength_score") or 0),
                    "满分": 20,
                },
                {
                    "评分维度": "工商信息完整度（10%）",
                    "得分": int(selected_item.get("registry_completeness_score") or 0),
                    "满分": 10,
                },
                {
                    "评分维度": "融资需求（20%）",
                    "得分": int(selected_item.get("financing_need_score") or 0),
                    "满分": 20,
                },
                {
                    "评分维度": "时间窗口（10%）",
                    "得分": int(selected_item.get("time_window_score") or 0),
                    "满分": 10,
                },
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("查看企业实力判断依据"):
        for basis in selected_strength.assessment_basis:
            st.write(f"- {basis}")
    st.warning(
        "工商画像和规模分类仅基于当前已有公开字段；未知项需通过工商登记、"
        "征信、财务报表和客户访谈核验，不作为授信审批依据。"
    )
    import_logs = list_company_import_logs(DATABASE_PATH, limit=10)
    with st.expander("最近工商数据导入日志", expanded=False):
        if import_logs:
            st.dataframe(
                pd.DataFrame([record.to_display_row() for record in import_logs]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无工商数据导入日志。")


def _enhanced_enterprise_profile_row(
    item: dict[str, object],
    profile: EnhancedEnterpriseProfile,
    estimation: FinanceEstimation,
) -> dict[str, object]:
    return {
        "企业名称": profile.company_name,
        "统一社会信用代码": profile.unified_social_credit_code,
        "法人": profile.legal_person,
        "注册资本": profile.registered_capital,
        "成立年份": _establish_year(profile.establish_date),
        "注册地址": profile.company_address,
        "经营范围": profile.business_scope,
        "企业状态": profile.company_status,
        "所属行业": profile.industry,
        "行业判断": str(item.get("industry_classification") or "待判断"),
        "行业判断置信度": str(
            item.get("industry_classification_confidence") or "low"
        ),
        "企业性质": profile.ownership_type,
        "企业规模": profile.company_scale,
        "企业实力等级": str(item.get("enterprise_strength_label") or "D 信息不足"),
        "工商信息完整度": (
            f"{int(item.get('registry_completeness_percentage') or 0)}% "
            f"{str(item.get('registry_completeness_level') or 'D')}"
        ),
        "项目名称": item.get("project_name") or "未披露",
        "融资评分": int(item.get("finance_score") or 0),
        "预计融资金额": estimation.estimated_credit_need,
        "推荐产品": estimation.recommended_product,
    }


def _enhanced_enterprise_basic_rows(
    profile: EnhancedEnterpriseProfile,
) -> list[dict[str, str]]:
    return [
        {"企业字段": "企业名称", "内容": profile.company_name},
        {
            "企业字段": "统一社会信用代码",
            "内容": profile.unified_social_credit_code,
        },
        {"企业字段": "法人", "内容": profile.legal_person},
        {"企业字段": "注册资本", "内容": profile.registered_capital},
        {"企业字段": "成立年份", "内容": _establish_year(profile.establish_date)},
        {"企业字段": "注册地址", "内容": profile.company_address},
        {"企业字段": "经营范围", "内容": profile.business_scope},
        {"企业字段": "企业状态", "内容": profile.company_status},
        {"企业字段": "所属行业", "内容": profile.industry},
        {"企业字段": "企业性质", "内容": profile.ownership_type},
        {"企业字段": "企业规模", "内容": profile.company_scale},
    ]


def _establish_year(establish_date: str) -> str:
    text = str(establish_date or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return "未披露"


def render_marketing_tracking_action(
    item: dict[str, object],
    profile: EnterpriseProfile,
) -> None:
    st.markdown("#### 营销跟踪")
    try:
        record = get_marketing_record(
            DATABASE_PATH,
            enterprise_name=profile.company_name,
            project_name=profile.project_name,
            region=profile.region,
        )
    except (OSError, RuntimeError, sqlite3.Error, MarketingTrackingValidationError) as exc:
        st.warning(f"营销跟踪暂不可用：{exc}")
        return

    if record is None and st.button(
        "加入营销跟踪",
        key=f"add_marketing_tracking_{_enterprise_selection_key(item)}",
    ):
        try:
            record = add_marketing_record(
                DATABASE_PATH,
                enterprise_name=profile.company_name,
                project_name=profile.project_name,
                region=profile.region,
            )
        except (OSError, RuntimeError, sqlite3.Error, MarketingTrackingValidationError) as exc:
            st.error(f"加入营销跟踪失败：{exc}")
            return
        st.success("已加入营销跟踪，可在“我的客户列表”中更新进度。")

    if record is None:
        st.caption("当前项目尚未加入营销跟踪。")
    else:
        st.info(
            f"当前状态：{record.status}　客户经理：{record.customer_manager}　"
            f"最近跟进时间：{record.latest_follow_time}"
        )


def render_my_customer_list(db_path: Path) -> None:
    st.markdown("### 我的客户列表")
    st.caption("管理已加入营销跟踪的企业项目，并记录最近跟进时间和授信进度。")
    status_filter = st.selectbox(
        "跟进状态筛选",
        (ALL_STATUS_FILTER, *MARKETING_STATUSES),
        key="marketing_status_filter",
    )
    try:
        records = list_marketing_records(db_path, status=status_filter)
    except (OSError, RuntimeError, sqlite3.Error, MarketingTrackingValidationError) as exc:
        st.error(f"营销跟踪数据读取失败：{exc}")
        return

    followed_dates = [record.follow_date for record in records if record.follow_date]
    metric1, metric2 = st.columns(2)
    metric1.metric("客户项目数量", len(records))
    metric2.metric(
        "最近跟进时间",
        max(followed_dates) if followed_dates else "尚未跟进",
    )

    if not records:
        st.info(f"当前没有“{status_filter}”营销跟踪记录。")
        return

    st.dataframe(
        pd.DataFrame(_marketing_record_rows(records)),
        use_container_width=True,
        hide_index=True,
    )

    records_by_id = {record.id: record for record in records}
    selected_id = st.selectbox(
        "选择客户记录",
        list(records_by_id),
        key="marketing_record_selector",
        format_func=lambda record_id: _marketing_record_label(
            records_by_id[record_id]
        ),
    )
    selected = records_by_id[selected_id]
    st.markdown("#### 更新跟进记录")
    manager = st.text_input(
        "客户经理",
        value=selected.customer_manager,
        key=f"marketing_manager_{selected.id}",
    )
    status = st.selectbox(
        "更新跟进状态",
        MARKETING_STATUSES,
        index=MARKETING_STATUSES.index(selected.status),
        key=f"marketing_update_status_{selected.id}",
    )
    follow_day = st.date_input(
        "最近跟进时间",
        value=_tracking_date_value(selected.follow_date),
        key=f"marketing_follow_date_{selected.id}",
    )
    estimated_amount = st.number_input(
        "预计授信金额（元）",
        min_value=0.0,
        value=float(selected.estimated_credit_amount),
        step=100_000.0,
        key=f"marketing_credit_amount_{selected.id}",
    )
    notes = st.text_area(
        "跟进备注",
        value=selected.notes,
        key=f"marketing_notes_{selected.id}",
    )
    if st.button("保存跟进记录", key=f"save_marketing_record_{selected.id}"):
        try:
            update_marketing_record(
                db_path,
                selected.id,
                customer_manager=manager,
                status=status,
                follow_date=follow_day.isoformat(),
                estimated_credit_amount=estimated_amount,
                notes=notes,
            )
        except (
            OSError,
            LookupError,
            RuntimeError,
            sqlite3.Error,
            MarketingTrackingValidationError,
        ) as exc:
            st.error(f"保存跟进记录失败：{exc}")
        else:
            st.success("跟进记录已更新。")
            st.rerun()


def _marketing_record_rows(
    records: list[MarketingRecord],
) -> list[dict[str, object]]:
    return [
        {
            "企业名称": record.enterprise_name,
            "项目名称": record.project_name,
            "所属地区": record.region,
            "发现日期": record.discovery_date,
            "客户经理": record.customer_manager,
            "跟进状态": record.status,
            "最近跟进时间": record.latest_follow_time,
            "预计授信金额（元）": record.estimated_credit_amount,
            "备注": record.notes,
        }
        for record in records
    ]


def _marketing_record_label(record: MarketingRecord) -> str:
    return f"{record.enterprise_name}｜{record.project_name}｜{record.status}"


def _tracking_date_value(value: str) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.today()


def _select_enterprise_for_analysis(item: dict[str, object]) -> None:
    selection_key = _enterprise_selection_key(item)
    st.session_state["selected_enterprise_key"] = selection_key
    st.session_state["analysis_enterprise_selector"] = selection_key
    st.session_state["navigation_page"] = "AI授信分析"


def _enterprise_selection_key(item: dict[str, object]) -> str:
    return "|".join(
        str(item.get(field) or "")
        for field in (
            "region_key",
            "permit_type",
            "permit_number",
            "company_name",
            "project_name",
            "source_url",
        )
    )


def _enterprise_option_label(item: dict[str, object]) -> str:
    company_name = _homepage_company_name(
        item.get("company_name") or item.get("construction_unit")
    )
    project_name = str(item.get("project_name") or "项目名称暂未披露")
    return f"{company_name}｜{project_name}"


def _enterprise_profile_rows(profile: EnterpriseProfile) -> list[dict[str, str]]:
    return [
        {"画像字段": "企业名称", "内容": profile.company_name},
        {"画像字段": "企业类型", "内容": profile.enterprise_type},
        {"画像字段": "所属地区", "内容": profile.region},
        {"画像字段": "所属行业", "内容": profile.industry},
        {"画像字段": "项目名称", "内容": profile.project_name},
        {"画像字段": "项目阶段", "内容": profile.project_stage},
        {"画像字段": "成立时间", "内容": profile.established_time},
        {"画像字段": "注册资本", "内容": profile.registered_capital},
        {
            "画像字段": "企业信用等级",
            "内容": profile.enterprise_credit_level,
        },
    ]


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
