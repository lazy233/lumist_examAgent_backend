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
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.repositories.exercise_repository import (
    create_exercise,
    create_exercise_result,
    delete_exercise_cascade,
    get_answers_by_question_ids,
    get_exercise_by_id,
    get_latest_exercise_result,
    get_latest_scores_by_exercise_ids,
    get_question_counts_by_exercise_ids,
    get_question_types_by_exercise_ids,
    get_questions_by_exercise_id,
    list_exercises as repo_list_exercises,
    set_exercise_status,
)
from app.repositories.user_repository import DEV_USER_ID, get_or_create_dev_user
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
    SubmitRequest,
    SubmitResponse,
    UsageInfo,
)
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

logger = logging.getLogger(__name__)
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


@router.post("/exercises/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    分析材料（粘贴/输入文字），返回出题要点。用户确认后再调用 /exercises/generate-from-text。
    注意：只有「上传文件」会走 /exercises/analyze-file，才会打印 file_analyze_service 的提示词。

    **注意**：此接口会调用大模型，响应时间通常为 20–60 秒。前端请将请求超时设为至少 **60 秒**（如 axios timeout: 60000），否则会报超时失败。
    """
    response.headers["X-Recommended-Client-Timeout"] = "60000"
    logger.info("[analyze] 收到请求：文字材料分析（非上传文件），将使用 analyze_material")
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
    logger.info("[analyze-file] 收到请求：上传文件分析 filename=%s，将使用 file_analyze_service", file.filename or "")
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
                await db.rollback()
                await set_exercise_status(db, exercise_id, "failed")
                logger.info("[generate-from-text] 已将练习状态设为 failed exercise_id=%s", exercise_id)
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
    await create_exercise(
        db,
        exercise_id=exercise_id,
        owner_id=user.id,
        title=title,
        status="generating",
        difficulty=body.difficulty,
        count=body.count,
        question_type=body.question_type,
        source_doc_id=None,
    )

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


@router.get("/exercises/{exercise_id}", response_model=ExerciseDetailResponse)
async def get_exercise_detail(
    exercise_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取练习详情。status 为 generating 时前端可轮询；ready 表示可作答。
    """
    await get_or_create_dev_user(db)
    exercise = await get_exercise_by_id(db, exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")
    questions = await get_questions_by_exercise_id(db, exercise_id)
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
    last_result = await get_latest_exercise_result(db, exercise_id, DEV_USER_ID)
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
    exercise = await get_exercise_by_id(db, exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")
    questions = await get_questions_by_exercise_id(db, exercise_id)
    q_by_id = {q.id: q for q in questions}
    question_ids = list(q_by_id.keys())
    answers = await get_answers_by_question_ids(db, question_ids)
    answers_by_qid = {a.question_id: a for a in answers}
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
    await create_exercise_result(
        db,
        result_id=result_id,
        exercise_id=exercise_id,
        owner_id=user.id,
        score=score,
        correct_rate=int(round(100 * correct_rate)),
        result_details=result_details,
    )
    return SubmitResponse(
        score=score,
        correctRate=round(correct_rate, 2),
        results=results,
    )


@router.delete("/exercises/{exercise_id}", status_code=204)
async def delete_exercise(
    exercise_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除练习。按外键依赖顺序删除：作答记录 -> 答案 -> 题目 -> 练习，确保无外键约束错误。
    """
    await get_or_create_dev_user(db)
    exercise = await get_exercise_by_id(db, exercise_id)
    if not exercise:
        raise HTTPException(status_code=404, detail="exercise not found")
    await delete_exercise_cascade(db, exercise_id)


@router.get("/exercises", response_model=ExerciseListResponse)
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
    items, total = await repo_list_exercises(
        db,
        DEV_USER_ID,
        keyword=keyword,
        difficulty=difficulty,
        question_type=questionType,
        page=page,
        page_size=pageSize,
    )
    if not items:
        return ExerciseListResponse(items=[], total=total)
    exercise_ids = [ex.id for ex in items]
    question_counts = await get_question_counts_by_exercise_ids(db, exercise_ids)
    question_types = await get_question_types_by_exercise_ids(db, exercise_ids)
    scores = await get_latest_scores_by_exercise_ids(db, exercise_ids, user.id)
    out_items = []
    for ex in items:
        status_api = STATUS_TO_API.get(ex.status, ex.status)
        q_type = ex.question_type or question_types.get(ex.id) or "single_choice"
        q_type_label = QUESTION_TYPE_LABELS.get(q_type, q_type)
        question_count = question_counts.get(ex.id, 0)
        score = scores.get(ex.id)
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
    return ExerciseListResponse(items=out_items, total=total)
