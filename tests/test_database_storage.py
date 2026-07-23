import tempfile
import unittest
from pathlib import Path

from database.storage import count_opportunities, load_opportunities, upsert_opportunities
from data_source.base import OpportunityRecord


class DatabaseStorageTest(unittest.TestCase):
    def test_upserts_and_loads_opportunities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            record = OpportunityRecord(
                enterprise_name="江苏示例自然资源有限公司",
                project_name="建设用地规划许可项目",
                source="江苏自然资源政务信息检索服务",
                event_time="2026-07-21",
                amount="1亿元",
                industry="设备制造",
                region="南通市海门区",
                approval_type="建设用地规划许可证",
                stage="土地/规划审批阶段",
                source_url="https://example.com/nr/a",
                source_title="关于江苏示例自然资源有限公司建设用地规划许可项目",
            ).enrich()

            first = upsert_opportunities(db_path, [record])
            second = upsert_opportunities(db_path, [record])
            loaded = load_opportunities(db_path)

            self.assertEqual(first.inserted_count, 1)
            self.assertEqual(second.inserted_count, 0)
            self.assertEqual(second.updated_count, 1)
            self.assertEqual(count_opportunities(db_path), 1)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].enterprise_name, "江苏示例自然资源有限公司")
            self.assertEqual(loaded[0].opportunity_level, record.opportunity_level)


if __name__ == "__main__":
    unittest.main()
