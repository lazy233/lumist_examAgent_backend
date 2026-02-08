"""执行 001_add_user_profile_columns.sql：为 users 表增加个人中心字段。
与应用使用同一 DATABASE_URL（会从项目根目录 .env 加载环境变量）。"""
import os
import sys

# 项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

# 在导入 app 前加载 .env，保证与 uvicorn 启动时使用同一 DATABASE_URL
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


def _redact_url(url: str) -> str:
    """隐藏密码，便于日志核对连接的是哪个库。"""
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
    sql_file = migration_dir / "001_add_user_profile_columns.sql"
    if not sql_file.is_file():
        print(f"Migration file not found: {sql_file}")
        sys.exit(1)

    engine = create_engine(settings.database_url)
    db_url_display = _redact_url(settings.database_url)
    print(f"Using DB: {db_url_display}")

    with engine.connect() as conn:
        # 校验：当前 users 表有哪些列
        r = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' ORDER BY ordinal_position"
            )
        )
        columns_before = [row[0] for row in r]
        print(f"users 表当前列: {columns_before}")

        required = {"school", "major", "grade", "age", "gender", "question_type_preference", "difficulty_preference", "question_count"}
        missing = required - set(columns_before)
        if not missing:
            print("个人中心相关列已存在，无需执行迁移。")
            return

        print(f"缺少列，执行迁移: {missing}")
        sql = sql_file.read_text(encoding="utf-8")
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if not stmt or stmt.startswith("--"):
                continue
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"Skip (already exists): {stmt[:60]}...")
                else:
                    raise

        # 再次校验
        r2 = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' ORDER BY ordinal_position"
            )
        )
        columns_after = [row[0] for row in r2]
        print(f"迁移后 users 表列: {columns_after}")
        still_missing = required - set(columns_after)
        if still_missing:
            print(f"ERROR: 迁移后仍缺少列: {still_missing}")
            sys.exit(1)
    print("Migration 001_add_user_profile_columns completed.")


if __name__ == "__main__":
    main()
