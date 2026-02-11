"""个人中心：用户资料 GET/PUT /api/user/profile。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.user import UserProfileResponse, UserProfileUpdate

router = APIRouter()


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
async def get_profile(user: User = Depends(get_current_user)):
    """获取当前用户个人资料（个人中心展示）。"""
    return _user_to_profile_response(user)


@router.put("/profile", response_model=UserProfileResponse)
async def update_profile(
    body: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
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
    await db.commit()
    await db.refresh(user)
    return _user_to_profile_response(user)
