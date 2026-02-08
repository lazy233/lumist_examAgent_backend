"""大模型服务，用于文档总结等。API Key 硬编码，上线前需改为环境变量。"""
import json
import os
from typing import Any

from openai import OpenAI

# 绕过代理，避免 SSL 连接错误
os.environ.update({"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "*"})

_DEFAULT_API_KEY = "sk-ed09584eec034991a5a7029342c05d98"
_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """供出题等模块使用的 OpenAI 兼容客户端（阿里云百炼）。"""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", _DEFAULT_API_KEY),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


def summarize_document(text: str) -> dict[str, Any]:
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
    completion = client.chat.completions.create(
        model="MiniMax-M2.1",
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
    )
    content = completion.choices[0].message.content or ""

    # 尝试解析 JSON（可能被 markdown 包裹）
    content = content.strip()
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
