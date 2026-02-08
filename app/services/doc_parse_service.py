import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from pptx import Presentation
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

from app.core.config import settings
from app.services.embedding_service import embed_texts
from app.services.llm_service import summarize_document
from app.services.qdrant_service import get_client, ensure_collection, upsert_chunks

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.doc import Doc

def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def _load_pptx_text(file_path: str) -> str:
    prs = Presentation(file_path)
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                texts.append(shape.text)
    return "\n".join(texts)

def _load_text(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        return "\n".join([d.page_content for d in docs])
    if ext == ".docx":
        loader = Docx2txtLoader(file_path)
        docs = loader.load()
        return "\n".join([d.page_content for d in docs])
    if ext == ".txt":
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        return "\n".join([d.page_content for d in docs])
    if ext == ".pptx":
        return _load_pptx_text(file_path)
    raise ValueError("Unsupported file type")

def _save_debug_files(doc_id: str, owner_id: str, cleaned_text: str, chunks: list[str], vectors: list[list[float]]) -> None:
    """保存解析内容和向量库写入指令到本地，方便调试"""
    debug_path = Path(settings.debug_dir)
    debug_path.mkdir(parents=True, exist_ok=True)

    # 1. 解析出的全文
    parsed_file = debug_path / f"{doc_id}_parsed.txt"
    parsed_file.write_text(cleaned_text, encoding="utf-8")

    # 2. 发到 Qdrant 的 upsert 指令（不含完整向量，仅保留维度示例）
    upsert_data = {
        "collection": settings.qdrant_collection,
        "points": [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{idx}")),
                "payload": {
                    "docId": doc_id,
                    "ownerId": owner_id,
                    "chunkIndex": idx,
                    "content": text,
                },
                "vector": vec,
            }
            for idx, (text, vec) in enumerate(zip(chunks, vectors))
        ],
    }
    qdrant_file = debug_path / f"{doc_id}_qdrant_upsert.json"
    qdrant_file.write_text(json.dumps(upsert_data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_and_index(
    file_path: str,
    doc_id: str,
    owner_id: str,
    db: "Session | None" = None,
    doc: "Doc | None" = None,
) -> None:
    raw_text = _load_text(file_path)
    cleaned = _clean_text(raw_text)

    # 1. 大模型总结，返回结构化数据
    parsed = summarize_document(cleaned)
    if db is not None and doc is not None:
        doc.parsed_school = parsed.get("school") or ""
        doc.parsed_major = parsed.get("major") or ""
        doc.parsed_course = parsed.get("course") or ""
        doc.parsed_summary = parsed.get("summary") or ""
        kps = parsed.get("knowledgePoints")
        doc.parsed_knowledge_points = kps if isinstance(kps, list) else []
        db.commit()

    # 2. 分块、向量化、写入 Qdrant
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_text(cleaned)
    chunks = [c.strip() for c in chunks if c.strip()]

    vectors = embed_texts(chunks)

    # 调试：保存解析内容和 Qdrant 写入指令到本地
    _save_debug_files(doc_id, owner_id, cleaned, chunks, vectors)

    client = get_client()
    ensure_collection(client)
    upsert_chunks(client, doc_id=doc_id, owner_id=owner_id, chunks=chunks, vectors=vectors)