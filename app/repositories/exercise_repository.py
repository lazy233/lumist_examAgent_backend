"""练习（Exercise）、题目（Question）、答案（Answer）、作答结果（ExerciseResult）数据访问层。"""
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer
from app.models.exercise import Exercise
from app.models.exercise_result import ExerciseResult
from app.models.question import Question


async def get_exercise_by_id(db: AsyncSession, exercise_id: str) -> Exercise | None:
    """按 ID 查询练习，不存在返回 None。"""
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    return result.scalars().first()


async def create_exercise(
    db: AsyncSession,
    *,
    exercise_id: str,
    owner_id: str,
    title: str,
    status: str = "generating",
    difficulty: str,
    count: int,
    question_type: str,
    source_doc_id: str | None = None,
) -> Exercise:
    """创建练习记录。"""
    exercise = Exercise(
        id=exercise_id,
        owner_id=owner_id,
        title=title,
        status=status,
        difficulty=difficulty,
        count=count,
        question_type=question_type,
        source_doc_id=source_doc_id,
    )
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)
    return exercise


async def list_exercises(
    db: AsyncSession,
    owner_id: str,
    *,
    keyword: str | None = None,
    difficulty: str | None = None,
    question_type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Exercise], int]:
    """分页列出某用户的练习，支持 keyword、difficulty、questionType 筛选。返回 (items, total)。"""
    q = select(Exercise).where(Exercise.owner_id == owner_id)
    count_stmt = select(func.count()).select_from(Exercise).where(Exercise.owner_id == owner_id)
    if keyword and keyword.strip():
        q = q.where(Exercise.title.ilike(f"%{keyword.strip()}%"))
        count_stmt = count_stmt.where(Exercise.title.ilike(f"%{keyword.strip()}%"))
    if difficulty and difficulty.strip():
        q = q.where(Exercise.difficulty == difficulty.strip())
        count_stmt = count_stmt.where(Exercise.difficulty == difficulty.strip())
    if question_type and question_type.strip():
        q = q.where(Exercise.question_type == question_type.strip())
        count_stmt = count_stmt.where(Exercise.question_type == question_type.strip())
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        q.order_by(Exercise.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return list(items), total


async def get_questions_by_exercise_id(db: AsyncSession, exercise_id: str) -> list[Question]:
    """按练习 ID 查询题目列表，按 created_at 升序。"""
    result = await db.execute(
        select(Question)
        .where(Question.exercise_id == exercise_id)
        .order_by(Question.created_at.asc())
    )
    return list(result.scalars().all())


async def get_question_type_by_exercise_id(db: AsyncSession, exercise_id: str) -> str | None:
    """取该练习下第一题的题型（用于列表展示）。"""
    result = await db.execute(
        select(Question.type).where(Question.exercise_id == exercise_id).order_by(Question.created_at.asc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_question_types_by_exercise_ids(db: AsyncSession, exercise_ids: list[str]) -> dict[str, str]:
    """批量取各练习下第一题的题型。返回 {exercise_id: type}，无题目则为空或不含该 key。"""
    if not exercise_ids:
        return {}
    # 每个 exercise_id 取 created_at 最小的一题的 type（用 distinct on 或 row_number）
    subq = (
        select(
            Question.exercise_id,
            Question.type,
            func.row_number().over(
                partition_by=[Question.exercise_id],
                order_by=Question.created_at.asc(),
            ).label("rn"),
        ).where(Question.exercise_id.in_(exercise_ids))
    ).subquery()
    stmt = select(subq.c.exercise_id, subq.c.type).where(subq.c.rn == 1)
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def get_question_count_by_exercise_id(db: AsyncSession, exercise_id: str) -> int:
    """某练习下的题目数量。"""
    result = await db.execute(select(func.count()).select_from(Question).where(Question.exercise_id == exercise_id))
    return result.scalar_one() or 0


async def get_question_counts_by_exercise_ids(db: AsyncSession, exercise_ids: list[str]) -> dict[str, int]:
    """批量查询各练习的题目数量。返回 {exercise_id: count}。"""
    if not exercise_ids:
        return {}
    result = await db.execute(
        select(Question.exercise_id, func.count(Question.id))
        .where(Question.exercise_id.in_(exercise_ids))
        .group_by(Question.exercise_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def get_answers_by_question_ids(db: AsyncSession, question_ids: list[str]) -> list[Answer]:
    """按题目 ID 列表查询答案。"""
    if not question_ids:
        return []
    result = await db.execute(select(Answer).where(Answer.question_id.in_(question_ids)))
    return list(result.scalars().all())


async def get_latest_exercise_result(
    db: AsyncSession,
    exercise_id: str,
    owner_id: str,
) -> ExerciseResult | None:
    """某用户在某练习下最近一次作答结果。"""
    result = await db.execute(
        select(ExerciseResult)
        .where(
            ExerciseResult.exercise_id == exercise_id,
            ExerciseResult.owner_id == owner_id,
        )
        .order_by(ExerciseResult.submitted_at.desc())
    )
    return result.scalars().first()


async def get_latest_scores_by_exercise_ids(
    db: AsyncSession,
    exercise_ids: list[str],
    owner_id: str,
) -> dict[str, int | None]:
    """
    批量查询某用户在各练习下的最近一次得分。返回 {exercise_id: score}，未提交过为 None。
    用子查询取每个 exercise_id 下该 owner 的 submitted_at 最大的一条，再取 score。
    """
    if not exercise_ids:
        return {}
    # 每个 exercise_id 取该 owner 最近一次作答的 score（row_number + 取 rn==1）
    subq = (
        select(
            ExerciseResult.exercise_id,
            ExerciseResult.score,
            func.row_number().over(
                partition_by=[ExerciseResult.exercise_id],
                order_by=ExerciseResult.submitted_at.desc(),
            ).label("rn"),
        )
        .where(
            ExerciseResult.exercise_id.in_(exercise_ids),
            ExerciseResult.owner_id == owner_id,
        )
    ).subquery()
    stmt = select(subq.c.exercise_id, subq.c.score).where(subq.c.rn == 1)
    result = await db.execute(stmt)
    out = {row[0]: row[1] for row in result.all()}
    for eid in exercise_ids:
        if eid not in out:
            out[eid] = None
    return out


async def create_exercise_result(
    db: AsyncSession,
    *,
    result_id: str,
    exercise_id: str,
    owner_id: str,
    score: int,
    correct_rate: int,
    result_details: list[dict],
) -> ExerciseResult:
    """创建作答记录。"""
    er = ExerciseResult(
        id=result_id,
        exercise_id=exercise_id,
        owner_id=owner_id,
        score=score,
        correct_rate=correct_rate,
        result_details=result_details,
    )
    db.add(er)
    await db.commit()
    await db.refresh(er)
    return er


async def add_question(
    db: AsyncSession,
    *,
    question_id: str,
    exercise_id: str,
    type: str,
    stem: str,
    options: list | None = None,
) -> Question:
    """插入一道题目并 flush（便于紧接着插入 answer）。"""
    q = Question(
        id=question_id,
        exercise_id=exercise_id,
        type=type,
        stem=stem,
        options=options,
    )
    db.add(q)
    await db.flush()
    return q


async def add_answer(
    db: AsyncSession,
    *,
    answer_id: str,
    question_id: str,
    correct_answer: str,
    analysis: str | None = None,
) -> Answer:
    """插入一条答案（不 commit，与 add_question 同事务）。"""
    a = Answer(
        id=answer_id,
        question_id=question_id,
        correct_answer=correct_answer,
        analysis=analysis,
    )
    db.add(a)
    return a


async def set_exercise_status(db: AsyncSession, exercise_id: str, status: str) -> None:
    """更新练习状态并 commit。"""
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    ex = result.scalars().first()
    if ex:
        ex.status = status
    await db.commit()


async def delete_exercise_cascade(db: AsyncSession, exercise_id: str) -> None:
    """按外键依赖顺序删除：作答记录 -> 答案 -> 题目 -> 练习。"""
    question_ids_result = await db.execute(select(Question.id).where(Question.exercise_id == exercise_id))
    question_ids = [row[0] for row in question_ids_result.all()]

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
