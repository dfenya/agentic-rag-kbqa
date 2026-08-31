import unittest

from langchain_core.documents import Document

from app.ingestion.chunker import DocumentChunker


class DocumentChunkerTests(unittest.TestCase):
    def test_normalizes_legal_and_numbered_headings_to_markdown(self):
        chunker = DocumentChunker()
        result = chunker._preprocess(
            "第一章 总则\n第一条 适用范围\n1.2 二级标题\n普通正文"
        )

        self.assertIn("# 第一章 总则", result)
        self.assertIn("## 第一条 适用范围", result)
        self.assertIn("## 1.2 二级标题", result)

    def test_large_parent_split_never_remerges_small_tail(self):
        chunker = DocumentChunker(min_parent_size=10, max_parent_size=30)
        chunks = chunker._split_large_parents([Document(page_content="甲" * 65)])

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.page_content) <= 30 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
