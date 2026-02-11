"""认证相关请求/响应模型。"""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(..., description="用户名（建议唯一）")
    password: str = Field(..., min_length=6, description="密码（至少 6 位）")
    name: str | None = Field(None, description="姓名/昵称")


class AuthUser(BaseModel):
    id: str = Field(..., description="用户 ID")
    name: str = Field(..., description="显示名称")


class AuthResponse(BaseModel):
    token: str = Field(..., description="JWT 或会话令牌")
    user: AuthUser = Field(..., description="用户信息")
