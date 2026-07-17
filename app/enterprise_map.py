from __future__ import annotations

import hashlib
import html
import math
from typing import Any

import pandas as pd
import streamlit as st

from app.dashboard_data import (
    DashboardRecord,
    UNKNOWN,
    format_yuan,
    infer_financing_window,
    parse_amount_to_yuan,
    suggest_visit_time,
)

try:
    import folium
    from streamlit_folium import st_folium
except ImportError:  # pragma: no cover - depends on optional UI packages
    folium = None
    st_folium = None


HAIMEN_CENTER_LATITUDE = 31.8936
HAIMEN_CENTER_LONGITUDE = 121.1766
LEVEL_COLOR_HEX = {
    "A": "#d92d20",
    "B": "#f2c94c",
    "C": "#2f9e44",
}
LEVEL_COLOR_RGB = {
    "A": [217, 45, 32, 210],
    "B": [242, 201, 76, 220],
    "C": [47, 158, 68, 210],
}
INDUSTRY_FILTERS = ["制造业", "新能源", "电子", "设备制造"]
INVESTMENT_FILTERS = [
    ("5000万以上", 50_000_000),
    ("1亿以上", 100_000_000),
    ("5亿以上", 500_000_000),
]


def render_enterprise_map(records: list[DashboardRecord]) -> None:
    st.markdown("### 海门产业项目地图")
    st.caption("展示海门区域企业投资项目分布，红色为A级、黄色为B级、绿色为C级。")

    filtered_records = _render_map_filters(records)
    points = build_map_points(filtered_records)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("地图项目点位", len(points))
    col2.metric("A级客户", len([point for point in points if point["customer_level"] == "A"]))
    col3.metric("模拟坐标点", len([point for point in points if point["is_simulated"]]))
    col4.metric("投资金额合计", format_yuan(sum(point["investment_yuan"] for point in points)))

    if not points:
        st.info("当前筛选条件下暂无可展示企业项目。")
        return

    if folium and st_folium:
        _render_folium_map(points)
    else:
        _render_streamlit_map(points)

    st.markdown("### 地图企业清单")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "企业名称": point["enterprise_name"],
                    "项目名称": point["project_name"],
                    "行业": point["industry"],
                    "投资金额": point["investment_amount"],
                    "AI客户等级": f'{point["customer_level"]}级',
                    "融资机会": point["financing_need"],
                    "推荐贷款产品": point["recommended_products"],
                    "建议拜访时间": point["visit_time"],
                    "坐标模式": "模拟" if point["is_simulated"] else "真实",
                }
                for point in points
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )


def build_map_points(records: list[DashboardRecord]) -> list[dict[str, Any]]:
    points = []
    for index, record in enumerate(records):
        latitude, longitude, is_simulated = _record_coordinate(record, index)
        investment_yuan = _investment_yuan(record)
        point = {
            "enterprise_name": record.enterprise_name,
            "project_name": record.project_name,
            "industry": record.industry,
            "industry_filter": _industry_filter(record),
            "investment_amount": record.investment_amount,
            "investment_yuan": investment_yuan,
            "customer_level": record.customer_level,
            "financing_need": record.financing_need,
            "recommended_products": record.recommended_products,
            "marketing_advice": record.marketing_advice,
            "visit_time": suggest_visit_time(record),
            "financing_window": infer_financing_window(record),
            "latitude": latitude,
            "longitude": longitude,
            "is_simulated": is_simulated,
            "color_hex": LEVEL_COLOR_HEX.get(record.customer_level, "#2f9e44"),
            "color_rgb": LEVEL_COLOR_RGB.get(record.customer_level, [47, 158, 68, 210]),
        }
        point["popup_html"] = _popup_html(point)
        points.append(point)
    return points


def _render_map_filters(records: list[DashboardRecord]) -> list[DashboardRecord]:
    st.markdown("### 地图筛选")

    level_cols = st.columns(4)
    all_levels = level_cols[0].checkbox("全部", value=True, key="map_level_all")
    selected_levels: list[str] = []
    for column, level in zip(level_cols[1:], ["A", "B", "C"]):
        checked = column.checkbox(f"{level}级", value=False, disabled=all_levels, key=f"map_level_{level}")
        if checked:
            selected_levels.append(level)
    if all_levels:
        selected_levels = ["A", "B", "C"]

    industry_cols = st.columns(4)
    selected_industries = [
        industry
        for column, industry in zip(industry_cols, INDUSTRY_FILTERS)
        if column.checkbox(industry, value=True, key=f"map_industry_{industry}")
    ]

    amount_cols = st.columns(3)
    selected_thresholds = [
        threshold
        for column, (label, threshold) in zip(amount_cols, INVESTMENT_FILTERS)
        if column.checkbox(label, value=False, key=f"map_amount_{threshold}")
    ]
    min_investment = max(selected_thresholds) if selected_thresholds else 0

    return [
        record
        for record in records
        if record.customer_level in selected_levels
        and _industry_filter(record) in selected_industries
        and _investment_yuan(record) >= min_investment
    ]


def _render_folium_map(points: list[dict[str, Any]]) -> None:
    map_obj = folium.Map(
        location=[HAIMEN_CENTER_LATITUDE, HAIMEN_CENTER_LONGITUDE],
        zoom_start=11,
        tiles="CartoDB positron",
        control_scale=True,
    )

    for point in points:
        folium.CircleMarker(
            location=[point["latitude"], point["longitude"]],
            radius=8,
            color=point["color_hex"],
            fill=True,
            fill_color=point["color_hex"],
            fill_opacity=0.88,
            tooltip=f'{point["enterprise_name"]} | {point["customer_level"]}级',
            popup=folium.Popup(point["popup_html"], max_width=360),
        ).add_to(map_obj)

    st_folium(map_obj, width=1200, height=560, returned_objects=[])


def _render_streamlit_map(points: list[dict[str, Any]]) -> None:
    st.warning("当前环境未安装 folium / streamlit-folium，已自动切换为内置地图模式。")
    map_df = pd.DataFrame(
        [
            {
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "color": point["color_hex"],
                "size": 120,
                "企业名称": point["enterprise_name"],
                "客户等级": f'{point["customer_level"]}级',
            }
            for point in points
        ]
    )
    st.map(map_df, latitude="latitude", longitude="longitude", color="color", size="size", use_container_width=True)

    selected = st.selectbox(
        "企业信息卡",
        points,
        format_func=lambda point: f'{point["customer_level"]}级 | {point["enterprise_name"]}',
    )
    st.markdown(selected["popup_html"], unsafe_allow_html=True)


def _record_coordinate(record: DashboardRecord, index: int) -> tuple[float, float, bool]:
    latitude = _first_float(record.raw, "latitude", "lat", "纬度", "项目纬度")
    longitude = _first_float(record.raw, "longitude", "lng", "lon", "经度", "项目经度")
    if latitude is not None and longitude is not None:
        return latitude, longitude, False

    seed = f"{record.enterprise_name}|{record.project_name}|{index}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    angle = int.from_bytes(digest[:2], "big") / 65535 * math.tau
    radius = 0.012 + int.from_bytes(digest[2:4], "big") / 65535 * 0.055
    latitude = HAIMEN_CENTER_LATITUDE + math.sin(angle) * radius
    longitude = HAIMEN_CENTER_LONGITUDE + math.cos(angle) * radius / math.cos(math.radians(HAIMEN_CENTER_LATITUDE))
    return round(latitude, 6), round(longitude, 6), True


def _first_float(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).strip())
        except ValueError:
            continue
    return None


def _industry_filter(record: DashboardRecord) -> str:
    text = f"{record.industry} {record.project_name} {record.source_title} {record.approval_item}"
    if any(keyword in text for keyword in ["新能源", "光伏", "电池", "储能", "风电", "氢能"]):
        return "新能源"
    if any(keyword in text for keyword in ["电子", "芯片", "智能", "传感", "半导体"]):
        return "电子"
    if any(keyword in text for keyword in ["设备", "装备", "机械", "电气", "零部件", "元件", "产线"]):
        return "设备制造"
    return "制造业"


def _investment_yuan(record: DashboardRecord) -> float:
    amount = parse_amount_to_yuan(record.investment_amount)
    if amount:
        return amount
    text = f"{record.project_name} {record.source_title} {record.reason}"
    return parse_amount_to_yuan(text)


def _popup_html(point: dict[str, Any]) -> str:
    return f"""
    <div style="font-size:14px;line-height:1.65;width:300px;color:#1f2933;">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:#10243d;">企业：{_safe(point["enterprise_name"])}</div>
      <div><b>项目：</b>{_safe(point["project_name"])}</div>
      <div><b>行业：</b>{_safe(point["industry"])}</div>
      <div><b>投资：</b>{_safe(point["investment_amount"])}</div>
      <div><b>客户等级：</b>{_safe(point["customer_level"])}级</div>
      <div><b>预计融资：</b>{_safe(point["recommended_products"])}</div>
      <div><b>融资窗口：</b>{_safe(point["financing_window"])}</div>
      <div><b>建议：</b>{_safe(point["visit_time"])}</div>
    </div>
    """


def _safe(value: Any) -> str:
    text = str(value or UNKNOWN)
    return html.escape(text)
