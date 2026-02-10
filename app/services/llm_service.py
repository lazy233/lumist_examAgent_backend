"""大模型服务，用于文档总结等。API Key 硬编码，上线前需改为环境变量。"""
import json
import os
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.core.config import settings

# 绕过代理，避免 SSL 连接错误
os.environ.update({"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "*"})

_DEFAULT_API_KEY = "sk-ed09584eec034991a5a7029342c05d98"
_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """供出题等模块使用的 OpenAI 兼容客户端（阿里云百炼）。"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", _DEFAULT_API_KEY),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


def parse_summary_content(content: str) -> dict[str, Any]:
    # 尝试解析 JSON（可能被 markdown 包裹）
    content = (content or "").strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "school": "",
            "major": "",
            "course": "",
            "knowledgePoints": [],
            "summary": content[:500] if content else "",
        }


async def summarize_document(text: str) -> dict[str, Any]:
    """
    让大模型总结文档，返回结构化数据。
    返回: { school, major, course, knowledgePoints: [...], summary }
    """
    if not text.strip():
        return {
            "school": "",
            "major": "",
            "course": "",
            "knowledgePoints": [],
            "summary": "",
        }

    prompt = """请根据以下文档内容，提取并返回 JSON 格式的结构化信息。只返回 JSON，不要其他文字。

字段说明：
- school: 学校/机构名称，若无则为空字符串
- major: 专业/方向，若无则为空字符串
- course: 课程名称，若无则为空字符串
- knowledgePoints: 知识点列表（字符串数组），提取文档中的核心知识点，若无则为 []
- summary: 文档摘要，200 字以内概括主要内容

文档内容：
"""
    prompt += text[:8000]  # 限制长度，避免超 token

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
    )
    content = completion.choices[0].message.content or ""
    return parse_summary_content(content)


async def stream_summarize_document(text: str) -> AsyncIterator[str]:
    """
    以流式方式让模型总结文档，仅 yield content 片段。
    调用方需自行拼接完整内容并做 JSON 解析。
    """
    if not text.strip():
        return
        yield  # pragma: no cover

    prompt = """请根据以下文档内容，提取并返回 JSON 格式的结构化信息。只返回 JSON，不要其他文字。

字段说明：
- school: 学校/机构名称，若无则为空字符串
- major: 专业/方向，若无则为空字符串
- course: 课程名称，若无则为空字符串
- knowledgePoints: 知识点列表（字符串数组），提取文档中的核心知识点，若无则为 []
- summary: 文档摘要，200 字以内概括主要内容

文档内容：
"""
    prompt += text[:8000]  # 限制长度，避免超 token

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
        stream=True,
    )
    async for chunk in completion:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            continue
        if hasattr(delta, "content") and delta.content:
            yield delta.content
