import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services.chat_service import stream_chat

router = APIRouter()

def _sse_frame(*, event: str, data: str) -> bytes:
    """
    生成一条 SSE 帧（bytes）。

    SSE 规则：
    - 以空行分隔事件（推荐使用 CRLF：\\r\\n\\r\\n）
    - data 允许多行，但每行必须以 `data:` 前缀
    """
    event = (event or "").strip() or "message"
    # 规范化为 LF 后再按行拆分，最终输出使用 CRLF，避免部分客户端/代理对换行处理不一致导致“粘包展示”
    data = (data or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = data.split("\n")

    out_lines: list[str] = [f"event: {event}"]
    if not lines:
        out_lines.append("data:")
    else:
        for line in lines:
            out_lines.append(f"data: {line}")

    out = "\r\n".join(out_lines) + "\r\n\r\n"
    return out.encode("utf-8")


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),  # 预留依赖，便于后续引入会话记忆等能力
):
    """
    智能问答流式接口。

    - 请求体：ChatRequest（messages + options），与前端约定保持一致。
    - 鉴权：使用 Authorization: Bearer <token>，通过 get_current_user 解析。
    - 响应：流式文本。
      - 前面多行/多段为回答正文。
      - 最后一行是包含 usage/conversationId/skillsUsed/recall 等字段的 JSON，供前端调试展示。
    """
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_chat(body, user_id=current_user.id):
                if isinstance(chunk, str):
                    if chunk:
                        yield _sse_frame(event="chunk", data=chunk)
                elif isinstance(chunk, dict) and "_meta" in chunk:
                    yield _sse_frame(
                        event="meta",
                        data=json.dumps(chunk["_meta"], ensure_ascii=False),
                    )
            yield _sse_frame(event="done", data="{}")
        except asyncio.CancelledError:
            # 客户端断开：不再继续写入
            raise
        except Exception as e:
            # 注意：流式中发生异常无法可靠返回非 200 状态码，因此用 SSE error 事件通知
            yield _sse_frame(
                event="error",
                data=json.dumps({"message": str(e)}, ensure_ascii=False),
            )
            yield _sse_frame(event="done", data="{}")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            # SSE 推荐 no-cache；no-store 也可，但这里按你前端描述对齐为 no-cache
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

