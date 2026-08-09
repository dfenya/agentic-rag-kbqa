"""PDF 转 Markdown，通过 HTTP 调用 mineru-api 服务

配置项在 config/mineru.yml，修改后重启生效。

直接运行测试：
  python -m app.ingestion.extractor input.pdf [output_dir]
"""

import sys
from pathlib import Path
import yaml
import httpx


def _load_config() -> dict:
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "mineru.yml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["mineru"]


async def pdf_to_markdown(pdf_path: str | Path, output_dir: str | Path) -> Path:
    """异步版本，供 FastAPI 调用，不阻塞事件循环"""
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_config()
    url = f"http://{cfg['host']}:{cfg['port']}/file_parse"

    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        with open(pdf_path, "rb") as f:
            resp = await client.post(url,
                files={"files": (pdf_path.name, f, "application/pdf")},
                data=cfg["request"])
            resp.raise_for_status()
            body = resp.json()

    results = body.get("results", {})
    if not results:
        raise RuntimeError("mineru-api 返回空结果")

    first = next(iter(results.values()))
    md_content = first.get("md_content", "")
    if not md_content:
        raise RuntimeError("mineru-api 返回空内容")

    md_path = output_dir / f"{pdf_path.stem}.md"
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


def pdf_to_markdown_sync(pdf_path: str | Path, output_dir: str | Path) -> Path:
    """同步版本，供直接运行测试用"""
    import asyncio
    return asyncio.run(pdf_to_markdown(pdf_path, output_dir))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m app.ingestion.extractor <pdf_path> [output_dir]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    result = pdf_to_markdown_sync(pdf_path, output_dir)
    print(f"输出: {result}")
