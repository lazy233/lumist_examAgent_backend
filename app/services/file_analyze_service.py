"""文件分析服务：上传文件到百炼，用 qwen-long 分析文档内容，供后续出题使用。"""
import asyncio
import io
import logging
import os
import re
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 与 llm_service 一致：绕过代理
os.environ.setdefault("HTTP_PROXY", "")
os.environ.setdefault("HTTPS_PROXY", "")
os.environ.setdefault("NO_PROXY", "*")


def _get_file_client() -> AsyncOpenAI:
    """文件上传与 qwen-long 使用同一 Dashscope 兼容端点，可用 DASHSCOPE_API_KEY 或 OPENAI_API_KEY。"""
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def _normalize_usage(raw: Any) -> dict[str, int] | None:
    """将 usage 转为统一格式：inputTokens, outputTokens, totalTokens。"""
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
    return {
        "inputTokens": int(inp) if inp is not None else 0,
        "outputTokens": int(out) if out is not None else 0,
        "totalTokens": int(total) if total is not None else 0,
    }


# 首行「标题：xxx」解析
_TITLE_LINE_RE = re.compile(r"^\s*标题[：:]\s*(.+)$")


async def analyze_file_for_questions(file_path: str | Path) -> tuple[str, str, dict[str, int] | None]:
    """
    上传文件到百炼并调用 qwen-long 分析文档，得到适合作为出题材料的文本。

    参数:
        file_path: 本地文件路径（临时文件即可）。

    返回:
        (content, title, usage)
        - content: 分析正文，用于后续 generate-from-text 的 content。
        - title: 建议试卷标题（若模型首行写了「标题：xxx」则解析，否则取 content 前 30 字）。
        - usage: { inputTokens, outputTokens, totalTokens } 或 None。
    """
    path = Path(file_path)
    if not await asyncio.to_thread(path.is_file):
        raise FileNotFoundError(f"文件不存在: {path}")

    client = _get_file_client()
    data = await asyncio.to_thread(path.read_bytes)
    file_object = await client.files.create(file=io.BytesIO(data), purpose="file-extract")
    file_id = getattr(file_object, "id", None)
    if not file_id:
        raise RuntimeError("文件上传后未返回 id")

    user_prompt = """请分析这篇文档的内容，提炼出主要内容和适合出题的知识要点，用连贯的文本概括（将作为后续出题的材料）。
若需要建议标题，请在第一行写：标题：xxx ，换行后再写正文；否则直接写正文。"""

    messages = [
        {"role": "system", "content": f"fileid://{file_id}"},
        {"role": "user", "content": user_prompt},
    ]
    print("\n" + "=" * 60 + " [LLM 提示词] analyze_file_for_questions " + "=" * 60)
    for m in messages:
        print(f"[{m['role']}]\n{m['content']}\n")
    print("=" * 60 + "\n")

    completion = await client.chat.completions.create(
        model=settings.file_analyze_model,
        messages=messages,
    )
    usage = _normalize_usage(getattr(completion, "usage", None))
    raw = (completion.choices[0].message.content or "").strip()
    if not raw:
        return "", "文档分析", usage

    lines = raw.split("\n")
    title = ""
    content = raw
    if lines:
        first = lines[0].strip()
        m = _TITLE_LINE_RE.match(first)
        if m:
            title = m.group(1).strip()
            content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    if not title and content:
        title = content[:30] + "…" if len(content) > 30 else content
    if not title:
        title = "文档出题"

    return content, title, usage
