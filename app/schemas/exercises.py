"""出题/练习相关请求/响应模型。"""
from pydantic import BaseModel, Field


# ----- 分析材料 -----
class AnalyzeRequest(BaseModel):
    content: str = Field(default="", description="用户输入的文字材料")
    question_type: str = Field(default="single_choice", alias="questionType")
    difficulty: str = Field(default="medium")
    count: int = Field(default=5, ge=1, description="题目数量，无上限")

    model_config = {"populate_by_name": True}


class UsageInfo(BaseModel):
    inputTokens: int = 0
    outputTokens: int = 0
    totalTokens: int = 0


class AnalyzeResponse(BaseModel):
    keyPoints: list[str] = Field(default_factory=list)
    title: str = Field("", description="整张试卷大标题，由分析得出，生成时传入")
    questionType: str = Field(..., description="题型枚举值")
    questionTypeLabel: str = Field(..., description="题型中文")
    difficulty: str = Field(..., description="难度枚举值")
    difficultyLabel: str = Field(..., description="难度中文")
    count: int = Field(..., description="题目数量")
    usage: UsageInfo | None = Field(None, description="本次分析调用大模型消耗的 token")


class GenerateFromTextRequest(BaseModel):
    content: str = Field(default="", description="用户输入的文字材料")
    title: str | None = Field(None, description="整张试卷大标题，来自分析接口，可选")
    question_type: str = Field(default="single_choice", alias="questionType")
    difficulty: str = Field(default="medium")
    count: int = Field(default=5, ge=1, description="题目数量，无上限")
    key_points: list[str] | None = Field(default=None, alias="keyPoints", description="分析得到的要点")
    analysis: str | None = Field(default=None, description="分析结果或用户意图补充")

    model_config = {"populate_by_name": True}


class AnalyzeFileResponse(BaseModel):
    """文件分析结果，用户确认后可将 content、title 传给 generate-from-text。"""
    content: str = Field(..., description="分析得到的出题材料正文，即 generate-from-text 的 content")
    title: str = Field("", description="建议试卷标题，即 generate-from-text 的 title")
    usage: UsageInfo | None = Field(None, description="本次文件分析调用大模型消耗的 token")


# ----- 练习详情、提交、列表 -----
class QuestionItem(BaseModel):
    questionId: str
    type: str
    stem: str
    options: dict[str, str] | None = None


class ExerciseDetailResponse(BaseModel):
    exerciseId: str
    title: str | None
    status: str
    difficulty: str
    count: int
    questionType: str
    questionTypeLabel: str
    questions: list[QuestionItem]
    createdAt: str
    score: int | None = None


class SubmitAnswerItem(BaseModel):
    questionId: str
    answer: str


class SubmitRequest(BaseModel):
    answers: list[SubmitAnswerItem]


class ResultItem(BaseModel):
    questionId: str
    isCorrect: bool
    userAnswer: str
    correctAnswer: str
    analysis: str | None = None


class SubmitResponse(BaseModel):
    score: int
    correctRate: float
    results: list[ResultItem]


class ExerciseListItem(BaseModel):
    exerciseId: str
    title: str | None
    status: str
    difficulty: str
    count: int
    questionType: str
    questionTypeLabel: str
    questionCount: int = Field(0, description="实际落库的题目数，用于核对是否插入成功")
    createdAt: str
    score: int | None = None


class ExerciseListResponse(BaseModel):
    items: list[ExerciseListItem] = Field(default_factory=list)
    total: int = 0
