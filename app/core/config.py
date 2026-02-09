import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_prefix: str = os.getenv("API_PREFIX", "/api")
    secret_key: str = os.getenv("SECRET_KEY", "change-me-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:123456@localhost:5432/lumist_exam_agent",
    )
    db_echo: bool = os.getenv("DB_ECHO", "false").lower() == "true"
    data_root: str = os.getenv("DATA_ROOT", "data")
    upload_dir: str = os.getenv("UPLOAD_DIR", "data/upload")
    library_dir: str = os.getenv("LIBRARY_DIR", "data/library")
    debug_dir: str = os.getenv("DEBUG_DIR", "data/debug")
    # 百炼知识库 RAG：业务空间 ID、知识库 ID，为空则不走 RAG
    bailian_workspace_id: str = os.getenv("WORKSPACE_ID", "")
    bailian_index_id: str = os.getenv("BAILIAN_INDEX_ID", "ujsxu342w0")


settings = Settings()
