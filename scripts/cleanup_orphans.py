"""孤儿向量清理脚本（正式入口，不用只读直接碰 Qdrant 存储文件，避免锁冲突）。

Dry-run:
  python scripts/cleanup_orphans.py

实际删除：
  python scripts/cleanup_orphans.py --apply

清理规则：
1. 遍历 child_chunks 全部点，若 payload.metadata.doc_id 不在 SQLite documents 表中 → 孤儿子块
2. 遍历 parent_chunks 全部点，同理 → 孤儿父块
3. 对 long_term_memory 同法：id 不在 SQLite memories 表中 → 孤儿记忆向量
"""
import sys
import argparse
from collections import Counter

# 把 backend 加入 path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import structlog
from app.core.config import get_settings
from app.core.container import Container

log = structlog.get_logger()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行删除（默认只 dry-run）")
    args = ap.parse_args()

    settings = get_settings()
    container = Container(settings)

    # 手动初始化必要部分（跳过 graph 编译，省 Ollama）
    container.sqlite = __import__("app.stores.sqlite_store", fromlist=["SqliteStore"]).SqliteStore(settings.storage.sqlite_path)
    container.sqlite.create_all()
    container.qdrant = __import__("app.stores.qdrant_store", fromlist=["QdrantStore"]).QdrantStore(settings)
    container.qdrant.init()
    container.parent = __import__("app.stores.parent_store", fromlist=["ParentStore"]).ParentStore(container.qdrant.client)
    container.long_term_memory_store = __import__("app.stores.long_term_memory_store", fromlist=["LongTermMemoryStore"]).LongTermMemoryStore(settings)
    container.long_term_memory_store.init(container.qdrant.client, container.qdrant._dense)

    apply = args.apply
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== 清理模式: {mode} ===")

    # ── 1. 拿现存 doc_id / mem_id 白名单 ──
    docs, total_docs = container.sqlite.docs_list(page=1, page_size=1_000_000)
    valid_doc_ids = {d.id for d in docs}
    valid_kb_ids = {kb.id for kb in container.sqlite.kb_list()}
    mems = container.sqlite.mem_all()
    valid_mem_ids = {m.id for m in mems}
    print(f"现存 doc_id: {len(valid_doc_ids)}, kb_id: {len(valid_kb_ids)}, mem_id: {len(valid_mem_ids)}")

    # ── 2. 扫 child_chunks → 找孤儿子块 ──
    child_client = container.qdrant.client
    child_coll = container.qdrant.COLLECTION_NAME
    if container.qdrant.collection_exists():
        orphans_doc = []       # doc_id 非法的
        orphans_kb = []        # kb_id 非法的（doc_id 合法但 doc 不在对应 KB）
        sources_before = Counter()
        offset = None
        while True:
            points, offset = child_client.scroll(
                collection_name=child_coll,
                limit=5_000,
                offset=offset,
                with_payload=True,
            )
            for p in points:
                meta = (p.payload or {}).get("metadata", {}) or {}
                src = meta.get("source", "")
                if src:
                    sources_before[src] += 1
                doc_id = meta.get("doc_id", "")
                kb_id = meta.get("kb_id")
                if not doc_id or doc_id not in valid_doc_ids:
                    orphans_doc.append((p.id, doc_id, src))
                    continue
                if kb_id and kb_id not in valid_kb_ids:
                    orphans_kb.append((p.id, doc_id, kb_id, src))
            if offset is None or not points:
                break
        print(f"\n[child_chunks] 孤儿( doc_id 不存在 ): {len(orphans_doc)}")
        print(f"[child_chunks] 孤儿( kb_id 不存在 ): {len(orphans_kb)}")
        print(f"[child_chunks] source 分布: {dict(sources_before.most_common(10))}")
        orphan_child_ids = [p[0] for p in orphans_doc] + [p[0] for p in orphans_kb]
        if orphan_child_ids:
            if apply:
                child_client.delete(
                    collection_name=child_coll,
                    points_selector=__import__("qdrant_client.http.models", fromlist=["PointIdsList"]).PointIdsList(points=orphan_child_ids),
                )
                print(f"  ✓ 已删除 {len(orphan_child_ids)} 个孤儿子块")
            else:
                print(f"  DRY-RUN: 将删除 {len(orphan_child_ids)} 个孤儿子块")
                # 打印前 10 条样例
                for p in orphans_doc[:10]:
                    print(f"    orphan doc_id='{p[1]}' source='{p[2]}'")
    else:
        print("[child_chunks] 集合不存在，跳过")

    # ── 3. 扫 parent_chunks → 找孤儿父块 ──
    parent_coll = container.parent.COLLECTION_NAME
    if container.parent.collection_exists():
        orphans_parent = []
        offset = None
        while True:
            points, offset = container.qdrant.client.scroll(
                collection_name=parent_coll,
                limit=5_000,
                offset=offset,
                with_payload=True,
            )
            for p in points:
                meta = (p.payload or {}).get("metadata", {}) or {}
                doc_id = meta.get("doc_id", "")
                if not doc_id or doc_id not in valid_doc_ids:
                    orphans_parent.append((p.id, doc_id, meta.get("source", "")))
            if offset is None or not points:
                break
        print(f"\n[parent_chunks] 孤儿: {len(orphans_parent)}")
        if orphans_parent:
            if apply:
                container.qdrant.client.delete(
                    collection_name=parent_coll,
                    points_selector=__import__("qdrant_client.http.models", fromlist=["PointIdsList"]).PointIdsList(
                        points=[p[0] for p in orphans_parent]
                    ),
                )
                print(f"  ✓ 已删除 {len(orphans_parent)} 个孤儿父块")
            else:
                print(f"  DRY-RUN: 将删除 {len(orphans_parent)} 个孤儿父块")
                for p in orphans_parent[:10]:
                    print(f"    orphan doc_id='{p[1]}' source='{p[2]}'")
    else:
        print("[parent_chunks] 集合不存在，跳过")

    # ── 4. 扫 long_term_memory → 找孤儿记忆向量 ──
    ltm_coll = container.long_term_memory_store.COLLECTION_NAME
    ltm_client = container.long_term_memory_store._client
    if ltm_client and ltm_client.collection_exists(ltm_coll):
        orphans_ltm = []
        offset = None
        while True:
            points, offset = ltm_client.scroll(
                collection_name=ltm_coll,
                limit=5_000,
                offset=offset,
                with_payload=False,
            )
            for p in points:
                if p.id not in valid_mem_ids:
                    orphans_ltm.append(p.id)
            if offset is None or not points:
                break
        print(f"\n[long_term_memory] 孤儿: {len(orphans_ltm)}")
        if orphans_ltm:
            if apply:
                ltm_client.delete(
                    collection_name=ltm_coll,
                    points_selector=__import__("qdrant_client.http.models", fromlist=["PointIdsList"]).PointIdsList(points=orphans_ltm),
                )
                print(f"  ✓ 已删除 {len(orphans_ltm)} 个孤儿记忆向量")
            else:
                print(f"  DRY-RUN: 将删除 {len(orphans_ltm)} 个孤儿记忆向量")
    else:
        print("[long_term_memory] 集合不存在，跳过")

    # ── 5. 结束报告（清理后再汇总） ──
    if apply:
        print("\n=== 再次统计（应用后） ===")
        doc_set = {d.id for d in docs}
        kb_set = valid_kb_ids
        for coll_name, is_child in [(child_coll, True), (parent_coll, False)]:
            if not container.qdrant.client.collection_exists(coll_name):
                continue
            sources_after = Counter()
            bad = 0
            total = 0
            offset = None
            while True:
                points, offset = container.qdrant.client.scroll(
                    collection_name=coll_name,
                    limit=5_000,
                    offset=offset,
                    with_payload=True,
                )
                total += len(points)
                for p in points:
                    meta = (p.payload or {}).get("metadata", {}) or {}
                    src = meta.get("source", "")
                    if src:
                        sources_after[src] += 1
                    doc_id = meta.get("doc_id", "")
                    kb_id = meta.get("kb_id")
                    if (doc_id and doc_id not in doc_set) or (kb_id and kb_id not in kb_set):
                        bad += 1
                if offset is None or not points:
                    break
            print(f"  [{coll_name}] total={total} 仍有orphan={bad} sources={dict(sources_after.most_common(10))}")

    container.qdrant.close()
    print("\n完成。")


if __name__ == "__main__":
    main()
