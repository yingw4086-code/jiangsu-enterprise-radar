import tempfile
import unittest
import zipfile
from pathlib import Path

from app.exporters.excel_writer import write_xlsx


class ExcelWriterTest(unittest.TestCase):
    def test_writes_xlsx_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "out.xlsx"
            write_xlsx(path, ["企业名称", "链接"], [["江苏海门示例装备有限公司", "https://example.com"]])

            self.assertTrue(path.exists())
            with zipfile.ZipFile(path) as workbook:
                self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
                sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn("江苏海门示例装备有限公司", sheet)


if __name__ == "__main__":
    unittest.main()

