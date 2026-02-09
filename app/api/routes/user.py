"""个人中心：用户资料 GET/PUT /api/user/profile。"""
from fastapi import APIRouter, Depends

from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User

router = APIRouter()


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


def _user_to_profile_response(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        userId=user.id,
        username=user.username or "",
        name=user.name or "",
        school=user.school,
        major=user.major,
        grade=user.grade,
        age=user.age,
        gender=user.gender,
        questionTypePreference=user.question_type_preference,
        difficultyPreference=user.difficulty_preference,
        questionCount=user.question_count,
    )


@router.get("/profile", response_model=UserProfileResponse)
def get_profile(user: User = Depends(get_current_user)):
    """获取当前用户个人资料（个人中心展示）。"""
    return _user_to_profile_response(user)


@router.put("/profile", response_model=UserProfileResponse)
def update_profile(
    body: UserProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新当前用户个人资料（个人中心保存）。"""
    if body.name is not None:
        user.name = body.name
    if body.school is not None:
        user.school = body.school
    if body.major is not None:
        user.major = body.major
    if body.grade is not None:
        user.grade = body.grade
    if body.age is not None:
        user.age = body.age
    if body.gender is not None:
        user.gender = body.gender
    if body.questionTypePreference is not None:
        user.question_type_preference = body.questionTypePreference
    if body.difficultyPreference is not None:
        user.difficulty_preference = body.difficultyPreference
    if body.questionCount is not None:
        user.question_count = body.questionCount
    db.commit()
    db.refresh(user)
    return _user_to_profile_response(user)
