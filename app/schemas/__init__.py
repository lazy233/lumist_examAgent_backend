"""API 请求/响应 Pydantic 模型。按模块组织，路由从本包或子模块导入。"""
from app.schemas.auth import (
    AuthResponse,
    AuthUser,
    LoginRequest,
    RegisterRequest,
)
from app.schemas.docs import (
    DocItem,
    DocListResponse,
    DocParsedInfo,
    DocUploadResponse,
)
from app.schemas.exercises import (
    AnalyzeFileResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    ExerciseDetailResponse,
    ExerciseListItem,
    ExerciseListResponse,
    GenerateFromTextRequest,
    QuestionItem,
    ResultItem,
    SubmitAnswerItem,
    SubmitRequest,
    SubmitResponse,
    UsageInfo,
)
from app.schemas.health import HealthResponse
from app.schemas.user import UserProfileResponse, UserProfileUpdate

__all__ = [
    "AuthResponse",
    "AuthUser",
    "LoginRequest",
    "RegisterRequest",
    "DocItem",
    "DocListResponse",
    "DocParsedInfo",
    "DocUploadResponse",
    "AnalyzeFileResponse",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "ExerciseDetailResponse",
    "ExerciseListItem",
    "ExerciseListResponse",
    "GenerateFromTextRequest",
    "QuestionItem",
    "ResultItem",
    "SubmitAnswerItem",
    "SubmitRequest",
    "SubmitResponse",
    "UsageInfo",
    "HealthResponse",
    "UserProfileResponse",
    "UserProfileUpdate",
]
