from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.region_permit_summary import load_region_permit_summary
from crawler.import_regional_permits import import_regional_permits
from data_source.regional_permit_import import (
    RegionalPermitImportError,
    load_verified_import_records,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = PROJECT_ROOT / "database" / "enterprise.db"
REGIONS = PROJECT_ROOT / "config" / "regions.json"
SOURCES = PROJECT_ROOT / "config" / "regional_permit_sources.json"
IMPORT_FILE = (
    PROJECT_ROOT / "data" / "region_imports" / "phase3_14_verified_permits.json"
)
MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "013_regional_permit_sources.py"
)
LEGACY_COLUMNS = (
    "id", "record_hash", "company_name", "project_name", "permit_type",
    "permit_date", "address", "construction_unit", "permit_number",
    "publish_date", "district", "district_code", "province", "city",
    "region_key", "area_code", "source_url",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("phase314_migration", MIGRATION)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load phase 3.14 migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _haimen_snapshot(db_path: Path) -> tuple[int, str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            f"SELECT {', '.join(LEGACY_COLUMNS)} FROM construction_permits "
            "WHERE region_key='320684' ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return len(rows), hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Phase314RegionalImportTest(unittest.TestCase):
    def test_migration_and_verified_import_are_idempotent_and_preserve_haimen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            shutil.copy2(PRODUCTION_DB, db_path)
            connection = sqlite3.connect(db_path)
            try:
                with connection:
                    connection.execute(
                        "DELETE FROM construction_permits WHERE region_key <> '320684'"
                    )
            finally:
                connection.close()
            before = _haimen_snapshot(db_path)

            migration = _load_migration()
            first_migration = migration.migrate(db_path)
            second_migration = migration.migrate(db_path)
            self.assertEqual(first_migration["schema_version"], 13)
            self.assertEqual(second_migration["schema_version"], 13)
            self.assertEqual(_haimen_snapshot(db_path), before)

            first = import_regional_permits(db_path=db_path)
            second = import_regional_permits(db_path=db_path)
            self.assertEqual(first["inserted_count"], 11)
            self.assertEqual(second["inserted_count"], 0)
            self.assertEqual(second["skipped_count"], 11)
            self.assertEqual(_haimen_snapshot(db_path), before)

            connection = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(construction_permits)"
                    )
                }
                counts = dict(
                    connection.execute(
                        "SELECT region_key, COUNT(*) FROM construction_permits "
                        "GROUP BY region_key"
                    ).fetchall()
                )
                source_rows = connection.execute(
                    "SELECT COUNT(*) FROM construction_permits "
                    "WHERE region_key <> '320684' "
                    "AND source_region <> '' AND source_time <> ''"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertTrue({"source_region", "source_time"}.issubset(columns))
            self.assertEqual(counts["320684"], 225)
            self.assertEqual(counts["320115"], 2)
            self.assertEqual(counts["320116"], 2)
            self.assertEqual(counts["320509"], 5)
            self.assertEqual(counts["320613"], 2)
            self.assertEqual(source_rows, 11)

            summary = load_region_permit_summary(db_path, REGIONS)
            self.assertEqual(summary.province_total, 236)
            self.assertEqual(summary.city_count("南京市"), 4)
            self.assertEqual(summary.city_count("苏州市"), 5)
            self.assertEqual(summary.city_count("南通市"), 227)

    def test_import_rejects_protected_haimen_and_unverified_domains(self):
        payload = json.loads(IMPORT_FILE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.json"

            haimen_item = dict(payload["items"][0])
            haimen_item.update(
                region_key="320684",
                source_region="江苏省/南通市/海门区",
            )
            path.write_text(
                json.dumps({"items": [haimen_item]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RegionalPermitImportError):
                load_verified_import_records(
                    path,
                    region_config_path=REGIONS,
                    source_config_path=SOURCES,
                )

            domain_item = dict(payload["items"][0])
            domain_item["source_url"] = "https://example.com/fake"
            path.write_text(
                json.dumps({"items": [domain_item]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RegionalPermitImportError):
                load_verified_import_records(
                    path,
                    region_config_path=REGIONS,
                    source_config_path=SOURCES,
                )


if __name__ == "__main__":
    unittest.main()
