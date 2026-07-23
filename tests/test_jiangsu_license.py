import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import requests

from database.storage import count_construction_permits, upsert_construction_permits
from data_source.jiangsu_license import (
    ConstructionPermitRecord,
    JiangsuLicenseCrawler,
    calculate_loan_opportunity_score,
    dedupe_license_records,
    extract_permit_type,
    infer_response_format,
    is_recent_license_record,
    level_from_license_score,
    parse_license_detail_html,
    parse_license_search_results,
    stage_for_permit,
)


class JiangsuLicenseTest(unittest.TestCase):
    @staticmethod
    def build_response(status_code: int, text: str, url: str) -> requests.Response:
        response = requests.Response()
        response.status_code = status_code
        response.url = url
        response.headers["Content-Type"] = "text/html;charset=GBK"
        response.encoding = "gbk"
        response._content = text.encode("gbk")
        return response

    def test_extracts_permit_type_and_stage(self):
        text = "许可证书名称 建设工程施工许可证 许可编号 320684202607210101"
        self.assertEqual(extract_permit_type(text), "建设工程施工许可证")
        self.assertEqual(stage_for_permit("建设用地规划许可证"), "拿地规划")
        self.assertEqual(stage_for_permit("建设工程规划许可证"), "建设审批")
        self.assertEqual(stage_for_permit("建设工程施工许可证"), "开工建设")

    def test_loan_score_rules(self):
        self.assertEqual(calculate_loan_opportunity_score("建设工程施工许可证", "1.2亿元", "2026-07-20"), 80)
        self.assertEqual(calculate_loan_opportunity_score("建设工程规划许可证", "6000万元", "2026-07-20"), 60)
        self.assertEqual(calculate_loan_opportunity_score("建设用地规划许可证", "未披露", "2025-01-01"), 25)
        self.assertEqual(level_from_license_score(80), "A")
        self.assertEqual(level_from_license_score(45), "B")
        self.assertEqual(level_from_license_score(25), "C")

    def test_builds_real_search_interface_params(self):
        crawler = JiangsuLicenseCrawler()
        params = crawler.build_search_params("建设工程施工许可证")

        self.assertEqual(crawler.search_url, "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action")
        self.assertEqual(params["catalogID"], "2c90825471c8dd7a0171c90aec380001")
        self.assertEqual(params["type"], "1")
        self.assertEqual(params["title"], "建设工程施工许可证")

    def test_warms_session_then_searches_with_browser_headers_and_20_second_timeout(self):
        crawler = JiangsuLicenseCrawler(request_interval_seconds=0)
        crawler.session = Mock()
        crawler.session.get.side_effect = [
            self.build_response(200, "<html>首页</html>", crawler.homepage_url),
            self.build_response(200, "<html>搜索结果</html>", crawler.search_url),
        ]

        crawler.search_keyword("建设工程施工许可证")

        self.assertEqual(crawler.session.get.call_count, 2)
        homepage_args, search_args = crawler.session.get.call_args_list
        self.assertEqual(homepage_args.args[0], "https://zrzy.jiangsu.gov.cn/")
        self.assertEqual(homepage_args.kwargs["timeout"], 20)
        self.assertIn("catalogID=2c90825471c8dd7a0171c90aec380001", search_args.args[0])
        self.assertIn("type=1", search_args.args[0])
        self.assertEqual(search_args.kwargs["timeout"], 20)
        self.assertEqual(
            search_args.kwargs["headers"]["User-Agent"],
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        )
        self.assertEqual(search_args.kwargs["headers"]["Referer"], "https://zrzy.jiangsu.gov.cn/")
        self.assertEqual(
            search_args.kwargs["headers"]["Accept"],
            "text/html,application/xhtml+xml,application/xml",
        )

    def test_prints_403_response_debug_information(self):
        crawler = JiangsuLicenseCrawler(request_interval_seconds=0)
        crawler.session = Mock()
        crawler.session.get.side_effect = [
            self.build_response(200, "<html>首页</html>", crawler.homepage_url),
            self.build_response(403, "拒绝访问-调试正文", crawler.search_url),
        ]
        output = StringIO()

        with redirect_stdout(output):
            result = crawler.search_keyword("建设工程施工许可证")

        debug_output = output.getvalue()
        self.assertEqual(result.status_code, 403)
        self.assertIn("HTTP 403 response.headers", debug_output)
        self.assertIn("拒绝访问-调试正文", debug_output)

    def test_filters_license_candidates_from_html_search_result(self):
        crawler = JiangsuLicenseCrawler()
        html = """
        <ul>
          <li><a href="/gtxxgk/nrglIndex.action?id=abc">建设工程施工许可证 海门厂房项目</a>2026-07-20</li>
          <li><a href="/index.html">网站首页</a></li>
        </ul>
        """
        candidates = crawler.extract_candidates(html, crawler.search_url)
        filtered = crawler.filter_search_result_candidates(candidates, "建设工程施工许可证")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].title, "建设工程施工许可证 海门厂房项目")
        self.assertEqual(filtered[0].date, "2026-07-20")

    def test_parses_real_nlist_result_structure(self):
        html = """
        <table>
          <tr><td height="40" class="nlist">
            <a title="南通市海门区建设项目" href="
              /gtxxgk/nrglIndex.action?type=2&amp;messageID=abc123
            ">南通市海门区建设项目</a>
            <span>2026-07-20</span>
          </td></tr>
          <tr><td><a href="/">首页</a></td></tr>
        </table>
        """

        records = parse_license_search_results(html, "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "南通市海门区建设项目")
        self.assertEqual(records[0].date, "2026-07-20")
        self.assertEqual(
            records[0].url,
            "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action?type=2&messageID=abc123",
        )

    def test_infers_search_response_format(self):
        self.assertEqual(infer_response_format("<html><body>结果</body></html>", "text/html"), "HTML")
        self.assertEqual(infer_response_format('{"items":[]}', "application/json"), "JSON")

    def test_parses_structured_license_detail_html(self):
        html = """
        <html><body><table>
          <tr><th>行政相对人名称</th><td>江苏海门新能源有限公司</td></tr>
          <tr><th>项目名称</th><td>新能源设备生产基地</td></tr>
          <tr><th>建设地点</th><td>南通市海门区三星镇项目路8号</td></tr>
          <tr><th>许可证书名称</th><td>建设工程施工许可证</td></tr>
          <tr><th>行政许可决定文书号</th><td>320684202607210101</td></tr>
          <tr><th>许可决定日期</th><td>2026年7月21日</td></tr>
          <tr><th>项目总投资</th><td>1.2亿元</td></tr>
        </table></body></html>
        """
        record = parse_license_detail_html(
            html,
            title="新能源设备生产基地建设工程施工许可证",
            source_url="https://zrzy.jiangsu.gov.cn/example",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.company_name, "江苏海门新能源有限公司")
        self.assertEqual(record.construction_unit, "江苏海门新能源有限公司")
        self.assertEqual(record.project_name, "新能源设备生产基地")
        self.assertEqual(record.project_address, "南通市海门区三星镇项目路8号")
        self.assertEqual(record.permit_type, "建设工程施工许可证")
        self.assertEqual(record.permit_number, "320684202607210101")
        self.assertEqual(record.permit_date, "2026-07-21")
        self.assertEqual(record.investment_amount, "1.2亿元")

    def test_filters_records_to_latest_30_days(self):
        current_day = date(2026, 7, 21)
        within_7_days = ConstructionPermitRecord(permit_date="2026-07-14")
        within_30_days = ConstructionPermitRecord(permit_date="2026-06-21")
        too_old = ConstructionPermitRecord(permit_date="2026-06-20")

        self.assertTrue(is_recent_license_record(within_7_days, today=current_day))
        self.assertTrue(is_recent_license_record(within_30_days, today=current_day))
        self.assertFalse(is_recent_license_record(too_old, today=current_day))

    def test_dedupes_by_company_and_permit_number(self):
        first = ConstructionPermitRecord(
            company_name="江苏海门新能源有限公司",
            permit_number="320684202607210101",
            project_name="项目一期",
            source_url="https://example.com/one",
        )
        duplicate = ConstructionPermitRecord(
            company_name="江苏海门新能源有限公司",
            permit_number="320684202607210101",
            project_name="项目一期（更新）",
            source_url="https://example.com/two",
        )

        self.assertEqual(len(dedupe_license_records([first, duplicate])), 1)

    def test_upserts_construction_permits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            record = ConstructionPermitRecord(
                permit_type="建设工程施工许可证",
                company_name="江苏示例建设有限公司",
                project_name="示例厂房建设项目",
                project_address="南通市海门区示例路1号",
                construction_unit="江苏示例建设有限公司",
                permit_date="2026-07-20",
                permit_number="320684202607200101",
                project_scale="12000平方米",
                investment_amount="1.2亿元",
                industry="设备制造",
                source_url="https://example.com/permit",
                update_time="2026-07-20",
            ).enrich()

            first = upsert_construction_permits(db_path, [record])
            duplicate = ConstructionPermitRecord(
                **{
                    **record.__dict__,
                    "project_name": "同一许可证的更新标题",
                    "source_url": "https://example.com/permit-updated",
                }
            )
            second = upsert_construction_permits(db_path, [duplicate])

            self.assertEqual(first.inserted_count, 1)
            self.assertEqual(second.inserted_count, 0)
            self.assertEqual(second.updated_count, 1)
            self.assertEqual(count_construction_permits(db_path), 1)


if __name__ == "__main__":
    unittest.main()
