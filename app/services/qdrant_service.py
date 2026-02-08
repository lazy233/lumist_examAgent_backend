import uuid
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, FilterSelector, MatchValue, PointStruct, VectorParams
from app.core.config import settings

def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)

def ensure_collection(client: QdrantClient) -> None:
    collections = client.get_collections().collections
    if not any(c.name == settings.qdrant_collection for c in collections):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.embedding_dim,
                distance=Distance.COSINE,
            ),
        )

def upsert_chunks(client: QdrantClient, doc_id: str, owner_id: str,
                  chunks: list[str], vectors: list[list[float]]) -> None:
    if not chunks or len(vectors) != len(chunks):
        return  # Qdrant 不接受空 points；chunks 与 vectors 长度需一致
    points = []
    for idx, (text, vec) in enumerate(zip(chunks, vectors)):
        points.append(
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{idx}")),
                vector=vec,
                payload={
                    "docId": doc_id,
                    "ownerId": owner_id,
                    "chunkIndex": idx,
                    "content": text,
                },
            )
        )
    if not points:
        return
    client.upsert(collection_name=settings.qdrant_collection, points=points)


def delete_chunks_by_doc_id(client: QdrantClient, doc_id: str) -> None:
    """Delete all chunks belonging to the given doc from Qdrant."""
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="docId", match=MatchValue(value=doc_id))],
            ),
        ),
    )