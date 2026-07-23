import unittest
from unittest.mock import Mock

from data_source.planning_construction_permit import (
    HAIMEN_PUBLISHER,
    SEARCH_API_URL,
    SEARCH_AREA_CODE,
    SEARCH_KEYWORD,
    PlanningSearchItem,
    PlanningConstructionPermitCrawler,
    confirm_haimen,
    is_planning_construction_result,
    parse_ocr_fields,
    parse_search_page,
    parse_title_entities,
    normalize_permit_number,
    plausible_issuing_authority,
)


class PlanningConstructionPermitTest(unittest.TestCase):
    def test_matches_official_first_page_form_parameter(self):
        crawler = PlanningConstructionPermitCrawler(enable_ocr=False)

        self.assertEqual(crawler.build_request_params(1)["page"], "")
        self.assertEqual(crawler.build_request_params(2)["page"], "2")
        self.assertEqual(crawler.build_request_params(1)["fieldType"], "0")
        self.assertEqual(crawler.build_request_params(1)["type"], "")

    def test_initializes_browser_like_session_before_list_request(self):
        crawler = PlanningConstructionPermitCrawler(request_interval_seconds=1.0, enable_ocr=False)
        crawler._wait_for_rate_limit = Mock()
        crawler.session = Mock()
        index_response = Mock()
        index_response.raise_for_status = Mock()
        list_response = Mock()
        list_response.raise_for_status = Mock()
        list_response.encoding = "UTF-8"
        list_response.text = '<script>new Pagination({pageSize: "10", total: "0"});</script>'
        crawler.session.get.side_effect = [index_response, list_response]

        crawler.fetch_search_page(1)

        self.assertEqual(crawler.session.get.call_count, 2)
        self.assertIn("/elsearch/search/index", crawler.session.get.call_args_list[0].args[0])
        self.assertEqual(crawler.session.get.call_args_list[1].args[0], SEARCH_API_URL)
        self.assertNotIn("Cookie", crawler.session.get.call_args_list[1].kwargs["headers"])

    def test_parses_real_search_result_shape_and_total(self):
        html = """
        <ul class="item">
          <li>
            <a href="http://zrzy.jiangsu.gov.cn/nthm/gtzx/ghgs/jsxmphgb/202607/example.htm">
              <div class="item-title"><span class="sign">要闻动态</span>
                冬泽特医食品生产基地新建项目<span>建设工程规划许可证</span>批后公布
              </div>
            </a>
            <div class="item-content"></div>
            <div class="item-time">南通市海门自然资源和规划局 2026-07-17</div>
          </li>
        </ul>
        <script>new Pagination({pageSize: "10", total: "211"});</script>
        """

        page = parse_search_page(html)

        self.assertEqual(page.total_count, 211)
        self.assertEqual(page.page_size, 10)
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].title, "冬泽特医食品生产基地新建项目建设工程规划许可证批后公布")
        self.assertEqual(page.items[0].publisher, HAIMEN_PUBLISHER)
        self.assertEqual(page.items[0].publish_date, "2026-07-17")

    def test_area_code_confirms_haimen_without_title_keyword(self):
        item = PlanningSearchItem(
            title="立新小区九期建设工程规划许可证批后公布",
            publish_date="2026-07-15",
            publisher=HAIMEN_PUBLISHER,
            detail_url="http://zrzy.jiangsu.gov.cn/nthm/gtzx/ghgs/jsxmphgb/example.htm",
        )

        confirmed, confidence, reason = confirm_haimen(item, SEARCH_AREA_CODE)

        self.assertTrue(confirmed)
        self.assertEqual(confidence, 100)
        self.assertIn("areaCode=320684", reason)

    def test_rejects_policy_article_even_if_body_keyword_would_match(self):
        item = PlanningSearchItem(
            title="《江苏省城乡规划条例》解读",
            publish_date="2016-12-10",
            publisher=HAIMEN_PUBLISHER,
            detail_url="http://zrzy.jiangsu.gov.cn/gtapp/nrglIndex.action?type=2&messageID=example",
            category="政策文件",
        )

        valid, reason = is_planning_construction_result(item)

        self.assertFalse(valid)
        self.assertIn("标题不是", reason)

    def test_accepts_target_column_result(self):
        item = PlanningSearchItem(
            title="平谦现代产业园（南通海门）有限公司-开闭所02建设工程规划许可证批后公布",
            publish_date="2026-07-21",
            publisher=HAIMEN_PUBLISHER,
            detail_url="http://zrzy.jiangsu.gov.cn/nthm/gtzx/ghgs/jsxmphgb/202607/example.htm",
            category="要闻动态",
        )

        valid, reason = is_planning_construction_result(item)

        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_extracts_company_and_project_from_title(self):
        company, project = parse_title_entities(
            "平谦现代产业园（南通海门）有限公司-开闭所02建设工程规划许可证批后公布"
        )

        self.assertEqual(company, "平谦现代产业园（南通海门）有限公司")
        self.assertEqual(project, "平谦现代产业园（南通海门）有限公司-开闭所02")

    def test_extracts_structured_fields_from_local_ocr_text(self):
        text = """
        建设单位：平谦现代产业园（南通海门）有限公司
        项目名称：平谦现代产业园（南通海门）有限公司-开闭所02
        建设位置：海门街道富江北路1600号
        许可证号：建字第3206142026GG0051651号
        发证日期：
        2026年7月20日
        """

        fields = parse_ocr_fields(text)

        self.assertEqual(fields["construction_unit"], "平谦现代产业园（南通海门）有限公司")
        self.assertEqual(fields["project_address"], "海门街道富江北路1600号")
        self.assertEqual(fields["permit_number"], "建字第3206142026GG0051651号")
        self.assertEqual(fields["issue_date"], "2026-07-20")
        self.assertEqual(SEARCH_KEYWORD, "建设工程规划许可证")

    def test_rejects_truncated_permit_number_and_ocr_noise(self):
        self.assertEqual(normalize_permit_number("建字第3206142026GG0"), "未披露")
        self.assertFalse(plausible_issuing_authority("本证限件出业证与本证者兴注"))

    def test_oversized_ocr_image_does_not_abort_batch(self):
        crawler = PlanningConstructionPermitCrawler(enable_ocr=True)
        crawler._wait_for_rate_limit = Mock()
        crawler._ocr_engine = Mock(side_effect=RuntimeError("image too large"))
        response = Mock()
        response.content = b"image"
        response.raise_for_status = Mock()
        crawler.session = Mock()
        crawler.session.get.return_value = response

        text = crawler._ocr_image("https://example.test/permit.jpg", "https://example.test/detail")

        self.assertEqual(text, "")
        self.assertTrue(any("image too large" in error for error in crawler.errors))


if __name__ == "__main__":
    unittest.main()
