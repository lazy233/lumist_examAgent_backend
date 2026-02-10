"""执行 002_add_exercise_question_type.sql：为 exercises 表增加 question_type 字段并回填。
与应用使用同一 DATABASE_URL（会从项目根目录 .env 加载环境变量）。"""
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

from sqlalchemy import text, create_engine

from app.core.config import settings


def _sync_database_url(url: str) -> str:
    """转为同步驱动 URL（psycopg2），便于迁移脚本使用。"""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
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


def main():
    migration_dir = Path(_project_root) / "sql" / "migrations"
    sql_file = migration_dir / "002_add_exercise_question_type.sql"
    if not sql_file.is_file():
        print(f"Migration file not found: {sql_file}")
        sys.exit(1)

    sync_url = _sync_database_url(settings.database_url)
    engine = create_engine(sync_url)
    print(f"Using DB: {_redact_url(sync_url)}")

    full_sql = sql_file.read_text(encoding="utf-8").strip()
    # 1) DO 块（含 ADD COLUMN）
    do_block = """DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'exercises' AND column_name = 'question_type'
    ) THEN
        ALTER TABLE exercises ADD COLUMN question_type VARCHAR(30);
    END IF;
END $$;"""
    # 2) 回填
    update_sql = """UPDATE exercises e
SET question_type = (
    SELECT q.type FROM questions q WHERE q.exercise_id = e.id ORDER BY q.created_at ASC LIMIT 1
)
WHERE e.question_type IS NULL;"""
    # 3) 索引
    index_sql = "CREATE INDEX IF NOT EXISTS idx_exercises_question_type ON exercises(question_type);"

    with engine.connect() as conn:
        for name, stmt in [("DO (add column)", do_block), ("UPDATE (backfill)", update_sql), ("CREATE INDEX", index_sql)]:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"OK: {name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"Skip: {name} (already exists)")
                    conn.rollback()
                else:
                    raise

    print("Migration 002_add_exercise_question_type completed.")


if __name__ == "__main__":
    main()
