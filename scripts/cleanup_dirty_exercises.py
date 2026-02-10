"""清理练习相关脏数据：无题目的空练习、长期处于 generating 的练习。
使用方式（在项目根目录）：
  python scripts/cleanup_dirty_exercises.py
  python scripts/cleanup_dirty_exercises.py --dry-run   # 只打印将删除的 ID，不执行
  python scripts/cleanup_dirty_exercises.py --stale-hours 48   # 超过 48 小时的 generating 才删
"""
import argparse
import io
import sys

# 避免 Windows 终端中文乱码
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

# 加载 .env
_env_file = os.path.join(_project_root, ".env")
if os.path.isfile(_env_file):
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and os.environ.get(k) is None:
                    os.environ[k] = v

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.answer import Answer
from app.models.exercise import Exercise
from app.models.exercise_result import ExerciseResult
from app.models.question import Question


async def delete_exercise_cascade(db, exercise_id: str) -> None:
    """按外键顺序删除一条练习及其作答、答案、题目。与 API delete_exercise 逻辑一致。"""
    question_result = await db.execute(select(Question.id).where(Question.exercise_id == exercise_id))
    question_ids = [row[0] for row in question_result.all()]

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


async def run_cleanup(dry_run: bool = False, stale_hours: int = 24) -> None:
    async with SessionLocal() as db:
        # 1) 空练习：没有任何题目的 exercise
        subq = select(Question.exercise_id).distinct()
        r_empty = await db.execute(select(Exercise.id).where(~Exercise.id.in_(subq)))
        empty_ids = [row[0] for row in r_empty.all()]

        # 2) 长期处于 generating 的练习（超过 stale_hours 小时）
        cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        r_stale = await db.execute(
            select(Exercise.id).where(
                Exercise.status == "generating",
                Exercise.created_at < cutoff,
            )
        )
        stale_ids = [row[0] for row in r_stale.all()]

        to_delete = list(set(empty_ids) | set(stale_ids))
        if not to_delete:
            print("没有需要清理的脏数据。")
            return

        print(f"将清理 {len(to_delete)} 条练习：空练习 {len(empty_ids)} 条，超时 generating {len(stale_ids)} 条")
        print("exercise_id 列表:", to_delete[:20], "..." if len(to_delete) > 20 else "")

        if dry_run:
            print("[dry-run] 未执行删除。去掉 --dry-run 后重新运行将真正删除。")
            return

        for eid in to_delete:
            await delete_exercise_cascade(db, eid)
        await db.commit()
        print(f"已删除 {len(to_delete)} 条脏数据。")


def main():
    parser = argparse.ArgumentParser(description="清理练习脏数据（空练习、长期 generating）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要删除的 ID，不执行删除",
    )
    parser.add_argument(
        "--stale-hours",
        type=int,
        default=24,
        help="超过多少小时的 generating 视为脏数据（默认 24）",
    )
    args = parser.parse_args()
    asyncio.run(run_cleanup(dry_run=args.dry_run, stale_hours=args.stale_hours))


if __name__ == "__main__":
    main()
