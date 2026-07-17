import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from app.main import run_once


class SamplePipelineTest(unittest.TestCase):
    def test_sample_site_generates_excel(self):
        project_root = Path(__file__).resolve().parents[1]
        list_url = (project_root / "samples" / "haimen_list.html").as_uri()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "sites.json"
            config_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "本地样本站点",
                            "base_url": list_url,
                            "list_urls": [list_url],
                            "keywords": ["备案", "规划许可证"],
                            "max_items": 10,
                            "enabled": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_dir = temp_path / "excel"
            state_path = temp_path / "state" / "seen_links.json"

            output = run_once(
                Namespace(
                    config=str(config_path),
                    output_dir=str(output_dir),
                    state_path=str(state_path),
                    include_seen=False,
                )
            )

            self.assertTrue(output.exists())
            self.assertTrue(state_path.exists())

    def test_with_ai_no_rows_writes_empty_json_without_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "sites.json"
            config_path.write_text("[]", encoding="utf-8")
            output_dir = temp_path / "excel"
            ai_output_dir = temp_path / "ai"
            state_path = temp_path / "state" / "seen_links.json"

            output = run_once(
                Namespace(
                    config=str(config_path),
                    output_dir=str(output_dir),
                    ai_output_dir=str(ai_output_dir),
                    state_path=str(state_path),
                    include_seen=False,
                    with_ai=True,
                )
            )

            self.assertTrue(output.exists())
            ai_files = list(ai_output_dir.glob("financing_analysis_*.json"))
            self.assertEqual(len(ai_files), 1)
            result = json.loads(ai_files[0].read_text(encoding="utf-8-sig"))
            self.assertEqual(result["items"], [])
            self.assertEqual(result["model"], "not_called_no_new_items")


if __name__ == "__main__":
    unittest.main()
