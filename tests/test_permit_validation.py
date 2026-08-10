from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from data_source.permit_validation import (
    HAIMEN_DISTRICT_CODE,
    PERMIT_SOURCES,
    PermitListItem,
    PermitValidationRecord,
    _DetailParser,
    _build_record,
    _extract_structured_fields,
    classify_haimen,
    is_target_list_item,
    parse_truecms_initial_page,
    parse_truecms_payload,
    write_validation_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PermitValidationTest(unittest.TestCase):
    def test_parses_saved_truecms_jsonp_xml_cdata_payloads(self) -> None:
        cases = (
            ("official_land_permit_list.jsonp", "https://www.haimen.gov.cn", 377),
            ("official_planning_construction_permit_list.jsonp", "https://shuju.nantong.gov.cn", 1788),
            ("official_construction_start_permit_list.jsonp", "https://shuju.nantong.gov.cn", 835),
        )
        for filename, base_url, expected_total in cases:
            payload = (PROJECT_ROOT / "tests" / "fixtures" / filename).read_text(
                encoding="utf-8"
            )
            total, items = parse_truecms_payload(payload, base_url)
            self.assertEqual(total, expected_total)
            self.assertEqual(len(items), 30)
            self.assertTrue(all(item.detail_url.startswith("https://") for item in items))

    def test_filters_mixed_columns_by_actual_permit_title(self) -> None:
        land = PERMIT_SOURCES[0]
        planning = PERMIT_SOURCES[1]
        construction = PERMIT_SOURCES[2]
        self.assertTrue(
            is_target_list_item(
                land,
                PermitListItem("关于同意某公司建设项目的...", "2026-07-13", "https://x"),
            )
        )
        self.assertTrue(
            is_target_list_item(
                planning,
                PermitListItem("R25013地块建设工程规划许可证调整批后公布", "2026-07-13", "https://x"),
            )
        )
        self.assertFalse(
            is_target_list_item(
                planning,
                PermitListItem("项目规划方案批前公示", "2026-07-13", "https://x"),
            )
        )
        self.assertTrue(
            is_target_list_item(
                construction,
                PermitListItem("某制造基地工程施工许可", "2026-07-13", "https://x"),
            )
        )
        self.assertFalse(
            is_target_list_item(
                construction,
                PermitListItem("某项目可行性研究报告的批复", "2026-07-13", "https://x"),
            )
        )

    def test_parses_truecms_initial_page_without_calling_pagination_api(self) -> None:
        html = """
        <div id="initData">
          <ul><li><a href="/ntsxzspj/pzjg/content/abc.html">示例项目工程施工许可</a><span>2026-07-20</span></li></ul>
          <ul><li><a href="/other/content/news.html">政策新闻</a><span>2026-07-19</span></li></ul>
        </div>
        <script>totalRecord:835,</script>
        """
        total, items = parse_truecms_initial_page(
            html,
            "https://shuju.nantong.gov.cn",
            "/ntsxzspj/pzjg/content/",
        )
        self.assertEqual(total, 835)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].publish_date, "2026-07-20")

    def test_list_parser_does_not_append_nested_date_to_title(self) -> None:
        payload = r'''raw({"result":"<datastore><totalrecord>1</totalrecord><recordset><record><![CDATA[<li><a href=\"/detail.html\">示例项目<span>2026-07-20</span></a></li>]]></record></recordset></datastore>"})'''
        total, items = parse_truecms_payload(payload, "https://example.test")
        self.assertEqual(total, 1)
        self.assertEqual(items[0].title, "示例项目")
        self.assertEqual(items[0].publish_date, "2026-07-20")

    def test_haimen_confidence_priority_and_threshold(self) -> None:
        by_code = PermitValidationRecord("x", "x", "普通项目", "建设工程施工许可证", "https://x")
        by_code.district_code = HAIMEN_DISTRICT_CODE
        classify_haimen(by_code)
        self.assertTrue(by_code.haimen_match)
        self.assertEqual(by_code.haimen_match_confidence, 100)

        by_address = PermitValidationRecord("x", "x", "普通项目", "建设工程施工许可证", "https://x")
        by_address.project_address = "海门港新区发展大道北侧"
        classify_haimen(by_address)
        self.assertTrue(by_address.haimen_match)
        self.assertEqual(by_address.haimen_match_confidence, 90)

        title_only = PermitValidationRecord("x", "x", "海门项目", "建设工程施工许可证", "https://x")
        classify_haimen(title_only)
        self.assertFalse(title_only.haimen_match)
        self.assertEqual(title_only.haimen_match_confidence, 60)
        self.assertEqual(title_only.validation_status, "待人工核验")

    def test_parses_detail_table_and_keeps_publish_and_permit_dates_separate(self) -> None:
        html = """
        <html><head><meta charset="utf-8" /><meta name="PubDate" content="2026-07-21 10:00" /></head><body>
        <table>
          <tr><th>建设单位</th><td>江苏示例设备有限公司</td></tr>
          <tr><th>项目名称</th><td>智能设备生产基地</td></tr>
          <tr><th>建设地点</th><td>海门区三星镇产业园</td></tr>
          <tr><th>行政区划代码</th><td>320684</td></tr>
          <tr><th>许可证书名称</th><td>建设工程施工许可证</td></tr>
          <tr><th>施工许可编号</th><td>320684202607150101</td></tr>
          <tr><th>发证日期</th><td>2026年7月15日</td></tr>
          <tr><th>发证机关</th><td>南通市海门区行政审批局</td></tr>
        </table></body></html>
        """
        parser = _DetailParser("https://example.test/detail.html")
        parser.feed(html)
        text = "\n".join(("项目施工许可", html))
        fields = _extract_structured_fields(parser.rows, text)
        source = PERMIT_SOURCES[2]
        item = PermitListItem("江苏示例设备有限公司--智能设备生产基地工程施工许可", "2026-07-21", "https://example.test/detail.html")
        record = _build_record(source, item, parser, fields, text)
        classify_haimen(record)

        self.assertEqual(record.company_name, "江苏示例设备有限公司")
        self.assertEqual(record.project_name, "智能设备生产基地")
        self.assertEqual(record.permit_date, "2026-07-15")
        self.assertEqual(record.publish_date, "2026-07-21")
        self.assertEqual(record.district_code, "320684")
        self.assertTrue(record.haimen_match)

    def test_fixed_haimen_column_supplies_authoritative_district_scope(self) -> None:
        html = """
        <html><head><meta name="PubDate" content="2026-07-21" /></head><body>
        <table>
          <tr><th>行政相对人名称</th><td>海门示例建设有限公司</td></tr>
          <tr><th>许可事项名称</th><td>建设用地规划许可证</td></tr>
          <tr><th>许可证书编号</th><td>地字第3206142026YG0047653号</td></tr>
          <tr><th>许可决定日期</th><td>202 6年7月14日</td></tr>
        </table></body></html>
        """
        parser = _DetailParser("https://example.test/detail.html")
        parser.feed(html)
        fields = _extract_structured_fields(parser.rows, html)
        item = PermitListItem("关于同意示例项目的行政许可", "2026-07-21", "https://example.test/detail.html")
        record = _build_record(PERMIT_SOURCES[0], item, parser, fields, html)
        classify_haimen(record)

        self.assertEqual(record.district, "海门区")
        self.assertEqual(record.district_code, "320684")
        self.assertEqual(record.permit_date, "2026-07-14")
        self.assertTrue(record.haimen_match)
        self.assertEqual(record.haimen_match_confidence, 100)

    def test_writes_utf8_validation_csv(self) -> None:
        record = PermitValidationRecord(
            "planning_land",
            "海门区自然资源局行政许可",
            "示例",
            "建设用地规划许可证",
            "https://example.test",
            company_name="示例公司",
            project_name="示例项目",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "permit_validation.csv"
            write_validation_csv(path, [record])
            text = path.read_text(encoding="utf-8-sig")
        self.assertIn("企业名称", text)
        self.assertIn("示例公司", text)


if __name__ == "__main__":
    unittest.main()
