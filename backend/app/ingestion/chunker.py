"""文档分块器：Markdown 预处理 → 标题切分 → 合并小父块 → 拆大父块 → 递归子块"""

from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


# 中文文档标题模式
HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3"),
    (r"^第[一二三四五六七八九十百千0-9０-９]+条", "Article"),
    (r"^第[一二三四五六七八九十百千0-9]+[编章节]", "Division"),
    (r"^\d+(\.\d+)*\s+", "Numbered H"),
]


class DocumentChunker:
    """把 Markdown 文档拆成父子块对"""

    def __init__(
        self,
        min_parent_size: int = 600,
        max_parent_size: int = 4000,
        child_chunk_size: int = 500,
        child_chunk_overlap: int = 100,
    ):
        self._parent_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS_TO_SPLIT_ON,
            strip_headers=False,
        )
        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_chunk_overlap,
        )
        self._min_parent_size = min_parent_size
        self._max_parent_size = max_parent_size

    def chunk_file(
        self,
        md_path: Path,
        doc_id: str,
        source_name: str,
        sha256: str = "",
        kb_id: str | None = None,
    ) -> Tuple[List[tuple], List[Document]]:
        """处理一个 Markdown 文件，返回 (parent_pairs, child_docs)"""
        content = md_path.read_text(encoding="utf-8")
        processed = self._preprocess(content)
        md_path.write_text(processed, encoding="utf-8")

        parent_docs = self._parent_splitter.split_text(processed)
        merged = self._merge_small_parents(parent_docs)
        split_parents = self._split_large_parents(merged)
        cleaned = self._clean_small(split_parents)

        all_parents: List[tuple] = []
        all_children: List[Document] = []
        self._create_children(all_parents, all_children, cleaned, doc_id, source_name, sha256, kb_id=kb_id)
        return all_parents, all_children

    def _preprocess(self, content: str) -> str:
        """修复 PDF 转换产生的 Markdown 格式问题"""
        import re

        lines = content.split("\n")
        processed: list[str] = []

        for line in lines:
            if not line.strip():
                processed.append(line)
                continue

            for prefix, marker in [
                (r"^(\s*)-\s*(\d+)\s+(.+)$", "#"),
                (r"^(\s*)-\s*(\d+\.\d+)\s+(.+)$", "##"),
                (r"^(\s*)-\s*(\d+\.\d+\.\d+)\s+(.+)$", "###"),
            ]:
                m = re.match(prefix, line)
                if m:
                    indent, number, text = m.groups()
                    processed.append(f"{indent}{marker} {number} {text}")
                    break
            else:
                m = re.match(r'^(\s*)##\s+(\d+)\s+(.+)$', line)
                if m:
                    indent, number, text = m.groups()
                    processed.append(f"{indent}# {number} {text}")
                    continue

                m = re.match(r'^(\s*)##\s+(\d+\.\d+)\s+(.+)$', line)
                if m:
                    indent, number, text = m.groups()
                    processed.append(f"{indent}## {number} {text}")
                    continue

                processed.append(line)

        return "\n".join(processed)

    def _merge_small_parents(self, chunks: List[Document]) -> List[Document]:
        if not chunks:
            return []
        merged, current = [], None
        for chunk in chunks:
            if current is None:
                current = chunk
            else:
                current.page_content += "\n\n" + chunk.page_content
                for k, v in chunk.metadata.items():
                    current.metadata[k] = (
                        f"{current.metadata[k]} -> {v}"
                        if k in current.metadata
                        else v
                    )
            if len(current.page_content) >= self._min_parent_size:
                merged.append(current)
                current = None
        if current:
            if merged:
                merged[-1].page_content += "\n\n" + current.page_content
                for k, v in current.metadata.items():
                    merged[-1].metadata[k] = (
                        f"{merged[-1].metadata[k]} -> {v}"
                        if k in merged[-1].metadata
                        else v
                    )
            else:
                merged.append(current)
        return merged

    def _split_large_parents(self, chunks: List[Document]) -> List[Document]:
        split_chunks = []
        for chunk in chunks:
            if len(chunk.page_content) <= self._max_parent_size:
                split_chunks.append(chunk)
            else:
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self._max_parent_size,
                    chunk_overlap=100,
                )
                sub = splitter.split_documents([chunk])
                split_chunks.extend(sub)
        return split_chunks

    def _clean_small(self, chunks: List[Document]) -> List[Document]:
        cleaned = []
        for i, chunk in enumerate(chunks):
            if len(chunk.page_content) < self._min_parent_size:
                if cleaned:
                    cleaned[-1].page_content += "\n\n" + chunk.page_content
                    for k, v in chunk.metadata.items():
                        cleaned[-1].metadata[k] = (
                            f"{cleaned[-1].metadata[k]} -> {v}"
                            if k in cleaned[-1].metadata
                            else v
                        )
                elif i < len(chunks) - 1:
                    chunks[i + 1].page_content = (
                        chunk.page_content + "\n\n" + chunks[i + 1].page_content
                    )
                    for k, v in chunk.metadata.items():
                        chunks[i + 1].metadata[k] = (
                            f"{v} -> {chunks[i + 1].metadata[k]}"
                            if k in chunks[i + 1].metadata
                            else v
                        )
                else:
                    cleaned.append(chunk)
            else:
                cleaned.append(chunk)
        return cleaned

    def _create_children(
        self,
        all_parents: List[tuple],
        all_children: List[Document],
        parent_docs: List[Document],
        doc_id: str,
        source_name: str,
        sha256: str,
        kb_id: str | None = None,
    ):
        for i, p_doc in enumerate(parent_docs):
            parent_id = f"{doc_id}:p{i}"
            p_doc.metadata.update({
                "source": source_name,
                "parent_id": parent_id,
                "doc_id": doc_id,
                "kb_id": kb_id or "",
                "sha256": sha256,
            })
            all_parents.append((parent_id, p_doc))
            children = self._child_splitter.split_documents([p_doc])
            for child in children:
                child.metadata.update({
                    "parent_id": parent_id,
                    "doc_id": doc_id,
                    "kb_id": kb_id or "",
                    "source": source_name,
                    "sha256": sha256,
                })
            all_children.extend(children)
