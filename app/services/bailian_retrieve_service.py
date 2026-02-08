"""百炼知识库检索服务：RAG 召回，供出题生成时增强上下文。"""
import logging
import os
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# 可选：请求百炼时绕过代理，避免 SSL 等问题
def _maybe_disable_proxy() -> None:
    if os.getenv("BAILIAN_NO_PROXY", "").lower() in ("1", "true", "yes"):
        os.environ.update({"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "*"})


def create_client():
    """创建百炼 OpenAPI 客户端。需环境变量：ALIBABA_CLOUD_ACCESS_KEY_ID、ALIBABA_CLOUD_ACCESS_KEY_SECRET。"""
    _maybe_disable_proxy()
    try:
        from alibabacloud_tea_openapi.models import Config
        from alibabacloud_bailian20231229 import client as bailian_client
    except ImportError as e:
        logger.warning("百炼 SDK 未安装或版本不兼容: %s", e)
        return None
    access_key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    access_key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if not access_key_id or not access_key_secret:
        logger.warning("未配置 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET，RAG 检索跳过")
        return None
    config = Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
    )
    config.endpoint = "bailian.cn-beijing.aliyuncs.com"
    return bailian_client.Client(config)


def retrieve(
    workspace_id: str,
    index_id: str,
    query: str,
    client: Any = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    在指定知识库中检索。

    参数:
        workspace_id: 业务空间 ID。
        index_id: 知识库 ID。
        query: 检索内容（如用户材料摘要或要点）。
        client: 百炼客户端，为 None 时内部创建。

    返回:
        (nodes_for_logging, concatenated_text)
        - nodes_for_logging: [{"score": float, "text": str, "metadata": ...}, ...]，便于日志/调试。
        - concatenated_text: 将各 node.text 用双换行拼接后的字符串，供拼进 prompt；无结果时为空串。
    """
    nodes_for_logging: list[dict[str, Any]] = []
    concatenated_text = ""

    if not (query or "").strip():
        return nodes_for_logging, concatenated_text
    if not workspace_id or not index_id:
        logger.info("[RAG] 未配置 WORKSPACE_ID 或 BAILIAN_INDEX_ID，跳过检索")
        return nodes_for_logging, concatenated_text

    close_client = False
    if client is None:
        client = create_client()
        close_client = True
    if client is None:
        return nodes_for_logging, concatenated_text

    try:
        from alibabacloud_bailian20231229 import models as bailian_models
    except ImportError:
        logger.warning("百炼 models 不可用，RAG 检索跳过")
        return nodes_for_logging, concatenated_text

    request = bailian_models.RetrieveRequest(
        index_id=index_id,
        query=query.strip(),
    )
    try:
        resp = client.retrieve(workspace_id, request)
    except Exception as e:
        logger.exception("[RAG] 百炼 retrieve 调用异常: %s", e)
        return nodes_for_logging, concatenated_text
    finally:
        if close_client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass

    if not resp or not getattr(resp, "body", None):
        logger.warning("[RAG] 检索无响应体")
        return nodes_for_logging, concatenated_text
    body = resp.body
    if body.success not in (True, "true", "True"):
        logger.warning("[RAG] 检索失败: %s", getattr(body, "message", body))
        return nodes_for_logging, concatenated_text

    data = getattr(body, "data", None)
    nodes = (data and getattr(data, "nodes", None)) or []

    texts: list[str] = []
    for node in nodes:
        score = getattr(node, "score", None)
        text = (getattr(node, "text", None) or "").strip()
        meta = getattr(node, "metadata", None)
        nodes_for_logging.append({
            "score": score,
            "text": text[:500] + ("..." if len(text) > 500 else ""),
            "metadata": meta,
        })
        if text:
            texts.append(text)

    concatenated_text = "\n\n".join(texts) if texts else ""

    logger.info(
        "[RAG] 召回完成 index_id=%s query_len=%d 命中=%d 总字符=%d",
        index_id, len(query.strip()), len(nodes_for_logging), len(concatenated_text),
    )
    return nodes_for_logging, concatenated_text


def retrieve_for_question_generation(
    user_content: str,
    workspace_id: str | None = None,
    index_id: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    为「生成题目」做 RAG 检索：用用户材料（或前一段）作为 query 召回知识库片段。

    返回 (nodes_for_logging, rag_text)，便于路由层打日志/写调试文件，并将 rag_text 拼进生成 prompt。
    """
    ws = (workspace_id or "").strip() or getattr(settings, "bailian_workspace_id", "") or ""
    idx = (index_id or "").strip() or getattr(settings, "bailian_index_id", "") or ""
    query = (user_content or "").strip()[:2000]  # 避免 query 过长
    return retrieve(workspace_id=ws, index_id=idx, query=query or "出题")
