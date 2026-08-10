from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from io import BytesIO
from typing import Any, Mapping

from app.credit_analysis import analyze_credit_opportunity
from app.enterprise_profile import EnterpriseProfile, UNKNOWN, build_enterprise_profile
from app.finance_estimation import FinanceEstimation, estimate_finance_need


REPORT_TITLE = "《客户经理营销建议报告》"


@dataclass(frozen=True)
class MarketingReportSection:
    title: str
    content: str


@dataclass(frozen=True)
class MarketingReport:
    title: str
    company_name: str
    project_name: str
    finance_score: int
    finance_level: str
    estimated_investment: str
    estimated_credit_need: str
    recommended_product: str
    generated_date: str
    sections: tuple[MarketingReportSection, ...]
    explanation_basis: tuple[str, ...]
    analysis_method: str = "本地可解释规则分析"


def build_marketing_report(
    item: Mapping[str, Any],
    *,
    profile: EnterpriseProfile | None = None,
    today: date | None = None,
) -> MarketingReport:
    selected_profile = profile or build_enterprise_profile(item)
    analysis = analyze_credit_opportunity(item, profile=selected_profile)
    estimation = estimate_finance_need(item)
    score = _integer(item.get("finance_score"))
    level = str(item.get("finance_level") or "C")
    permit_type = _disclosed(item.get("permit_type"))
    investment = _disclosed(item.get("investment"))
    project_scale = _disclosed(item.get("project_scale"))
    products = _merged_products(
        analysis.recommended_products,
        estimation.recommended_product,
    )
    risks = _risk_notices(item, selected_profile, estimation)

    return MarketingReport(
        title=REPORT_TITLE,
        company_name=selected_profile.company_name,
        project_name=selected_profile.project_name,
        finance_score=score,
        finance_level=level,
        estimated_investment=estimation.estimated_investment,
        estimated_credit_need=estimation.estimated_credit_need,
        recommended_product=products,
        generated_date=(today or date.today()).isoformat(),
        sections=(
            MarketingReportSection(
                "1. 企业基本情况",
                f"企业名称：{selected_profile.company_name}；企业类型：{selected_profile.enterprise_type}；"
                f"所属地区：{selected_profile.region}；所属行业：{selected_profile.industry}；"
                f"成立时间：{selected_profile.established_time}；注册资本：{selected_profile.registered_capital}；"
                f"企业信用等级：{selected_profile.enterprise_credit_level}。",
            ),
            MarketingReportSection(
                "2. 项目投资情况",
                f"项目名称：{selected_profile.project_name}；公开投资金额：{investment}；"
                f"公开建设规模：{project_scale}；预计投资规模：{estimation.estimated_investment}；"
                f"融资机会评分：{score}分（{level}级）。",
            ),
            MarketingReportSection(
                "3. 当前项目阶段",
                f"许可证类型：{permit_type}；当前阶段：{selected_profile.project_stage}。"
                "阶段判断来自许可证类型及现有项目字段。",
            ),
            MarketingReportSection(
                "4. 预计融资需求",
                f"{analysis.estimated_financing_need}；"
                f"预计授信金额：{estimation.estimated_credit_need}。",
            ),
            MarketingReportSection("5. 推荐银行产品", products),
            MarketingReportSection("6. 最佳营销时间窗口", analysis.suggested_marketing_time),
            MarketingReportSection(
                "7. 首次拜访话术建议",
                _first_visit_script(selected_profile, permit_type, products),
            ),
            MarketingReportSection("8. 风险提示", "；".join(risks) + "。"),
        ),
        explanation_basis=_explanation_basis(
            item,
            selected_profile,
            products,
            estimation,
        ),
    )


def marketing_report_to_text(report: MarketingReport) -> str:
    lines = [
        report.title,
        f"企业：{report.company_name}",
        f"项目：{report.project_name}",
        f"融资评分：{report.finance_score}分",
        f"机会等级：{report.finance_level}",
        f"预计投资规模：{report.estimated_investment}",
        f"预计授信金额：{report.estimated_credit_need}",
        f"推荐贷款产品：{report.recommended_product}",
        f"报告日期：{report.generated_date}",
        "",
    ]
    for section in report.sections:
        lines.extend((section.title, section.content, ""))
    lines.append("生成依据")
    lines.extend(f"- {basis}" for basis in report.explanation_basis)
    lines.append("本报告仅用于银行客户经理营销线索参考，不作为授信审批依据。")
    return "\n".join(lines)


def render_marketing_report_pdf(report: MarketingReport) -> bytes:
    """Render a polished PDF in memory for Streamlit's download button."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            PageBreak,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError("PDF导出依赖缺失：请安装 reportlab") from exc

    font_name = "STSong-Light"
    try:
        pdfmetrics.getFont(font_name)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=19 * mm,
        bottomMargin=18 * mm,
        title=report.title,
        author="区域企业融资机会雷达",
        subject="银行客户经理营销线索分析",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MarketingTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#163A5F"),
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )
    meta_style = ParagraphStyle(
        "MarketingMeta",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#425466"),
    )
    heading_style = ParagraphStyle(
        "MarketingHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#0B5CAB"),
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
    )
    body_style = ParagraphStyle(
        "MarketingBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=16,
        textColor=colors.HexColor("#202A35"),
        spaceAfter=1.5 * mm,
    )
    note_style = ParagraphStyle(
        "MarketingNote",
        parent=body_style,
        fontSize=8.5,
        leading=14,
        textColor=colors.HexColor("#5E6C7B"),
    )

    def meta_cell(value: Any) -> Any:
        return Paragraph(escape(str(value)), meta_style)

    story: list[Any] = [
        Paragraph(escape(report.title), title_style),
        Table(
            [
                [
                    meta_cell("企业名称"),
                    meta_cell(report.company_name),
                    meta_cell("机会等级"),
                    meta_cell(report.finance_level),
                ],
                [
                    meta_cell("项目名称"),
                    meta_cell(report.project_name),
                    meta_cell("融资评分"),
                    meta_cell(f"{report.finance_score}分"),
                ],
                [
                    meta_cell("报告日期"),
                    meta_cell(report.generated_date),
                    meta_cell("生成方式"),
                    meta_cell(report.analysis_method),
                ],
                [
                    meta_cell("预计投资"),
                    meta_cell(report.estimated_investment),
                    meta_cell("预计授信"),
                    meta_cell(report.estimated_credit_need),
                ],
                [
                    meta_cell("推荐产品"),
                    meta_cell(report.recommended_product),
                    meta_cell("金额性质"),
                    meta_cell("本地规则区间"),
                ],
            ],
            colWidths=(25 * mm, 76 * mm, 25 * mm, 33 * mm),
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("LEADING", (0, 0), (-1, -1), 13),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EAF2F8")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#203040")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D6E2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 3 * mm),
    ]
    for section in report.sections:
        story.append(
            KeepTogether(
                [
                    Paragraph(escape(section.title), heading_style),
                    Paragraph(escape(section.content), body_style),
                ]
            )
        )

    story.extend(
        [
            PageBreak(),
            Paragraph("生成依据", heading_style),
            *[
                Paragraph(f"- {escape(basis)}", note_style)
                for basis in report.explanation_basis
            ],
            Spacer(1, 2 * mm),
            Paragraph(
                "重要说明：本报告仅基于政府公开项目信息和本地规则生成，用于营销线索参考；"
                "未披露的工商、征信、财务和担保信息需要另行尽调，不作为授信审批依据。",
                note_style,
            ),
        ]
    )

    def add_page_footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B7785"))
        canvas.drawString(18 * mm, 10 * mm, "区域企业融资机会雷达 | 客户经理内部营销参考")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_footer, onLaterPages=add_page_footer)
    return buffer.getvalue()


def marketing_report_filename(report: MarketingReport) -> str:
    safe_company = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in report.company_name
    ).strip("_")
    if not safe_company:
        safe_company = "enterprise"
    return f"{safe_company}_客户经理营销建议报告_{report.generated_date}.pdf"


def _first_visit_script(
    profile: EnterpriseProfile,
    permit_type: str,
    products: str,
) -> str:
    return (
        f"您好，我们关注到贵司“{profile.project_name}”已进入{profile.project_stage}，"
        f"公开信息显示已取得{permit_type}。想向您了解项目总投资、自有资金比例、"
        f"建设进度及后续采购计划。结合当前阶段，我行可重点沟通{products}，"
        "如您方便，希望安排一次现场拜访，进一步核实资金使用节点和期限需求。"
    )


def _risk_notices(
    item: Mapping[str, Any],
    profile: EnterpriseProfile,
    estimation: FinanceEstimation,
) -> list[str]:
    risks = ["许可证信息只能证明项目审批或建设进度，不能证明企业已有融资需求"]
    if profile.established_time == UNKNOWN:
        risks.append("成立时间未披露，需核验工商登记信息")
    if profile.registered_capital == UNKNOWN:
        risks.append("注册资本未披露，需核验实缴资本和股权结构")
    if profile.enterprise_credit_level.startswith("未评级"):
        risks.append("缺少征信及财务数据，当前不能形成企业信用评价")
    if _disclosed(item.get("investment")) == UNKNOWN:
        risks.append("项目投资金额未披露，需核实总投资及资金来源")
    if estimation.estimation_confidence == "low":
        risks.append(
            "预计投资和授信金额来自关键词及许可证阶段规则区间，不代表企业实际融资需求"
        )
    if str(item.get("classification_confidence") or "low") != "high":
        risks.append("项目主体分类置信度不是高，需人工复核企业属性")
    risks.append("授信方案仍需按银行准入、合规、担保和风险审批流程执行")
    return risks


def _explanation_basis(
    item: Mapping[str, Any],
    profile: EnterpriseProfile,
    products: str,
    estimation: FinanceEstimation,
) -> tuple[str, ...]:
    return (
        f"企业属性规则：project_type={str(item.get('project_type') or 'unknown')}，企业类型显示为“{profile.enterprise_type}”",
        f"项目阶段规则：许可证“{_disclosed(item.get('permit_type'))}”映射为“{profile.project_stage}”",
        (
            "融资评分规则："
            f"项目价值={_integer(item.get('project_value_score'))}/40，"
            f"企业实力={_integer(item.get('enterprise_strength_score'))}/20，"
            f"工商完整度={_integer(item.get('registry_completeness_score'))}/10，"
            f"融资需求={_integer(item.get('financing_need_score'))}/20，"
            f"时间窗口={_integer(item.get('time_window_score'))}/10，"
            f"finance_score={_integer(item.get('finance_score'))}，"
            f"finance_level={str(item.get('finance_level') or 'C')}"
        ),
        f"金额预测规则：{estimation.estimated_investment}，预计授信金额“{estimation.estimated_credit_need}”",
        f"产品规则：结合项目关键词及许可证阶段，推荐“{products}”",
        "风险规则：未披露字段保持未披露，并明确要求工商、征信、财务和担保尽调",
    )


def _merged_products(
    analysis_products: tuple[str, ...],
    estimation_product: str,
) -> str:
    products = list(analysis_products)
    if estimation_product and estimation_product != "不进入企业融资推荐":
        products.extend(
            part.strip()
            for part in estimation_product.replace("/", "、").split("、")
            if part.strip()
        )
    return "、".join(dict.fromkeys(products)) or "不进入企业融资推荐"


def _disclosed(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and text not in {UNKNOWN, "未知"} else UNKNOWN


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
