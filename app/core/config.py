import os
from dataclasses import dataclass

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_local_model_path = os.path.join(_project_root, "models", "AI-ModelScope", "all-MiniLM-L6-v2")
_default_embedding = _local_model_path if os.path.exists(_local_model_path) else "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class Settings:
    api_prefix: str = os.getenv("API_PREFIX", "/api")
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:123456@localhost:5432/lumist_exam_agent",
    )
    db_echo: bool = os.getenv("DB_ECHO", "false").lower() == "true"
    qdrant_url: str = os.getenv("QDRANT_URL", "http://134.175.97.248:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "doc_chunks")
    data_root: str = os.getenv("DATA_ROOT", "data")
    upload_dir: str = os.getenv("UPLOAD_DIR", "data/upload")
    library_dir: str = os.getenv("LIBRARY_DIR", "data/library")
    debug_dir: str = os.getenv("DEBUG_DIR", "data/debug")
    hf_endpoint: str = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", _default_embedding)
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "384"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))
    # 百炼知识库 RAG：业务空间 ID、知识库 ID，为空则不走 RAG
    bailian_workspace_id: str = os.getenv("WORKSPACE_ID", "")
    bailian_index_id: str = os.getenv("BAILIAN_INDEX_ID", "ujsxu342w0")


settings = Settings()
