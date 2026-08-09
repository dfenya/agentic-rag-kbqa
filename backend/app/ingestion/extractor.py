"""PDF 转 Markdown，基于 pymupdf4llm"""

import os
from pathlib import Path

import pymupdf
import pymupdf4llm

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def pdf_to_markdown(pdf_path: str | Path, output_dir: str | Path) -> Path:
    """单个 PDF 转 Markdown，返回输出文件路径"""
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_path))
    md = pymupdf4llm.to_markdown(
        doc,
        header=False,
        footer=False,
        page_separators=True,
        ignore_images=True,
        write_images=False,
        image_path=None,
    )
    md_cleaned = md.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")
    output_path = output_dir / f"{pdf_path.stem}.md"
    output_path.write_bytes(md_cleaned.encode("utf-8"))
    doc.close()
    return output_path
