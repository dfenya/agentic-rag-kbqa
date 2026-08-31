import unittest

from app.core.paths import kb_storage_folder, safe_filename


class SafePathTests(unittest.TestCase):
    def test_upload_filename_cannot_escape_temp_directory(self):
        self.assertEqual(safe_filename("../../合同:终稿.pdf"), "合同_终稿.pdf")
        self.assertEqual(safe_filename(r"C:\fakepath\报告.pdf"), "报告.pdf")

    def test_knowledge_base_folder_contains_no_path_separator(self):
        folder = kb_storage_folder("../../法务/合同", "kb-id")
        self.assertNotIn("/", folder)
        self.assertNotIn("\\", folder)
        self.assertTrue(folder.endswith("_kb-id"))


if __name__ == "__main__":
    unittest.main()
