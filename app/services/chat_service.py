"""智能问答服务：为 /chat/stream 提供解耦的编排层。

设计目标：
- 与具体 LLM SDK 解耦：通过 get_openai_client 适配 OpenAI 兼容接口，后续可替换为 LangChain、AgentScope 等。
- 与 RAG 框架解耦：通过一个简单的检索提供函数，当前默认实现复用百炼 RAG，后续可替换为任意向量库/检索框架。
- 与 Skill / MCP 解耦：通过选项与占位逻辑记录启用的特性，实际编排可在此模块内自由扩展或替换。

本模块不做持久化记忆，仅使用前端传入的多轮 messages；需要服务端记忆时，可在此处接数据库或向量库。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Iterable

from app.core.config import settings
from app.schemas.chat import (
    ChatMeta,
    ChatOptions,
    ChatRecallItem,
    ChatRequest,
    ChatUsage,
)
from app.services.llm_service import get_openai_client

logger = logging.getLogger(__name__)


def _normalize_usage(raw: Any) -> ChatUsage | None:
    """将 OpenAI/百炼返回的 usage 转为 ChatUsage。"""
    if raw is None:
        return None
    inp = getattr(raw, "input_tokens", None) or getattr(raw, "prompt_tokens", None)
    out = getattr(raw, "output_tokens", None) or getattr(raw, "completion_tokens", None)
    total = getattr(raw, "total_tokens", None)
    if inp is None and out is None and total is None:
        return None
    if total is None and (inp is not None or out is not None):
        try:
            total = (inp or 0) + (out or 0)
        except Exception:
            total = None
    return ChatUsage(
        inputTokens=int(inp) if inp is not None else 0,
        outputTokens=int(out) if out is not None else 0,
        totalTokens=int(total) if total is not None else 0,
    )


async def _retrieve_rag_context_for_chat(
    options: ChatOptions | None,
    messages: Iterable[dict[str, str]],
) -> tuple[list[ChatRecallItem], str]:
    """
    为聊天做 RAG 检索，当前实现是可选的：
    - 若 settings.chat_enable_rag 为 False 或没有知识库 id，则直接返回空。
    - 默认实现：复用百炼知识库检索，使用最后一条 user 消息作为 query。
    后续可以很容易替换为任意向量库 / LangChain / AgentScope 等方案。
    """
    from app.services.bailian_retrieve_service import retrieve_for_question_generation

    if not settings.chat_enable_rag:
        return [], ""

    kb_ids = (options.knowledgeBaseIds if options else None) or []
    # 当前百炼检索并不按 docId 过滤，仅作为后续扩展保留 knowledgeBaseIds
    # 默认 query 使用最后一条 user 消息
    last_user_content = ""
    for m in reversed(list(messages)):
        if m.get("role") == "user" and (m.get("content") or "").strip():
            last_user_content = m["content"]
            break
    if not last_user_content.strip():
        return [], ""

    nodes, rag_text = await retrieve_for_question_generation(last_user_content)
    recall_items: list[ChatRecallItem] = []
    for node in nodes:
        meta = node.get("metadata") or {}
        doc_id = (
            meta.get("docId")
            or meta.get("doc_id")
            or meta.get("document_id")
            or meta.get("id")
            or ""
        )
        recall_items.append(
            ChatRecallItem(
                docId=str(doc_id),
                content=str(node.get("text") or ""),
                score=node.get("score"),
            )
        )
    return recall_items, rag_text


async def stream_chat(
    request: ChatRequest,
    *,
    user_id: str | None = None,
) -> AsyncIterator[str | dict[str, Any]]:
    """
    核心编排入口：根据请求与配置调用底层 LLM（可替换）、可选 RAG（可替换），并以流式形式输出。

    约定：
    - 迭代过程中 yield 若干 str 片段，作为回答正文。
    - 结束前 yield 一次 {"_meta": ChatMetaDict}，供路由层转为最后一行 JSON。
    """
    if not request.messages:
        # 由路由层做 400 校验，这里兜底
        yield "对话消息不能为空。"
        return

    options: ChatOptions | None = request.options
    model = (options.model or "").strip() if options else ""
    if not model:
        # 单独为聊天预留的可切换模型；为空则回落到全局 llm_model
        model = settings.chat_model or settings.llm_model

    # 将 messages 转为 OpenAI 兼容格式，并收集 user 消息用于 RAG
    openai_messages: list[dict[str, str]] = []

    system_prompt = (options.systemPrompt or "").strip() if options else ""
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})

    for m in request.messages:
        role = m.role
        if role not in ("user", "assistant", "system"):
            # 非标准角色一律按 user 处理，避免 SDK 报错
            role = "user"
        openai_messages.append({"role": role, "content": m.content})

    # RAG：可通过环境变量完全关闭；实现也可替换
    recall_items: list[ChatRecallItem] = []
    rag_context = ""
    if settings.chat_enable_rag:
        try:
            recall_items, rag_context = await _retrieve_rag_context_for_chat(
                options,
                openai_messages,
            )
        except Exception as e:
            logger.warning("聊天 RAG 检索失败，将继续无 RAG：%s", e)

    if rag_context:
        # 以 system 消息形式注入 RAG 参考，保持与核心对话解耦
        openai_messages.insert(
            0,
            {
                "role": "system",
                "content": (
                    "下面是与本次对话相关的知识库检索结果，请在回答时参考其内容，"
                    "但当与用户问题或事实相冲突时，以通用常识与用户问题为准：\n\n"
                    f"{rag_context[:6000]}"
                ),
            },
        )

    # Skills / MCP：当前仅记录启用的 skills，真实编排逻辑可在此扩展或替换
    skills_requested = (options.skills if options else None) or []
    skills_used: list[str] = []
    if settings.chat_enable_skills and skills_requested:
        # 当前版本不做复杂 skill 调度，仅原样标记为已使用
        skills_used = list(dict.fromkeys(skills_requested))  # 去重并保持顺序

    # 若后续引入 MCP，可在此根据 settings.chat_enable_mcp 决定是否接入工具调用

    # 调用底层 LLM（当前适配 OpenAI 兼容接口，后续可替换为任意实现）
    client = get_openai_client()
    logger.info("[chat] 开始流式对话调用 model=%s user_id=%s", model, user_id or "-")

    completion = await client.chat.completions.create(
        model=model,
        messages=openai_messages,
        extra_body={"enable_thinking": True},
        stream=True,
        stream_options={"include_usage": True},
    )

    last_usage: ChatUsage | None = None
    async for chunk in completion:
        if getattr(chunk, "usage", None) is not None:
            last_usage = _normalize_usage(chunk.usage)
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        # 屏蔽 reasoning_content，仅下发最终回答
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            continue
        if hasattr(delta, "content") and delta.content:
            yield delta.content

    # 组装元数据，交给路由层输出为最后一行 JSON
    meta = ChatMeta(
        usage=last_usage,
        conversationId=str(uuid.uuid4()),
        skillsUsed=skills_used or None,
        recall=recall_items or None,
    )
    yield {"_meta": json.loads(meta.model_dump_json(exclude_none=True, ensure_ascii=False))}

