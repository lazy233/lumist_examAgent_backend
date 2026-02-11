"""健康检查响应模型。"""
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field("ok", description="服务状态")
