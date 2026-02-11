"""资料/文档相关请求/响应模型。"""
from pydantic import BaseModel, Field


class DocUploadResponse(BaseModel):
    docId: str = Field(..., description="文档 ID")
    fileName: str = Field(..., description="文件名")
    status: str = Field(..., description="状态，如 uploaded")


class DocParsedInfo(BaseModel):
    """解析结果（仅当 status=done 时返回）。"""
    school: str = ""
    major: str = ""
    course: str = ""
    knowledgePoints: list[str] = Field(default_factory=list)
    summary: str = ""


class DocItem(BaseModel):
    docId: str
    fileName: str
    status: str
    createdAt: str | None = None
    parsed: DocParsedInfo | None = None


class DocListResponse(BaseModel):
    items: list[DocItem] = Field(default_factory=list)
    total: int = 0
