# Lumist ExamAgent Backend

AI 出题与练习后端服务（FastAPI + PostgreSQL）。

## 本地运行

```bash
# 依赖
pip install -r requirements.txt

# 环境变量（可选，可放在项目根目录 .env）
# DATABASE_URL=postgresql+psycopg2://user:pass@host:port/dbname

# 数据库迁移（users 表个人中心字段）
python scripts/run_migration_001_user_profile.py

# 启动
uvicorn app.main:app --reload
```

## 仓库与协作

- 仓库：<https://github.com/lazy233/lumist_examAgent_backend>
- 主分支不直接 push，请通过 **Pull Request** 合并，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。
