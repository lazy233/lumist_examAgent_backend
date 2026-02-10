"""AI 出题：分析材料、流式生成题目；练习详情、提交答案、练习列表。"""
import asyncio
import json
import logging
import re
import time
import uuid

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Response

logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, get_db
from app.models.answer import Answer
from app.models.exercise import Exercise
from app.models.exercise_result import ExerciseResult
from app.models.question import Question
from app.repositories.user_repository import DEV_USER_ID, get_or_create_dev_user
from app.core.config import settings
from app.services.bailian_retrieve_service import retrieve_for_question_generation
from app.services.exercise_service import (
    DIFFICULTY_LABELS,
    QUESTION_TYPE_LABELS,
    analyze_material,
    analyze_rag_context,
    parse_and_save_questions,
    stream_raw_and_collect,
)
from app.services.file_analyze_service import analyze_file_for_questions

router = APIRouter()

# 前端 status：DB 存 generating / done / failed，接口返回 ready 表示可作答
STATUS_TO_API = {"generating": "generating", "done": "ready", "failed": "failed"}
# 前端题型：DB 可能存 judgment，接口返回 true_false
TYPE_TO_API = {"judgment": "true_false"}


# 视为纯文本、需要做编码归一化为 UTF-8 的扩展名（含中文等非 UTF-8 常见编码）
_TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".log", ".ini", ".cfg", ".conf"}
)


def _normalize_upload_to_utf8(content_bytes: bytes, suffix: str) -> bytes:
    """
    对文本类上传做编码归一化：尝试多种编码解码后统一以 UTF-8 写入，避免中文等编码无法解析。
    非文本扩展名（如 .pdf、.docx）原样返回，不修改。
    """
    suffix_lower = (suffix or "").strip().lower()
    if suffix_lower not in _TEXT_EXTENSIONS:
        return content_bytes
    # 常见编码顺序：UTF-8 -> GBK/GB18030（中文 Windows）-> Big5（繁体）-> Latin-1（兜底）
    for enc in ("utf-8", "gbk", "gb18030", "big5", "cp936", "latin-1"):
        try:
            text = content_bytes.decode(enc)
            return text.encode("utf-8")
        except (UnicodeDecodeError, LookupError):
            continue
    return content_bytes


def _options_list_to_object(options: list | None) -> dict[str, str]:
    """将 ['A. 内容', 'B. 内容'] 转为 {'A': '内容', 'B': '内容'}。"""
    if not options or not isinstance(options, list):
        return {}
    out: dict[str, str] = {}
    for item in options:
        if not isinstance(item, str):
            continue
        s = item.strip()
        m = re.match(r"^([A-D])[.、．]\s*(.*)$", s, re.IGNORECASE)
        if m:
            out[m.group(1).upper()] = m.group(2).strip() or s
        elif len(s) >= 2 and s[0].upper() in "ABCD":
            out[s[0].upper()] = s[1:].lstrip(".、． ").strip() or s
    return out


class AnalyzeRequest(BaseModel):
    content: str = Field(default="", description="用户输入的文字材料")
    question_type: str = Field(default="single_choice", alias="questionType")
    difficulty: str = Field(default="medium")
    count: int = Field(default=5, ge=1, description="题目数量，无上限")


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


class AnalyzeFileResponse(BaseModel):
    """文件分析结果，用户确认后可将 content、title 传给 generate-from-text。"""
    content: str = Field(..., description="分析得到的出题材料正文，即 generate-from-text 的 content")
    title: str = Field("", description="建议试卷标题，即 generate-from-text 的 title")
    usage: UsageInfo | None = Field(None, description="本次文件分析调用大模型消耗的 token")


@router.post("/exercises/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    分析材料，返回出题要点。用户确认后再调用 /exercises/generate-from-text。

    **注意**：此接口会调用大模型，响应时间通常为 20–60 秒。前端请将请求超时设为至少 **60 秒**（如 axios timeout: 60000），否则会报超时失败。
    """
    response.headers["X-Recommended-Client-Timeout"] = "60000"
    t0 = time.perf_counter()
    user = await get_or_create_dev_user(db)
    key_points, usage = await analyze_material(
        content=body.content,
        question_type=body.question_type,
        difficulty=body.difficulty,
        count=body.count,
    )
    # 标题：优先用第一个要点，否则用材料前 30 字
    content_stripped = (body.content or "").strip()
    title = ""
    if key_points:
        title = (key_points[0] or "").strip()
    if not title and content_stripped:
        title = content_stripped[:30] + "…" if len(content_stripped) > 30 else content_stripped
    if not title:
        title = "AI 出题练习"

    logger.info("[analyze] 分析材料总耗时 %.2fs", time.perf_counter() - t0)
    usage_info = UsageInfo(**usage) if usage else None
    return AnalyzeResponse(
        keyPoints=key_points,
        title=title,
        questionType=body.question_type,
        questionTypeLabel=QUESTION_TYPE_LABELS.get(body.question_type, body.question_type),
        difficulty=body.difficulty,
        difficultyLabel=DIFFICULTY_LABELS.get(body.difficulty, body.difficulty),
        count=body.count,
        usage=usage_info,
    )


@router.post("/exercises/analyze-file", response_model=AnalyzeFileResponse)
async def analyze_file(
    file: UploadFile = File(..., description="待分析的文档（如 .txt / .pdf 等）"),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文件，调用大模型（qwen-long）分析文档内容，得到出题材料。
    用户确认后，将返回的 content、title 作为请求体调用 POST /exercises/generate-from-text 生成题目。
    """
    await get_or_create_dev_user(db)
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="请上传文件")
    suffix = Path(file.filename).suffix or ".txt"
    try:
        content_bytes = await file.read()
        normalized_bytes = _normalize_upload_to_utf8(content_bytes, suffix)
        def _write_tmp_file(data: bytes, suffix_name: str) -> str:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix_name) as tmp:
                tmp.write(data)
                return tmp.name

        tmp_path = await asyncio.to_thread(_write_tmp_file, normalized_bytes, suffix)
        try:
            content, title, usage = await analyze_file_for_questions(tmp_path)
            usage_info = UsageInfo(**usage) if usage else None
            return AnalyzeFileResponse(content=content, title=title or "", usage=usage_info)
        finally:
            try:
                await asyncio.to_thread(Path(tmp_path).unlink, missing_ok=True)
            except Exception as e:
                logger.warning("删除临时文件失败 %s: %s", tmp_path, e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("文件分析失败: %s", e)
        raise HTTPException(status_code=500, detail="文件分析失败，请稍后重试")


async def _log_rag_recall(exercise_id: str, nodes: list) -> None:
    """输出 RAG 召回结果，便于调试。"""
    if not nodes:
        logger.info("[RAG 召回] exercise_id=%s 无召回片段", exercise_id)
        return
    logger.info("[RAG 召回] exercise_id=%s 共 %d 条:", exercise_id, len(nodes))
    for i, node in enumerate(nodes, 1):
        score = node.get("score")
        text = (node.get("text") or "")[:200]
        if len((node.get("text") or "")) > 200:
            text += "..."
        logger.info("  [%d] score=%s | %s", i, score, text)
    debug_dir = getattr(settings, "debug_dir", None)
    if debug_dir:
        import aiofiles
        import os
        await asyncio.to_thread(os.makedirs, debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, f"rag_recall_{exercise_id}.json")
        try:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(nodes, ensure_ascii=False, indent=2))
            logger.info("[RAG 召回] 已写入 %s", path)
        except Exception as e:
            logger.warning("[RAG 召回] 写入调试文件失败: %s", e)


async def _stream_generate(
    content: str,
    question_type: str,
    difficulty: str,
    count: int,
    exercise_id: str,
    rag_context: str | None = None,
    intent_context: str | None = None,
):
    """
    流式生成：先 yield 模型内容，收集完整后用新 session 解析落库，最后 yield 一行 JSON exerciseId。
    若传入 rag_context，会拼入生成 prompt 的「知识库参考」部分。
    不在闭包中使用请求级 db，因返回 StreamingResponse 后 session 会被关闭。
    """
    buffer: list[str] = []
    final_usage: dict | None = None
    try:
        async for chunk in stream_raw_and_collect(
            content=content,
            question_type=question_type,
            difficulty=difficulty,
            count=count,
            rag_context=rag_context,
            intent_context=intent_context,
        ):
            if isinstance(chunk, dict) and "_usage" in chunk:
                final_usage = chunk["_usage"]
                continue
            buffer.append(chunk)
            yield chunk
    except Exception as e:
        logger.exception("流式生成题目时出错: %s", e)
        yield "\n"
        yield json.dumps({"error": "生成失败", "exerciseId": exercise_id})
        return
    full = "".join(buffer)
    logger.info("[generate-from-text] 流式结束 exercise_id=%s 收集长度=%d", exercise_id, len(full))
    # 调试：控制台打印大模型生成的完整内容
    print("\n" + "=" * 60 + " [大模型生成题目-完整内容] exercise_id=%s " % exercise_id + "=" * 60)
    print(full)
    print("=" * 60 + " [完整内容结束] " + "=" * 60 + "\n")
    async with SessionLocal() as db:
        parse_ok = False
        try:
            logger.info("[generate-from-text] 开始解析并落库 exercise_id=%s", exercise_id)
            await parse_and_save_questions(
                full_content=full,
                exercise_id=exercise_id,
                question_type=question_type,
                db_session=db,
            )
            parse_ok = True
            logger.info("[generate-from-text] 解析落库成功 exercise_id=%s 状态已设为 done", exercise_id)
        except Exception as e:
            logger.exception("[generate-from-text] 解析或落库失败 exercise_id=%s: %s", exercise_id, e)
            try:
                await db.rollback()  # 先回滚，否则 session 处于 PendingRollback 无法再查询
                result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
                ex = result.scalars().first()
                if ex:
                    ex.status = "failed"
                    await db.commit()
                    logger.info("[generate-from-text] 已将练习状态设为 failed exercise_id=%s", exercise_id)
                else:
                    logger.warning("[generate-from-text] 未找到练习无法设为 failed exercise_id=%s", exercise_id)
            except Exception as e2:
                logger.exception("[generate-from-text] 更新状态为 failed 时出错: %s", e2)
                await db.rollback()
    yield "\n"
    payload: dict = {"exerciseId": exercise_id}
    if final_usage is not None:
        payload["usage"] = final_usage
    yield json.dumps(payload)


def _exercise_title_from_request(title: str | None, content: str) -> str:
    """请求里的 title 若为空，则用 content 前 30 字或默认标题。"""
    t = (title or "").strip()
    if t:
        return t
    c = (content or "").strip()
    if c:
        return c[:30] + "…" if len(c) > 30 else c
    return "AI 出题练习"


@router.post("/exercises/generate-from-text")
async def generate_from_text(
    body: GenerateFromTextRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    流式生成题目。响应为 text/event-stream 或普通流式文本，最后一行为 JSON：{"exerciseId": "xxx"}。
    """
    user = await get_or_create_dev_user(db)
    exercise_id = str(uuid.uuid4())
    title = _exercise_title_from_request(body.title, body.content)
    exercise = Exercise(
        id=exercise_id,
        owner_id=user.id,
        title=title,
        status="generating",
        difficulty=body.difficulty,
        count=body.count,
        question_type=body.question_type,
        source_doc_id=None,
    )
    db.add(exercise)
    await db.commit()

    # 组合用户意图（标题/题型/难度/数量/要点/分析）
    intent_parts = [
        f"标题：{title}",
        f"题型：{QUESTION_TYPE_LABELS.get(body.question_type, body.question_type)}",
        f"难度：{DIFFICULTY_LABELS.get(body.difficulty, body.difficulty)}",
        f"数量：{body.count}",
    ]
    if body.key_points:
        intent_parts.append("要点：" + "；".join([str(x) for x in body.key_points if str(x).strip()]))
    if body.analysis:
        intent_parts.append("分析：" + body.analysis.strip())
    intent_text = "\n".join([x for x in intent_parts if x.strip()])

    # 第二次调用前：RAG 检索知识库，并对召回内容做梳理再作为知识库参考（此处耗时易导致「首包很慢」）
    t0 = time.perf_counter()
    rag_nodes, rag_text = await retrieve_for_question_generation(body.content)
    logger.info("[generate-from-text] RAG 检索耗时 %.2fs", time.perf_counter() - t0)
    await _log_rag_recall(exercise_id, rag_nodes)
    if rag_text and rag_text.strip():
        if getattr(settings, "skip_rag_analyze", False):
            rag_context = rag_text.strip()
            logger.info("[generate-from-text] 已跳过 RAG 梳理（SKIP_RAG_ANALYZE=true），使用原文")
        else:
            t1 = time.perf_counter()
            rag_context = await analyze_rag_context(rag_text)
            logger.info("[generate-from-text] RAG 梳理耗时 %.2fs", time.perf_counter() - t1)
    else:
        rag_context = None
    logger.info("[generate-from-text] 首包前总耗时（RAG+梳理）%.2fs", time.perf_counter() - t0)
    async def gen():
        async for chunk in _stream_generate(
            content=body.content,
            question_type=body.question_type,
            difficulty=body.difficulty,
            count=body.count,
            exercise_id=exercise_id,
            rag_context=rag_context,
            intent_context=intent_text,
        ):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 练习详情、提交答案、练习列表 ----------


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


@router.get("/exercises/{exercise_id}", response_model=ExerciseDetailResponse)
async def get_exercise_detail(
    exercise_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取练习详情。status 为 generating 时前端可轮询；ready 表示可作答。
    """
    await get_or_create_dev_user(db)
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalars().first()
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")
    questions_result = await db.execute(
        select(Question)
        .where(Question.exercise_id == exercise_id)
        .order_by(Question.created_at.asc())
    )
    questions = questions_result.scalars().all()
    status_api = STATUS_TO_API.get(exercise.status, exercise.status)
    question_items = []
    for q in questions:
        type_api = TYPE_TO_API.get(q.type, q.type)
        opts = _options_list_to_object(q.options) if q.options else None
        if opts == {}:
            opts = None
        question_items.append(
            QuestionItem(
                questionId=q.id,
                type=type_api,
                stem=q.stem,
                options=opts,
            )
        )
    created_at = exercise.created_at.isoformat() if exercise.created_at else ""
    question_type = exercise.question_type or (questions[0].type if questions else "single_choice")
    question_type_label = QUESTION_TYPE_LABELS.get(question_type, question_type)
    # 若已提交过，返回最后一次得分
    last_result_res = await db.execute(
        select(ExerciseResult)
        .where(
            ExerciseResult.exercise_id == exercise_id,
            ExerciseResult.owner_id == DEV_USER_ID,
        )
        .order_by(ExerciseResult.submitted_at.desc())
    )
    last_result = last_result_res.scalars().first()
    score = last_result.score if last_result else None
    return ExerciseDetailResponse(
        exerciseId=exercise.id,
        title=exercise.title,
        status=status_api,
        difficulty=exercise.difficulty,
        count=exercise.count,
        questionType=question_type,
        questionTypeLabel=question_type_label,
        questions=question_items,
        createdAt=created_at,
        score=score,
    )


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


@router.post("/exercises/{exercise_id}/submit", response_model=SubmitResponse)
async def submit_exercise(
    exercise_id: str,
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    提交答案，返回得分、正确率及每题对错与解析。
    """
    user = await get_or_create_dev_user(db)
    exercise_result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = exercise_result.scalars().first()
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")
    questions_result = await db.execute(select(Question).where(Question.exercise_id == exercise_id))
    questions = questions_result.scalars().all()
    q_by_id = {q.id: q for q in questions}
    answers_by_qid = {
        a.question_id: a
        for a in (
            await db.execute(
                select(Answer).where(Answer.question_id.in_(q_by_id.keys()))
            )
        )
        .scalars()
        .all()
    }
    user_answers = {a.questionId: a.answer for a in body.answers}
    results: list[ResultItem] = []
    correct_count = 0
    for q in questions:
        ans = answers_by_qid.get(q.id)
        correct = (ans.correct_answer or "").strip() if ans else ""
        user_ans = (user_answers.get(q.id) or "").strip()
        is_correct = user_ans == correct
        if is_correct:
            correct_count += 1
        results.append(
            ResultItem(
                questionId=q.id,
                isCorrect=is_correct,
                userAnswer=user_ans,
                correctAnswer=correct,
                analysis=ans.analysis if ans else None,
            )
        )
    total = len(questions)
    correct_rate = correct_count / total if total else 0.0
    score = int(round(100 * correct_rate)) if total else 0
    result_id = str(uuid.uuid4())
    result_details = [
        {
            "questionId": r.questionId,
            "isCorrect": r.isCorrect,
            "userAnswer": r.userAnswer,
            "correctAnswer": r.correctAnswer,
            "analysis": r.analysis,
        }
        for r in results
    ]
    er = ExerciseResult(
        id=result_id,
        exercise_id=exercise_id,
        owner_id=user.id,
        score=score,
        correct_rate=int(round(100 * correct_rate)),
        result_details=result_details,
    )
    db.add(er)
    await db.commit()
    return SubmitResponse(
        score=score,
        correctRate=round(correct_rate, 2),
        results=results,
    )


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


@router.delete("/exercises/{exercise_id}", status_code=204)
async def delete_exercise(
    exercise_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除练习。按外键依赖顺序删除：作答记录 -> 答案 -> 题目 -> 练习，确保无外键约束错误。
    """
    await get_or_create_dev_user(db)
    exercise_result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = exercise_result.scalars().first()
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")

    question_result = await db.execute(select(Question.id).where(Question.exercise_id == exercise_id))
    question_ids = [row[0] for row in question_result.all()]

    # 按依赖顺序删除，每步 flush 确保子表先落盘再删父表，避免外键约束
    await db.execute(
        ExerciseResult.__table__.delete().where(ExerciseResult.exercise_id == exercise_id)
    )
    await db.flush()
    if question_ids:
        await db.execute(Answer.__table__.delete().where(Answer.question_id.in_(question_ids)))
        await db.flush()
    await db.execute(Question.__table__.delete().where(Question.exercise_id == exercise_id))
    await db.flush()
    await db.execute(Exercise.__table__.delete().where(Exercise.id == exercise_id))
    await db.commit()


@router.get("/exercises", response_model=dict)
async def list_exercises(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    keyword: str | None = Query(None, description="按练习标题关键词筛选"),
    difficulty: str | None = Query(None, description="按难度筛选：easy / medium / hard"),
    questionType: str | None = Query(None, alias="questionType", description="按题型筛选：single_choice / multiple_choice / judgment / fill_blank / short_answer"),
    db: AsyncSession = Depends(get_db),
):
    """
    练习列表（历史练习）。支持 keyword（标题）、difficulty、questionType（题型）筛选。返回 items 与 total。
    """
    user = await get_or_create_dev_user(db)
    q = select(Exercise).where(Exercise.owner_id == DEV_USER_ID)
    if keyword is not None and keyword.strip():
        q = q.where(Exercise.title.ilike(f"%{keyword.strip()}%"))
    if difficulty is not None and difficulty.strip():
        q = q.where(Exercise.difficulty == difficulty.strip())
    if questionType is not None and questionType.strip():
        q = q.where(Exercise.question_type == questionType.strip())
    count_stmt = select(func.count()).select_from(Exercise).where(Exercise.owner_id == DEV_USER_ID)
    if keyword is not None and keyword.strip():
        count_stmt = count_stmt.where(Exercise.title.ilike(f"%{keyword.strip()}%"))
    if difficulty is not None and difficulty.strip():
        count_stmt = count_stmt.where(Exercise.difficulty == difficulty.strip())
    if questionType is not None and questionType.strip():
        count_stmt = count_stmt.where(Exercise.question_type == questionType.strip())
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        q.order_by(Exercise.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    )
    items = result.scalars().all()
    out_items = []
    for ex in items:
        status_api = STATUS_TO_API.get(ex.status, ex.status)
        q_type = ex.question_type
        if not q_type:
            first_q = await db.execute(
                select(Question.type).where(Question.exercise_id == ex.id).order_by(Question.created_at.asc()).limit(1)
            )
            q_type = first_q.scalar_one_or_none() or "single_choice"
        q_type_label = QUESTION_TYPE_LABELS.get(q_type, q_type)
        qcount_res = await db.execute(
            select(func.count()).select_from(Question).where(Question.exercise_id == ex.id)
        )
        question_count = qcount_res.scalar_one()
        last_result_res = await db.execute(
            select(ExerciseResult)
            .where(
                ExerciseResult.exercise_id == ex.id,
                ExerciseResult.owner_id == user.id,
            )
            .order_by(ExerciseResult.submitted_at.desc())
        )
        last_result = last_result_res.scalars().first()
        score = last_result.score if last_result else None
        out_items.append(
            ExerciseListItem(
                exerciseId=ex.id,
                title=ex.title,
                status=status_api,
                difficulty=ex.difficulty,
                count=ex.count,
                questionType=q_type,
                questionTypeLabel=q_type_label,
                questionCount=question_count,
                createdAt=ex.created_at.isoformat() if ex.created_at else "",
                score=score,
            )
        )
    return {"items": out_items, "total": total}
