from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.export_cloud_data import PUBLIC_FIELDS, export_cloud_data
from database.storage import upsert_planning_construction_permits
from tests.test_planning_permit_storage import permit_record


class CloudExportTest(unittest.TestCase):
    def test_exports_only_public_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            output_path = root / "planning_construction_permits.json"
            upsert_planning_construction_permits(db_path, [permit_record()])

            result = export_cloud_data(db_path, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(result["export_count"], 1)
            self.assertTrue(result["written"])
            self.assertIsInstance(payload, list)
            self.assertEqual(tuple(payload[0].keys()), PUBLIC_FIELDS)
            serialized = json.dumps(payload, ensure_ascii=False).lower()
            self.assertNotIn("api_key", serialized)
            self.assertNotIn("cookie", serialized)
            self.assertNotIn(str(root).lower(), serialized)

    def test_empty_database_does_not_create_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "planning_construction_permits.json"

            result = export_cloud_data(root / "enterprise.db", output_path)

            self.assertFalse(result["written"])
            self.assertEqual(result["export_count"], 0)
            self.assertFalse(output_path.exists())

    def test_empty_database_does_not_overwrite_old_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "planning_construction_permits.json"
            output_path.write_text('[{"existing": true}]', encoding="utf-8")

            result = export_cloud_data(root / "enterprise.db", output_path)

            self.assertFalse(result["written"])
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                '[{"existing": true}]',
            )


if __name__ == "__main__":
    unittest.main()
