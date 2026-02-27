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
    # 生成题目时是否跳过 RAG 梳理（直接用召回原文）。设为 true 可显著减少首包延迟，但知识库参考更乱
    skip_rag_analyze: bool = os.getenv("SKIP_RAG_ANALYZE", "false").lower() in ("1", "true", "yes")
    # 大模型名称（出题、分析材料、RAG 梳理等均使用，需与 base_url 对应）
    llm_model: str = os.getenv("LLM_MODEL", "qwen-long")
    # 文件解析（长文档总结）使用的模型，可与 llm_model 不同
    file_analyze_model: str = os.getenv("FILE_ANALYZE_MODEL", "qwen-long")
    # 聊天相关配置：完全解耦，方便后续切换底层实现 / 模型 / RAG / Skills / MCP 等
    # 聊天默认模型，不配置则回落到 llm_model
    chat_model: str = os.getenv("CHAT_MODEL", "")
    # 是否在聊天中启用 RAG（当前默认实现复用百炼检索，后续可替换）
    chat_enable_rag: bool = os.getenv("CHAT_ENABLE_RAG", "false").lower() in ("1", "true", "yes")
    # 是否在聊天中启用 skills 编排（当前仅记录启用列表，逻辑可在 chat_service 中扩展或替换）
    chat_enable_skills: bool = os.getenv("CHAT_ENABLE_SKILLS", "true").lower() in ("1", "true", "yes")
    # 是否在聊天中启用 MCP / 工具调用（占位配置，具体实现留给后续框架接入）
    chat_enable_mcp: bool = os.getenv("CHAT_ENABLE_MCP", "false").lower() in ("1", "true", "yes")


settings = Settings()
