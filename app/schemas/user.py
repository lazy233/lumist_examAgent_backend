"""用户/个人中心相关请求/响应模型。"""
from pydantic import BaseModel, Field


class UserProfileResponse(BaseModel):
    """个人资料响应，字段与前端个人中心一致。"""
    userId: str = Field(..., description="用户 ID（可与 username 一致用于展示）")
    username: str = Field("", description="用户名，如 dev")
    name: str = Field("", description="姓名")
    school: str | None = Field(None, description="学校")
    major: str | None = Field(None, description="专业")
    grade: str | None = Field(None, description="年级")
    age: int | None = Field(None, description="年龄")
    gender: str | None = Field(None, description="性别")
    questionTypePreference: str | None = Field(None, description="题型偏好")
    difficultyPreference: str | None = Field(None, description="难度偏好")
    questionCount: int | None = Field(None, description="题目数量")

    model_config = {"populate_by_name": True}


class UserProfileUpdate(BaseModel):
    """个人资料更新请求体（camelCase 与前端一致）。"""
    name: str | None = Field(None, description="姓名")
    school: str | None = Field(None, description="学校")
    major: str | None = Field(None, description="专业")
    grade: str | None = Field(None, description="年级")
    age: int | None = Field(None, description="年龄")
    gender: str | None = Field(None, description="性别")
    questionTypePreference: str | None = Field(None, description="题型偏好")
    difficultyPreference: str | None = Field(None, description="难度偏好")
    questionCount: int | None = Field(None, description="题目数量")

    model_config = {"populate_by_name": True}
