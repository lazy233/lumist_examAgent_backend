from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description='消息角色："user" 或 "assistant"')
    content: str = Field(..., description="消息内容（纯文本）")


class ChatOptions(BaseModel):
    model: Optional[str] = Field(
        default=None,
        description="模型名称，如 gpt-4o / gpt-4o-mini 等；为空则走后端默认模型",
    )
    knowledgeBaseIds: Optional[List[str]] = Field(
        default=None,
        description="用于 RAG 检索的知识库/文档 ID 列表，可为空",
    )
    skills: Optional[List[str]] = Field(
        default=None,
        description="启用的 skill 标识列表，可为空",
    )
    systemPrompt: Optional[str] = Field(
        default=None,
        description="系统提示词，用于约束助手角色或回答风格，可为空",
    )


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="按时间顺序排列的多轮对话消息")
    options: Optional[ChatOptions] = Field(
        default=None,
        description="聊天选项，可为空或空对象",
    )

    model_config = {"populate_by_name": True}


class ChatUsage(BaseModel):
    inputTokens: int = 0
    outputTokens: int = 0
    totalTokens: int = 0


class ChatRecallItem(BaseModel):
    docId: str = ""
    content: str = ""
    score: float | None = None


class ChatMeta(BaseModel):
    """
    流式输出最后一行的元数据结构。

    注意：不直接作为 FastAPI 响应模型使用，而是在路由中转为 JSON 字符串写入最后一行。
    """

    usage: Optional[ChatUsage] = None
    conversationId: Optional[str] = None
    skillsUsed: Optional[list[str]] = None
    recall: Optional[list[ChatRecallItem]] = None

