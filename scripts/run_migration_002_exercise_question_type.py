"""执行 002_add_exercise_question_type.sql：为 exercises 表增加 question_type 字段并回填。
使用 asyncpg（与应用一致），不依赖 psycopg2。"""
import asyncio
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

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

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


def _async_database_url(url: str) -> str:
    """确保为 asyncpg URL。"""
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _redact_url(url: str) -> str:
    if "@" in url and "//" in url:
        pre, _, rest = url.partition("//")
        if "@" in rest:
            user_part, _, host_part = rest.rpartition("@")
            if ":" in user_part:
                user = user_part.split(":")[0]
                return f"{pre}//{user}:****@{host_part}"
    return url


async def main():
    migration_dir = Path(_project_root) / "sql" / "migrations"
    sql_file = migration_dir / "002_add_exercise_question_type.sql"
    if not sql_file.is_file():
        print(f"Migration file not found: {sql_file}")
        sys.exit(1)

    url = _async_database_url(settings.database_url)
    engine = create_async_engine(url)
    print(f"Using DB: {_redact_url(url)}")

    do_block = """DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'exercises' AND column_name = 'question_type'
    ) THEN
        ALTER TABLE exercises ADD COLUMN question_type VARCHAR(30);
    END IF;
END $$;"""
    update_sql = """UPDATE exercises e
SET question_type = (
    SELECT q.type FROM questions q WHERE q.exercise_id = e.id ORDER BY q.created_at ASC LIMIT 1
)
WHERE e.question_type IS NULL;"""
    index_sql = "CREATE INDEX IF NOT EXISTS idx_exercises_question_type ON exercises(question_type);"

    async with engine.begin() as conn:
        for name, stmt in [("DO (add column)", do_block), ("UPDATE (backfill)", update_sql), ("CREATE INDEX", index_sql)]:
            try:
                await conn.execute(text(stmt))
                print(f"OK: {name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"Skip: {name} (already exists)")
                else:
                    raise

    await engine.dispose()
    print("Migration 002_add_exercise_question_type completed.")


if __name__ == "__main__":
    asyncio.run(main())
