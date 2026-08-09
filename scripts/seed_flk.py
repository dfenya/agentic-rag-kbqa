#!/usr/bin/env python3
"""批量导入 PDF 文件到知识库

Usage:
    python scripts/seed_flk.py /path/to/pdfs/

指向一个包含 PDF 文件的目录，脚本会逐个上传到后端。
需要后端在 http://localhost:8000 运行。
"""

import asyncio
import sys
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api/v1"


async def upload_file(client: httpx.AsyncClient, filepath: Path) -> dict:
    """上传单个 PDF"""
    with open(filepath, "rb") as f:
        files = {"files": (filepath.name, f, "application/pdf")}
        resp = await client.post(f"{API_BASE}/documents", files=files)
        resp.raise_for_status()
        data = resp.json()

    upload_id = data["upload_id"]
    tasks = data.get("tasks", [])
    print(f"  Uploaded: {filepath.name} → upload_id={upload_id}, tasks={len(tasks)}")
    return {"upload_id": upload_id, "tasks": tasks, "filename": filepath.name}


async def main(pdf_dir: str):
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.is_dir():
        print(f"Error: {pdf_dir} is not a directory")
        sys.exit(1)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}")
        sys.exit(0)

    print(f"Found {len(pdfs)} PDF(s) in {pdf_dir}\n")

    async with httpx.AsyncClient(timeout=300) as client:
        results = []
        for pdf in pdfs:
            try:
                result = await upload_file(client, pdf)
                results.append(result)
            except Exception as e:
                print(f"  ✗ Failed: {pdf.name} — {e}")
                results.append({"filename": pdf.name, "error": str(e)})

        print(f"\n{'='*50}")
        print(f"Done. {len(results)} file(s) processed.")
        success = sum(1 for r in results if "upload_id" in r)
        print(f"  Success: {success}")
        print(f"  Failed:  {len(results) - success}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} /path/to/pdfs/")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
