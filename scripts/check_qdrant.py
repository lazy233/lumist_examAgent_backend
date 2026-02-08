"""查看 Qdrant 集合内容和统计"""
from qdrant_client import QdrantClient
from app.core.config import settings

client = QdrantClient(url=settings.qdrant_url)
print("=== Qdrant 连接:", settings.qdrant_url)
print()
colls = client.get_collections().collections
print("=== 集合列表")
for c in colls:
    info = client.get_collection(c.name)
    print(f"  - {c.name}: points={info.points_count}")
print()

if settings.qdrant_collection in [c.name for c in colls]:
    info = client.get_collection(settings.qdrant_collection)
    print(f"=== 集合 {settings.qdrant_collection} 详情")
    print(f"  points: {info.points_count}")
    print()
    if info.points_count > 0:
        result = client.scroll(
            settings.qdrant_collection, limit=5, with_payload=True, with_vectors=False
        )
        points, _ = result
        print("=== 前 5 条 payload 示例")
        for i, p in enumerate(points):
            print(f"  --- [{i+1}] id={p.id} ---")
            for k, v in (p.payload or {}).items():
                val = str(v)[:80] + "..." if len(str(v)) > 80 else v
                print(f"      {k}: {val}")
else:
    print("集合 doc_chunks 不存在")
